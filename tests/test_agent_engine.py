import json
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, call, patch
from uuid import UUID

from app.agent_engine import ExtractedRfq, extract_intent_with_hf
from app.hf_inference import chat_completion_json
from app.rfq_graph import process_rfq
from app.specialist_agents import CreditRiskAssessment, InventoryAssessment, PricingAssessment
from app.worker import _handle_message


class AgentEngineTests(unittest.TestCase):
    @patch("app.agent_engine.chat_completion_json")
    def test_langchain_intent_agent_extracts_structured_output(self, chat_model: object) -> None:
        payload = {
            "issuer": "Apple",
            "maturity_year": 2030,
            "side": "BUY",
            "notional_text": "$50M",
            "target_yield_pct": "4.5",
            "seniority": "senior unsecured",
        }
        chat_model.return_value = payload

        rfq, errors = extract_intent_with_hf("We want to buy $50M Apple 2030", hf_token="test-token")

        self.assertEqual(errors, [])
        self.assertEqual(rfq, ExtractedRfq("Apple", 2030, "BUY", Decimal("50000000"), Decimal("4.5"), "senior unsecured"))
        chat_model.assert_called_once()

    @patch("app.agent_engine.chat_completion_json")
    def test_explicit_face_notional_overrides_unit_quantity(self, chat_model: object) -> None:
        chat_model.return_value = {
            "issuer": "Apple",
            "maturity_year": 2030,
            "side": "BUY",
            "notional_text": "10,000 units",
            "target_yield_pct": "4.5",
            "seniority": "senior unsecured",
        }

        rfq, errors = extract_intent_with_hf(
            "Buy 10,000 units of Apple 2030. Quantity 10,000 bonds x USD 1,000 par = USD 10,000,000 face. "
            "The bond issue has aggregate principal USD 3,000,000,000.",
            hf_token="test-token",
        )

        self.assertEqual(errors, [])
        self.assertIsNotNone(rfq)
        self.assertEqual(rfq.notional, Decimal("10000000"))

    @patch("app.agent_engine.chat_completion_json")
    def test_conflicting_explicit_face_amounts_route_to_review(self, chat_model: object) -> None:
        chat_model.return_value = {
            "issuer": "Apple",
            "maturity_year": 2030,
            "side": "BUY",
            "notional_text": "$10M",
            "target_yield_pct": None,
            "seniority": "senior unsecured",
        }

        rfq, errors = extract_intent_with_hf(
            "Buy Apple 2030 notes: 10,000 bonds x USD 1,000 par = USD 10,000,000 face; "
            "alternate instruction says 12,000 bonds x USD 1,000 par = USD 12,000,000 face.",
            hf_token="test-token",
        )

        self.assertIsNone(rfq)
        self.assertIn("The document contains conflicting explicit face or notional amounts.", errors)

    @patch("app.rfq_graph.get_bond_snapshot")
    @patch("app.rfq_graph.get_credit_capacity")
    @patch("app.rfq_graph.retrieve_credit_context", return_value=[{"source": "demo.txt", "content": "Demo client."}])
    @patch("app.rfq_graph.assess_credit_risk")
    @patch("app.rfq_graph.assess_inventory")
    @patch("app.rfq_graph.assess_pricing")
    @patch("app.rfq_graph.extract_intent_with_hf")
    def test_graph_proposes_rfq_after_specialist_agents_pass(
        self,
        extract_agent: object,
        pricing_agent: object,
        inventory_agent: object,
        credit_agent: object,
        _credit_context: object,
        credit_lookup: object,
        bond_lookup: object,
    ) -> None:
        extract_agent.return_value = (
            ExtractedRfq("Apple", 2030, "BUY", Decimal("50000000"), Decimal("4.5"), "senior unsecured"),
            [],
        )
        credit_lookup.return_value = {
            "credit_limit": Decimal("100000000"),
            "current_exposure": Decimal("25000000"),
            "remaining_credit": Decimal("75000000"),
        }
        bond_lookup.return_value = {
            "isin": "US037833EF47",
            "issuer": "Apple Inc.",
            "maturity_year": 2030,
            "available_notional": Decimal("20000000"),
            "hedge_capacity": Decimal("40000000"),
            "market_mid_yield": Decimal("4.35"),
            "updated_at": datetime.now(timezone.utc),
        }
        credit_agent.return_value = CreditRiskAssessment(risk_rating="LOW", rationale="Synthetic evidence supports low risk.")
        inventory_agent.return_value = InventoryAssessment(
            liquidity_posture="ADEQUATE", hedge_required_notional="30000000", rationale="Capacity is sufficient."
        )
        pricing_agent.return_value = PricingAssessment(spread_adjustment_bps=2, rationale="Small liquidity premium.")
        result = process_rfq(
            "We want to buy $50M nominal of Apple 2030 senior unsecured notes.",
            hf_token="test-token",
        )
        self.assertEqual(result["status"], "QUOTE_PROPOSED", result)
        self.assertIsNotNone(result["quote"])
        self.assertEqual(result["steps"][-1]["status"], "PROPOSED")
        self.assertEqual(
            [step["agent"] for step in result["steps"]],
            ["Intent Agent", "Credit Risk Agent", "Inventory Agent", "Pricing Agent", "Quote Proposal Agent"],
        )

    @patch("app.rfq_graph.get_bond_snapshot")
    @patch("app.rfq_graph.get_credit_capacity")
    @patch("app.rfq_graph.retrieve_credit_context", return_value=[{"source": "demo.txt", "content": "Demo client."}])
    @patch("app.rfq_graph.assess_credit_risk")
    @patch("app.rfq_graph.assess_inventory")
    @patch("app.rfq_graph.extract_intent_with_hf")
    def test_graph_rejects_rfq_over_remaining_credit(
        self,
        extract_agent: object,
        inventory_agent: object,
        credit_agent: object,
        _credit_context: object,
        credit_lookup: object,
        bond_lookup: object,
    ) -> None:
        extract_agent.return_value = (
            ExtractedRfq("Apple", 2030, "BUY", Decimal("80000000"), None, "senior unsecured"),
            [],
        )
        credit_lookup.return_value = {
            "credit_limit": Decimal("100000000"),
            "current_exposure": Decimal("25000000"),
            "remaining_credit": Decimal("75000000"),
        }
        bond_lookup.return_value = {
            "isin": "US037833EF47",
            "issuer": "Apple Inc.",
            "maturity_year": 2030,
            "available_notional": Decimal("20000000"),
            "hedge_capacity": Decimal("40000000"),
            "market_mid_yield": Decimal("4.35"),
            "updated_at": datetime.now(timezone.utc),
        }
        credit_agent.return_value = CreditRiskAssessment(risk_rating="LOW", rationale="Capacity check still applies.")
        inventory_agent.return_value = InventoryAssessment(
            liquidity_posture="INSUFFICIENT", hedge_required_notional="60000000", rationale="Insufficient capacity."
        )
        result = process_rfq("We want to buy $80M nominal of Apple 2030 senior unsecured notes.", hf_token="test-token")
        self.assertEqual(result["status"], "REJECTED")
        self.assertIsNone(result["quote"])
        self.assertEqual(result["steps"][1]["status"], "REJECTED")
        self.assertEqual(result["steps"][2]["status"], "REJECTED")
        self.assertEqual(result["steps"][3]["status"], "SKIPPED")
        self.assertEqual(result["steps"][-1]["status"], "BLOCKED")

    @patch("app.rfq_graph.extract_intent_with_hf", return_value=(None, ["Issuer is unclear."]))
    def test_incomplete_intent_routes_to_manual_review(self, _extract_agent: object) -> None:
        result = process_rfq("Please quote $50M of Apple bonds.", hf_token="test-token")
        self.assertEqual(result["status"], "NEEDS_REVIEW")
        self.assertIsNone(result["quote"])
        self.assertEqual(result["steps"][1]["status"], "SKIPPED")
        self.assertEqual(result["steps"][-1]["status"], "SKIPPED")

    def test_missing_token_fails_closed_without_parser_fallback(self) -> None:
        result = process_rfq(
            "We want to buy $50M nominal of Apple 2030 senior unsecured notes."
        )
        self.assertEqual(result["status"], "NEEDS_REVIEW")
        self.assertEqual(result["intent_provider"], "Hugging Face not configured")
        self.assertIsNone(result["quote"])

    @patch("app.specialist_agents.chat_completion_json")
    def test_credit_risk_agent_returns_model_structured_assessment(self, chat_model: object) -> None:
        payload = {
            "risk_rating": "MODERATE",
            "risk_flags": ["maturity concentration"],
            "rationale": "Evidence indicates moderate risk.",
        }
        chat_model.return_value = payload

        from app.specialist_agents import assess_credit_risk

        assessment = assess_credit_risk(
            hf_token="test-token",
            model="test-model",
            client_id="DEMO-001",
            raw_text="Buy $50M Apple 2030",
            credit_capacity={"remaining_credit": "75000000"},
            evidence=[{"source": "memo.txt", "content": "Synthetic credit note"}],
        )

        self.assertEqual(assessment.risk_rating, "MODERATE")
        self.assertEqual(assessment.risk_flags, ["maturity concentration"])
        chat_model.assert_called_once()


