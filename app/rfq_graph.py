from __future__ import annotations

import time
from decimal import Decimal
from typing import Any, Literal, TypedDict

from langchain_core.tools import tool
from langgraph.graph import END, START, StateGraph
from prometheus_client import Histogram

from app.agent_engine import (
    DEFAULT_HF_MODEL,
    ExtractedRfq,
    extract_intent_with_hf,
)
from app.credit_rag import retrieve_credit_context
from app.reference_data import get_bond_snapshot, get_credit_capacity
from app.specialist_agents import assess_credit_risk, assess_inventory, assess_pricing


AGENT_DURATION = Histogram(
    "rfq_agent_duration_seconds",
    "Execution duration of each RFQ graph node",
    ["agent"],
)


class RfqState(TypedDict, total=False):
    raw_text: str
    client_id: str
    hf_token: str | None
    hf_model: str
    rfq: ExtractedRfq | None
    extraction_errors: list[str]
    intent_provider: str
    steps: list[dict[str, Any]]
    credit_decision: dict[str, Any]
    inventory_decision: dict[str, Any]
    credit_assessment: dict[str, Any]
    inventory_assessment: dict[str, Any]
    pricing_assessment: dict[str, Any]
    credit_context: list[dict[str, str]]
    intent_duration_ms: float
    credit_duration_ms: float
    inventory_duration_ms: float
    pricing_duration_ms: float
    manual_review_duration_ms: float
    proposal_duration_ms: float
    quote: dict[str, Any] | None
    status: str


