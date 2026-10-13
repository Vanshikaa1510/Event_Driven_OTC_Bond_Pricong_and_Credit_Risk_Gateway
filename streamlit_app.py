import json
import os
import time
import uuid
from decimal import Decimal

import requests
import streamlit as st
from dotenv import load_dotenv


load_dotenv(override=False)
API_URL = os.getenv("RFQ_API_URL", "http://127.0.0.1:8080/api")
WORKER_URL = os.getenv("RFQ_WORKER_URL", "http://127.0.0.1:8081")
API_KEY = os.getenv("RFQ_API_KEY", "")
API_HEADERS = {"X-API-Key": API_KEY} if API_KEY else {}
AUTO_REFRESH_SECONDS = 3
SAMPLE_RFQ = (
    "We want to buy $50M nominal of Apple 2030 senior unsecured notes, "
    "targeting 4.5% yield. What can you do?"
)

st.set_page_config(page_title="OTC RFQ Workbench", page_icon="▤", layout="wide")
if not API_KEY:
    st.error("Core API access is not configured. Set RFQ_API_KEY for the dashboard service.")
    st.stop()

st.markdown(
    """
    <style>
    :root { color-scheme: light; }
    .stApp { background: #f3f6f9; }
    .block-container { max-width: 1480px; padding-top: 2.75rem; padding-bottom: 3rem; }
    h1, h2, h3 { color: #13283f; letter-spacing: -.025em; }
    h1 { font-weight: 690; }
    h2 { font-size: 1.35rem; }
    h3 { font-size: 1.05rem; }
    [data-testid="stSidebar"] { background: #edf2f6; border-right: 1px solid #dce4eb; }
    [data-testid="stSidebar"] h2, [data-testid="stSidebar"] h3 { color: #233d56; }
    [data-testid="stMetric"] {
        background: #fff; border: 1px solid #dce4eb; border-radius: 10px;
        padding: .8rem 1rem; box-shadow: 0 1px 2px rgba(16, 39, 61, .04);
    }
    [data-testid="stMetricLabel"] { color: #65788b; font-size: .82rem; }
    [data-testid="stMetricValue"] { color: #17324d; font-weight: 650; }
    [data-testid="stForm"] {
        background: #fff; border: 1px solid #dce4eb; border-radius: 12px;
        padding: 1.1rem 1.2rem .7rem;
    }
    [data-testid="stExpander"] { background: #fff; border: 1px solid #dce4eb; border-radius: 9px; }
    [data-testid="stDataFrame"] { border: 1px solid #dce4eb; border-radius: 9px; overflow: hidden; }
    [data-testid="stFileUploader"] { background: #f8fafc; border-radius: 8px; }
    .masthead {
        display: flex; align-items: center; justify-content: space-between;
        gap: 1rem; padding: .9rem 1.15rem; margin-bottom: 1.35rem;
        background: #122b43; border-radius: 12px; color: #fff;
        box-shadow: 0 4px 14px rgba(18, 43, 67, .12);
    }
    .brand-lockup { display: flex; align-items: center; gap: .8rem; }
    .brand-mark {
        display: grid; place-items: center; width: 2.35rem; height: 2.35rem;
        border: 1px solid rgba(255,255,255,.27); border-radius: 8px;
        color: #8ee0ce; font-size: 1.05rem; font-weight: 750;
    }
    .brand-name { font-size: .92rem; font-weight: 700; letter-spacing: .09em; }
    .brand-subtitle { color: #b8c7d5; font-size: .72rem; margin-top: .15rem; }
    .env-pill {
        padding: .35rem .65rem; border: 1px solid rgba(255,255,255,.2);
        border-radius: 999px; color: #c8d6e2; font-size: .7rem;
        font-weight: 650; letter-spacing: .08em; white-space: nowrap;
    }
    .section-kicker {
        color: #547187; font-size: .7rem; font-weight: 750;
        letter-spacing: .11em; text-transform: uppercase; margin-bottom: .2rem;
    }
    .section-note { color: #718295; font-size: .85rem; }
    .quote-banner {
        padding: .8rem 1rem; margin: .4rem 0 1rem; border-radius: 9px;
        background: #e8f5f1; border: 1px solid #cbe8de; color: #17634f;
        font-weight: 650;
    }
    .risk-banner {
        padding: .8rem 1rem; margin: .4rem 0 1rem; border-radius: 9px;
        background: #fff4e5; border: 1px solid #f3d9aa; color: #81550e;
        font-weight: 650;
    }
    .error-banner {
        padding: .8rem 1rem; margin: .4rem 0 1rem; border-radius: 9px;
        background: #fff0ef; border: 1px solid #f1ceca; color: #9d3f36;
        font-weight: 650;
    }
    .subtle { color: #64727e; }
    .quote-box { background: #eef7f4; border-left: 4px solid #167a72; padding: 1rem 1.2rem; border-radius: 4px; }
    .quote-value { font-size: 1.5rem; font-weight: 700; color: #172b3a; }
    .agent-row { border-bottom: 1px solid #e3e8eb; padding: .65rem 0; }
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    """
    <div class="masthead">
      <div class="brand-lockup">
        <div class="brand-mark">FI</div>
        <div>
          <div class="brand-name">FIXED INCOME · OTC</div>
          <div class="brand-subtitle">Institutional RFQ &amp; Risk Workbench</div>
        </div>
      </div>
      <div class="env-pill">SYNTHETIC DEMO ENVIRONMENT</div>
    </div>
    """,
    unsafe_allow_html=True,
)

title_col, context_col = st.columns([3, 1])
with title_col:
    st.title("RFQ Workbench")
    st.markdown(
        '<div class="section-note">Review incoming client interest, assess desk capacity, and generate a controlled indicative quote.</div>',
        unsafe_allow_html=True,
    )
with context_col:
    st.markdown("<br>", unsafe_allow_html=True)
    st.caption("DECISION SUPPORT ONLY · NO ORDER ROUTING")

client_options_error = None
try:
    clients_response = requests.get(f"{API_URL}/dashboard/clients", headers=API_HEADERS, timeout=3)
    clients_response.raise_for_status()
    client_options = clients_response.json()
    if not isinstance(client_options, list) or not client_options:
        raise ValueError("The core API returned no configured clients.")
except (requests.RequestException, ValueError) as exc:
    client_options = ["DEMO-001"]
    client_options_error = str(exc)

client_id = st.selectbox(
    "Client",
    options=client_options,
    index=client_options.index("DEMO-001") if "DEMO-001" in client_options else 0,
)

with st.form("rfq_form"):
    st.markdown('<div class="section-kicker">New request</div>', unsafe_allow_html=True)
    st.markdown("#### Capture client interest")
    st.caption("Enter a free-text RFQ or attach a client document. All quote proposals remain subject to the deterministic finance gate.")
    raw_text = st.text_area("Client request", value=SAMPLE_RFQ, height=130)
    uploaded_file = st.file_uploader(
        "Or attach a PDF, email, or text transcript",
        type=["pdf", "eml", "txt"],
        max_upload_size=10,
        help="Maximum file size is 10 MB. Extracted RFQ text is limited to 20,000 characters.",
    )
    submit_col, form_note_col = st.columns([1, 2])
    with submit_col:
        submitted = st.form_submit_button("Submit RFQ for review", type="primary", use_container_width=True)
    with form_note_col:
        st.caption("Asynchronous processing · indicative quote only · credit and market checks enforced")

if submitted:
    try:
        headers = {**API_HEADERS, "Idempotency-Key": str(uuid.uuid4())}
        if uploaded_file is not None:
            accepted = requests.post(
                f"{API_URL}/rfqs/documents",
                params={"clientId": client_id},
                files={"file": (uploaded_file.name, uploaded_file.getvalue(), uploaded_file.type)},
                headers=headers,
                timeout=20,
            )
        else:
            accepted = requests.post(
                f"{API_URL}/rfqs",
                json={"rawText": raw_text, "clientId": client_id},
                headers=headers,
                timeout=20,
            )
        accepted.raise_for_status()
        rfq_id = accepted.json()["id"]
        st.session_state["active_rfq_id"] = rfq_id
        with st.spinner(f"RFQ accepted · awaiting agent workflow · {rfq_id[:8]}"):
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline:
                current = requests.get(f"{API_URL}/rfqs/{rfq_id}", headers=API_HEADERS, timeout=5)
                current.raise_for_status()
                st.session_state["rfq_record"] = current.json()
                if current.json()["status"] in {"QUOTED", "REJECTED", "NEEDS_REVIEW", "FAILED"}:
                    break
                time.sleep(0.5)
        st.session_state.pop("rfq_error", None)
    except requests.RequestException as exc:
        st.session_state["rfq_error"] = f"Could not reach the agent service at {API_URL}: {exc}"
        st.session_state.pop("rfq_record", None)

if st.session_state.get("rfq_error"):
    st.error(f"RFQ submission error · {st.session_state['rfq_error']}")

record = st.session_state.get("rfq_record")
if record:
    result = record.get("result") or {}
    status = record["status"]
    st.markdown('<div class="section-kicker">Workflow result</div>', unsafe_allow_html=True)
    st.subheader(f"RFQ {record['id'][:8]} · {status.replace('_', ' ').title()}")
    if status == "QUOTED":
        st.markdown('<div class="quote-banner">Finance gate approved · indicative quote generated</div>', unsafe_allow_html=True)
    elif status == "NEEDS_REVIEW":
        st.markdown('<div class="risk-banner">Manual review required · the request could not be fully validated</div>', unsafe_allow_html=True)
    elif status in {"RECEIVED", "PROCESSING"}:
        st.info(f"Request {status.lower()} · workflow is running asynchronously · {record['id']}")
    elif status == "FAILED":
        st.markdown('<div class="error-banner">Agent worker failed after retries · inspect the dead-letter topic</div>', unsafe_allow_html=True)
    else:
        st.markdown('<div class="error-banner">Finance gate rejected · no quote generated</div>', unsafe_allow_html=True)

    quote = result.get("quote") if result else None
    if quote:
        st.markdown('<div class="section-kicker">Pricing proposal</div>', unsafe_allow_html=True)
        st.subheader("Indicative quote")
        notional_display = f"${format(Decimal(quote['notional']), ',.2f').rstrip('0').rstrip('.') }"
        quote_cols = st.columns(5)
        quote_cols[0].metric("Issuer", quote["issuer"])
        quote_cols[1].metric("Notional", notional_display)
        quote_cols[2].metric("Client yield", f"{quote['quote_yield_pct']}%")
        quote_cols[3].metric("Clean price", quote["clean_price"])
        quote_cols[4].metric("Expires", f"{quote['expires_in_seconds']} sec")
        st.caption(
            f"{quote['side']} · {quote['maturity_year']} · {quote['spread_bps']} bps over "
            f"demo mid-yield {quote['market_mid_yield_pct']}% · indicative only"
        )

    if result:
        st.markdown('<div class="section-kicker">Decision trace</div>', unsafe_allow_html=True)
        st.subheader("Agent & control checks")
        st.caption(f"Submitted {record['createdAt']} · complete trace and deterministic control rationale")
        for step in result.get("steps", []):
            label = f"{step['agent']}  ·  {step['status']}"
            with st.expander(label, expanded=step["status"] in {"REJECTED", "NEEDS_REVIEW"}):
                st.write(step["summary"])
                if step.get("details"):
                    st.code(json.dumps(step["details"], indent=2), language="json")

    try:
        history_response = requests.get(
            f"{API_URL}/rfqs/{record['id']}/history",
            headers=API_HEADERS,
            timeout=3,
        )
        history_response.raise_for_status()
        st.markdown('<div class="section-kicker">Audit trail</div>', unsafe_allow_html=True)
        st.dataframe(
            [
                {
                    "Time": event["occurredAt"],
                    "Event": event["eventType"],
                    "Previous status": event["previousStatus"] or "—",
                    "New status": event["newStatus"],
                }
                for event in history_response.json()
            ],
            use_container_width=True,
            hide_index=True,
        )
    except requests.RequestException as exc:
        st.warning(f"RFQ audit history is unavailable: {exc}")

with st.sidebar:
    st.markdown("### Desk monitor")
    st.caption("Operational health and live database-backed capacity")
    if client_options_error:
        st.warning("Could not load the configured client list. Showing the default client.")
        with st.expander("Client-list diagnostic"):
            st.code(client_options_error)
    try:
        core_health = requests.get(f"{API_URL.replace('/api', '')}/actuator/health", timeout=2)
        core_health.raise_for_status()
        st.success("Spring Boot core · healthy")
    except requests.RequestException:
        st.error("Spring Boot core · unavailable")
    try:
        worker_health = requests.get(f"{WORKER_URL}/health", timeout=2).json()
        if worker_health.get("status") == "ok":
            st.success("LangGraph worker · connected")
        else:
            st.warning("LangGraph worker · degraded")
    except requests.RequestException:
        st.warning("LangGraph worker · unavailable")

    @st.fragment(run_every=f"{AUTO_REFRESH_SECONDS}s")
    def live_balances(selected_client_id: str) -> None:
        try:
            summary_response = requests.get(
                f"{API_URL}/dashboard/summary",
                params={"clientId": selected_client_id},
                headers=API_HEADERS,
                timeout=5,
            )
            summary_response.raise_for_status()
            summary = summary_response.json()

            def money(value: str) -> str:
                amount = Decimal(str(value))
                return f"${format(amount, ',.2f').rstrip('0').rstrip('.')}"

            st.caption(
                f"Database balances · as of {summary['asOf']} · "
                f"auto-refreshes every {AUTO_REFRESH_SECONDS} seconds"
            )
            st.metric("Client credit limit", money(summary["creditLimit"]))
            st.metric("Current exposure", money(summary["currentExposure"]))
            st.metric("Active quote reservations", money(summary["activeReservations"]))
            st.metric("Available credit", money(summary["availableCredit"]))
            if summary["inventory"]:
                st.markdown("**Bond inventory & market**")
                st.dataframe(
                    [
                        {
                            "Bond": f"{bond['issuer']} {bond['maturityYear']}",
                            "Available": money(bond["availableNotional"]),
                            "Hedge capacity": money(bond["hedgeCapacity"]),
                            "Active quote reservations": money(bond["activeReservations"]),
                            "Remaining capacity": money(bond["remainingCapacity"]),
                            "Mid-yield": f"{bond['marketMidYield']}%",
                            "Market data": "Fresh" if bond["fresh"] else "STALE",
                        }
                        for bond in summary["inventory"]
                    ],
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                st.info("No bond inventory or market snapshots are configured.")
            st.caption("Reservations expire after 15 seconds. No orders are executed and settled exposure is not updated.")
        except requests.RequestException as exc:
            st.error("Live balances are unavailable. Check the core API connection.")
            with st.expander("Balance-service diagnostic"):
                st.code(str(exc))

    live_balances(client_id.strip() or "DEMO-001")
    st.divider()
    st.caption("No order is routed or executed. All generated quotes are illustrative.")


@st.fragment(run_every=f"{AUTO_REFRESH_SECONDS}s")
def recent_rfqs() -> None:
    try:
        recent = requests.get(f"{API_URL}/rfqs?limit=10", headers=API_HEADERS, timeout=3)
        recent.raise_for_status()
        rows = recent.json()
        st.markdown('<div class="section-kicker">Blotter</div>', unsafe_allow_html=True)
        st.subheader("Recent RFQs")
        st.caption(f"Latest 10 requests · refreshes every {AUTO_REFRESH_SECONDS} seconds")
        if rows:
            st.dataframe(
                [{"RFQ": row["id"], "Client": row["clientId"], "Status": row["status"], "Created": row["createdAt"]} for row in rows],
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info("No RFQs have been submitted yet.")
    except requests.RequestException as exc:
        st.error("Recent RFQs are unavailable. Check the core API connection.")
        with st.expander("RFQ blotter diagnostic"):
            st.code(str(exc))


recent_rfqs()