class HuggingFaceInferenceClientTests(unittest.TestCase):
    @patch("app.hf_inference.InferenceClient")
    def test_explicit_provider_suffix_selects_native_provider(self, client_type: object) -> None:
        client_type.return_value.chat_completion.return_value.choices = [
            SimpleNamespace(message=SimpleNamespace(content='{"ok": true}'))
        ]

        result = chat_completion_json(
            hf_token="test-token",
            model="openai/gpt-oss-20b:nscale",
            system_prompt="Return JSON.",
            user_prompt="Test",
        )

        self.assertEqual(result, {"ok": True})
        client_type.assert_called_once_with(
            model="openai/gpt-oss-20b",
            provider="nscale",
            token="test-token",
            timeout=20,
        )
        client_type.return_value.chat_completion.assert_called_once_with(
            messages=[
                {"role": "system", "content": "Return JSON."},
                {"role": "user", "content": "Test"},
            ],
            temperature=0,
            response_format={"type": "json_object"},
        )

    @patch("app.hf_inference.InferenceClient")
    def test_model_without_provider_suffix_uses_auto_routing(self, client_type: object) -> None:
        client_type.return_value.chat_completion.return_value.choices = [
            SimpleNamespace(message=SimpleNamespace(content='{"ok": true}'))
        ]

        chat_completion_json(
            hf_token="test-token",
            model="openai/gpt-oss-20b",
            system_prompt="Return JSON.",
            user_prompt="Test",
        )

        client_type.assert_called_once_with(
            model="openai/gpt-oss-20b",
            provider="auto",
            token="test-token",
            timeout=20,
        )