def _money(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.01")), "f")


def _step(agent: str, status: str, summary: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"agent": agent, "status": status, "summary": summary, "details": details or {}}


@tool
def credit_risk_tool(client_id: str, notional: str) -> dict[str, Any]:
    """Check requested notional against the authoritative PostgreSQL client credit limit."""
    requested = Decimal(notional)
    capacity = get_credit_capacity(client_id)
    remaining = capacity["remaining_credit"]
    approved = Decimal("0") < requested <= remaining
    return {
        "approved": approved,
        "credit_limit": _money(capacity["credit_limit"]),
        "current_exposure": _money(capacity["current_exposure"]),
        "remaining_credit": _money(remaining),
        "requested_notional": _money(requested),
        "reason": "Within client credit capacity." if approved else "Requested notional exceeds remaining credit capacity.",
    }


@tool
def inventory_tool(issuer: str, maturity_year: int, notional: str) -> dict[str, Any]:
    """Check requested notional against the current PostgreSQL bond inventory snapshot."""
    requested = Decimal(notional)
    snapshot = get_bond_snapshot(issuer, maturity_year)
    total_capacity = snapshot["available_notional"] + snapshot["hedge_capacity"]
    approved = Decimal("0") < requested <= total_capacity
    return {
        "approved": approved,
        "isin": snapshot["isin"],
        "available_inventory": _money(snapshot["available_notional"]),
        "hedge_capacity": _money(snapshot["hedge_capacity"]),
        "total_capacity": _money(total_capacity),
        "snapshot_updated_at": snapshot["updated_at"].isoformat(),
        "requested_notional": _money(requested),
        "reason": "Inventory and hedge capacity are sufficient." if approved else "Requested notional exceeds inventory and hedge capacity.",
    }


@tool
def pricing_tool(
    issuer: str,
    maturity_year: int,
    side: Literal["BUY", "SELL"],
    notional: str,
    spread_adjustment_bps: int,
) -> dict[str, Any]:
    """Calculate an indicative quote from the market snapshot and bounded agent spread adjustment."""
    requested = Decimal(notional)
    if not 0 <= spread_adjustment_bps <= 5:
        raise ValueError("Pricing spread adjustment must be between 0 and 5 basis points")
    snapshot = get_bond_snapshot(issuer, maturity_year)
    base_spread_bps = Decimal("8") + (Decimal("3") if requested >= Decimal("50000000") else Decimal("0"))
    spread_bps = base_spread_bps + Decimal(spread_adjustment_bps)
    signed_spread = spread_bps / Decimal("100")
    mid_yield = snapshot["market_mid_yield"]
    quote_yield = mid_yield + signed_spread if side == "BUY" else mid_yield - signed_spread
    clean_price = Decimal("100") - (quote_yield - mid_yield) * Decimal("5")
    return {
        "isin": snapshot["isin"],
        "issuer": issuer,
        "maturity_year": maturity_year,
        "side": side,
        "notional": _money(requested),
        "quote_yield_pct": str(quote_yield.quantize(Decimal("0.001"))),
        "clean_price": str(clean_price.quantize(Decimal("0.001"))),
        "market_mid_yield_pct": str(mid_yield),
        "market_snapshot_updated_at": snapshot["updated_at"].isoformat(),
        "base_spread_bps": str(base_spread_bps),
        "spread_adjustment_bps": str(spread_adjustment_bps),
        "spread_bps": str(spread_bps),
        "indicative": True,
        "expires_in_seconds": 15,
    }


def intent_agent(state: RfqState) -> dict[str, Any]:
    token = state.get("hf_token")
    model = state.get("hf_model", DEFAULT_HF_MODEL)
    if not token:
        rfq, errors = None, ["HF_TOKEN is not configured; the Intent Agent cannot run."]
        provider = "Hugging Face not configured"
    else:
        rfq, errors = extract_intent_with_hf(state["raw_text"], hf_token=token, model=model)
        provider = f"Hugging Face · {model}"

    return {
        "rfq": rfq,
        "extraction_errors": errors,
        "intent_provider": provider,
        "steps": [
            _step(
                "Intent Agent",
                "PASS" if rfq else "NEEDS_REVIEW",
                "Structured RFQ extracted by the language model." if rfq else "The Intent Agent could not validate required fields.",
                {
                    "provider": provider,
                    "errors": errors,
                    "rfq": {
                        "issuer": rfq.issuer,
                        "maturity_year": rfq.maturity_year,
                        "side": rfq.side,
                        "notional": _money(rfq.notional),
                        "target_yield_pct": str(rfq.target_yield_pct) if rfq.target_yield_pct is not None else None,
                        "seniority": rfq.seniority,
                    } if rfq else {},
                },
            )
        ],
    }


def route_after_intent(state: RfqState) -> list[str]:
    if state.get("rfq") is None:
        return ["manual_review_agent"]
    return ["credit_risk_agent", "inventory_agent"]


def credit_risk_agent(state: RfqState) -> dict[str, Any]:
    rfq = state["rfq"]
    assert rfq is not None
    try:
        capacity = credit_risk_tool.invoke({"client_id": state["client_id"], "notional": str(rfq.notional)})
        context = retrieve_credit_context(state["client_id"], state["raw_text"], state["hf_token"] or "")
        if not context:
            raise LookupError("No client credit documents were retrieved")
        assessment = assess_credit_risk(
            hf_token=state["hf_token"] or "",
            model=state.get("hf_model", DEFAULT_HF_MODEL),
            client_id=state["client_id"],
            raw_text=state["raw_text"],
            credit_capacity=capacity,
            evidence=context,
        )
        decision = {
            **capacity,
            "risk_rating": assessment.risk_rating,
            "risk_flags": assessment.risk_flags,
            "model_rationale_advisory": assessment.rationale,
            "approved": capacity["approved"] and assessment.risk_rating in {"LOW", "MODERATE"},
        }
        decision["evidence_retrieved"] = bool(context)
        if decision["approved"]:
            decision["reason"] = (
                f"HF risk rating {assessment.risk_rating}; requested {_money(rfq.notional)} is within "
                f"{_money(Decimal(capacity['remaining_credit']))} remaining credit; retrieved {len(context)} evidence documents."
            )
        else:
            decision["reason"] = (
                f"HF risk rating {assessment.risk_rating} or deterministic credit capacity blocked the RFQ."
            )
    except Exception as exc:
        context = []
        assessment = None
        decision = {
            "approved": False,
            "reason": f"Credit limit or document retrieval unavailable ({type(exc).__name__}).",
        }
    return {
        "credit_context": context,
        "credit_assessment": assessment.model_dump() if assessment else {},
        "credit_decision": decision,
    }


def inventory_agent(state: RfqState) -> dict[str, Any]:
    rfq = state["rfq"]
    assert rfq is not None
    try:
        decision = inventory_tool.invoke(
            {"issuer": rfq.issuer, "maturity_year": rfq.maturity_year, "notional": str(rfq.notional)}
        )
        assessment = assess_inventory(
            hf_token=state["hf_token"] or "",
            model=state.get("hf_model", DEFAULT_HF_MODEL),
            raw_text=state["raw_text"],
            rfq={
                "issuer": rfq.issuer,
                "maturity_year": rfq.maturity_year,
                "side": rfq.side,
                "notional": str(rfq.notional),
            },
            inventory=decision,
        )
        hedge_required = max(Decimal("0"), rfq.notional - Decimal(decision["available_inventory"]))
        decision["liquidity_posture"] = assessment.liquidity_posture
        decision["hedge_required_notional"] = _money(hedge_required)
        decision["rationale"] = assessment.rationale
        decision["approved"] = decision["approved"] and assessment.liquidity_posture in {"ADEQUATE", "TIGHT"}
        decision["reason"] = assessment.rationale if decision["approved"] else "Inventory agent or deterministic capacity check blocked the RFQ."
        assessment_details = {
            **assessment.model_dump(),
            "model_rationale_advisory": assessment.rationale,
            "available_inventory": decision["available_inventory"],
            "hedge_capacity": decision["hedge_capacity"],
            "deterministic_hedge_required_notional": _money(hedge_required),
            "total_capacity": decision["total_capacity"],
        }
        assessment_details["rationale"] = (
            f"HF liquidity posture {assessment.liquidity_posture}; database snapshot has "
            f"{decision['available_inventory']} inventory and {decision['hedge_capacity']} hedge capacity; "
            f"deterministic hedge requirement is {_money(hedge_required)}."
        )
        decision["model_rationale_advisory"] = assessment.rationale
        decision["reason"] = assessment_details["rationale"]
    except Exception as exc:
        assessment = None
        assessment_details = {}
        decision = {"approved": False, "reason": f"Inventory lookup unavailable ({type(exc).__name__})."}
    return {"inventory_assessment": assessment_details, "inventory_decision": decision}


def pricing_agent(state: RfqState) -> dict[str, Any]:
    rfq = state["rfq"]
    assert rfq is not None
    credit = state["credit_decision"]
    inventory = state["inventory_decision"]
    steps = [
        *state["steps"],
        _step(
            "Credit Risk Agent",
            "PASS" if credit["approved"] else "REJECTED",
            credit["reason"],
            {**credit, "evidence": state.get("credit_context", []), "duration_ms": state.get("credit_duration_ms")},
        ),
        _step(
            "Inventory Agent",
            "PASS" if inventory["approved"] else "REJECTED",
            inventory["reason"],
            {**inventory, "duration_ms": state.get("inventory_duration_ms")},
        ),
    ]

    quote: dict[str, Any] | None = None
    assessment = None
    if credit["approved"] and inventory["approved"]:
        try:
            market = get_bond_snapshot(rfq.issuer, rfq.maturity_year)
            assessment = assess_pricing(
                hf_token=state["hf_token"] or "",
                model=state.get("hf_model", DEFAULT_HF_MODEL),
                rfq={
                    "issuer": rfq.issuer,
                    "maturity_year": rfq.maturity_year,
                    "side": rfq.side,
                    "notional": str(rfq.notional),
                    "target_yield_pct": str(rfq.target_yield_pct) if rfq.target_yield_pct is not None else None,
                },
                risk=state.get("credit_assessment", {}),
                inventory=state.get("inventory_assessment", {}),
                market=market,
            )
            quote = pricing_tool.invoke(
                {
                    "issuer": rfq.issuer,
                    "maturity_year": rfq.maturity_year,
                    "side": rfq.side,
                    "notional": str(rfq.notional),
                    "spread_adjustment_bps": assessment.spread_adjustment_bps,
                }
            )
            quote["model_rationale_advisory"] = assessment.rationale
            quote["pricing_rationale"] = (
                f"HF pricing agent recommended +{assessment.spread_adjustment_bps} bp. "
                f"Deterministic pricing used mid-yield {quote['market_mid_yield_pct']}%, "
                f"base spread {quote['base_spread_bps']} bp, final spread {quote['spread_bps']} bp, "
                f"yield {quote['quote_yield_pct']}%, and clean price {quote['clean_price']}."
            )
            steps.append(_step("Pricing Agent", "PASS", assessment.rationale, quote))
        except Exception as exc:
            steps.append(
                _step("Pricing Agent", "NEEDS_REVIEW", "Pricing agent could not produce a validated spread proposal.", {"error": type(exc).__name__})
            )
    else:
        steps.append(_step("Pricing Agent", "SKIPPED", "Pricing is blocked until risk and inventory pass."))
    return {"pricing_assessment": assessment.model_dump() if assessment else {}, "quote": quote, "steps": steps}


def manual_review_agent(state: RfqState) -> dict[str, Any]:
    steps = [
        *state["steps"],
        _step("Credit Risk Agent", "SKIPPED", "Waiting for a complete, validated RFQ."),
        _step("Inventory Agent", "SKIPPED", "Waiting for a complete, validated RFQ."),
        _step("Pricing Agent", "SKIPPED", "Waiting for validated risk and inventory."),
    ]
    return {"quote": None, "steps": steps}


def quote_proposal_agent(state: RfqState) -> dict[str, Any]:
    rfq = state.get("rfq")
    if rfq is None:
        status = "NEEDS_REVIEW"
        step_status = "SKIPPED"
        summary = "No quote proposed because the Intent Agent did not return a complete RFQ."
    else:
        credit = state.get("credit_decision", {})
        inventory = state.get("inventory_decision", {})
        proposed = bool(
            credit.get("approved")
            and inventory.get("approved")
            and state.get("quote")
        )
        status = "QUOTE_PROPOSED" if proposed else "REJECTED"
        step_status = "PROPOSED" if proposed else "BLOCKED"
        summary = "Agent checks propose an indicative quote for the Java finance gate." if proposed else "One or more agent checks failed."

    steps = [
        *state["steps"],
        _step(
            "Quote Proposal Agent",
            step_status,
            summary,
            {"client_id": state.get("client_id", "DEMO-001")},
        ),
    ]
    return {"status": status, "steps": steps, "quote": state.get("quote") if step_status == "PROPOSED" else None}


def _instrument(agent: str, duration_field: str, node):
    def run(state: RfqState) -> dict[str, Any]:
        started = time.perf_counter()
        try:
            output = node(state)
        finally:
            elapsed = time.perf_counter() - started
            AGENT_DURATION.labels(agent=agent).observe(elapsed)
        output[duration_field] = round(elapsed * 1000, 3)
        for step in output.get("steps", []):
            if step["agent"] == agent:
                step["details"]["duration_ms"] = output[duration_field]
        return output

    return run


def build_rfq_graph():
    workflow = StateGraph(RfqState)
    workflow.add_node("intent_agent", _instrument("Intent Agent", "intent_duration_ms", intent_agent))
    workflow.add_node("credit_risk_agent", _instrument("Credit Risk Agent", "credit_duration_ms", credit_risk_agent))
    workflow.add_node("inventory_agent", _instrument("Inventory Agent", "inventory_duration_ms", inventory_agent))
    workflow.add_node("pricing_agent", _instrument("Pricing Agent", "pricing_duration_ms", pricing_agent))
    workflow.add_node("manual_review_agent", _instrument("Manual Review Agent", "manual_review_duration_ms", manual_review_agent))
    workflow.add_node("quote_proposal_agent", _instrument("Quote Proposal Agent", "proposal_duration_ms", quote_proposal_agent))

    workflow.add_edge(START, "intent_agent")
    workflow.add_conditional_edges("intent_agent", route_after_intent)
    workflow.add_edge(["credit_risk_agent", "inventory_agent"], "pricing_agent")
    workflow.add_edge("pricing_agent", "quote_proposal_agent")
    workflow.add_edge("manual_review_agent", "quote_proposal_agent")
    workflow.add_edge("quote_proposal_agent", END)
    return workflow.compile()


rfq_graph = build_rfq_graph()


def process_rfq(
    raw_text: str,
    client_id: str = "DEMO-001",
    *,
    hf_token: str | None = None,
    hf_model: str = DEFAULT_HF_MODEL,
) -> dict[str, Any]:
    result = rfq_graph.invoke(
        {
            "raw_text": raw_text,
            "client_id": client_id,
            "hf_token": hf_token,
            "hf_model": hf_model,
        }
    )
    return {
        "client_id": client_id,
        "status": result["status"],
        "intent_provider": result["intent_provider"],
        "steps": result["steps"],
        "quote": result.get("quote"),
    }