class FakeProducer:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict, bytes]] = []

    async def send_and_wait(self, topic: str, value: bytes, key: bytes) -> None:
        self.events.append((topic, json.loads(value), key))


class WorkerTests(unittest.IsolatedAsyncioTestCase):
    def worker_event(self, rfq_id: str) -> dict[str, object]:
        return {
            "schema_version": 1,
            "event_id": str(UUID("1d8d87e5-e5ca-4b59-98f0-85dca4d235dd")),
            "rfq_id": rfq_id,
            "client_id": "DEMO-001",
            "raw_text": "sample",
            "created_at": "2026-10-10T06:00:00Z",
        }

    @patch("app.worker.asyncio.to_thread", new_callable=AsyncMock)
    async def test_worker_publishes_status_then_agent_result(self, process_graph: AsyncMock) -> None:
        process_graph.return_value = {"status": "QUOTE_PROPOSED", "steps": [], "quote": {}}
        producer = FakeProducer()
        message = SimpleNamespace(
            value=json.dumps(self.worker_event("461fa8b3-0c8f-4f1e-86bf-e043047a2eab")).encode(),
            topic="rfq.received",
            partition=0,
            offset=4,
            key=b"461fa8b3-0c8f-4f1e-86bf-e043047a2eab",
        )

        await _handle_message(message, producer, "test-token", "test-model")

        self.assertEqual([event[0] for event in producer.events], ["rfq.status", "rfq.processed"])
        self.assertEqual(producer.events[0][1]["status"], "PROCESSING")
        self.assertEqual(producer.events[1][1]["result"]["status"], "QUOTE_PROPOSED")

    @patch("app.worker.MAX_ATTEMPTS", 1)
    @patch("app.worker.asyncio.to_thread", new_callable=AsyncMock, side_effect=RuntimeError("provider unavailable"))
    async def test_worker_sends_retry_exhausted_message_to_dead_letter(self, _process_graph: AsyncMock) -> None:
        producer = FakeProducer()
        rfq_id = "62b6089a-4e94-4bd4-80e2-6dcb589a3aef"
        message = SimpleNamespace(
            value=json.dumps(self.worker_event(rfq_id)).encode(),
            topic="rfq.received",
            partition=1,
            offset=9,
            key=rfq_id.encode(),
        )

        await _handle_message(message, producer, "test-token", "test-model")

        self.assertEqual([event[0] for event in producer.events], ["rfq.status", "rfq.dead-letter", "rfq.status"])
        self.assertEqual(producer.events[-1][1]["status"], "FAILED")
        self.assertEqual(producer.events[1][1]["source"]["offset"], 9)
        self.assertNotIn("raw_text", producer.events[1][1])

    @patch("app.worker.asyncio.to_thread", new_callable=AsyncMock)
    async def test_worker_dead_letters_invalid_schema_without_processing(self, process_graph: AsyncMock) -> None:
        producer = FakeProducer()
        message = SimpleNamespace(
            value=json.dumps({"schema_version": 99, "raw_text": "sensitive request text"}).encode(),
            topic="rfq.received",
            partition=0,
            offset=12,
            key=None,
        )

        await _handle_message(message, producer, "test-token", "test-model")

        self.assertEqual([event[0] for event in producer.events], ["rfq.dead-letter"])
        self.assertEqual(producer.events[0][1]["error_type"], "ValueError")
        self.assertNotIn("raw_text", producer.events[0][1])
        process_graph.assert_not_awaited()

    @patch("app.worker.MAX_ATTEMPTS", 3)
    @patch("app.worker.asyncio.sleep", new_callable=AsyncMock)
    @patch(
        "app.worker.asyncio.to_thread",
        new_callable=AsyncMock,
        side_effect=RuntimeError("provider unavailable"),
    )
    async def test_worker_retries_with_bounded_exponential_backoff(
        self, process_graph: AsyncMock, sleep: AsyncMock
    ) -> None:
        producer = FakeProducer()
        rfq_id = "cd325650-3d2c-4634-8d00-26154bd4c68c"
        message = SimpleNamespace(
            value=json.dumps(self.worker_event(rfq_id)).encode(),
            topic="rfq.received",
            partition=2,
            offset=21,
            key=rfq_id.encode(),
        )

        await _handle_message(message, producer, "test-token", "test-model")

        self.assertEqual(process_graph.await_count, 3)
        self.assertEqual(sleep.await_args_list, [call(2), call(4)])
        self.assertEqual([event[0] for event in producer.events].count("rfq.dead-letter"), 1)


if __name__ == "__main__":
    unittest.main()