# OTC RFQ Agent Workbench

An asynchronous fixed-income RFQ prototype with Spring Boot intake, Kafka events, PostgreSQL/pgvector state, and a Python LangGraph agent worker. It uses synthetic credit, inventory, market, and client-document data. Do not submit real client data or treat generated quotes as executable.

## Architecture

1. `core-api` accepts RFQs, applies an idempotency key, and commits the RFQ plus an outbox event in one PostgreSQL transaction.
2. Every `/api/**` route requires the dashboard/API key in `X-API-Key`. The dashboard reads `RFQ_API_KEY` server-side and does not expose it to the browser. Actuator health remains available for local service health checks.
3. The outbox publisher sends schema-versioned `rfq.received` events to Kafka. The Python worker validates version 1, uses manual offset commits and bounded exponential retries, and dead-letters invalid or exhausted messages without copying RFQ text into the dead-letter payload. The Java consumer validates status/result event envelopes, retries failures, and publishes exhausted records to `rfq.dead-letter`.
4. The LangGraph Intent Agent extracts a validated RFQ with the Hugging Face chat model. Credit Risk and Inventory agents run as parallel graph branches. Credit Risk retrieves synthetic client documents with Hugging Face embeddings and pgvector; deterministic LangChain tools read authoritative credit and inventory values from PostgreSQL.
5. The Pricing Agent calculates an indicative quote from the market snapshot. This is only a proposal.
6. Spring Boot independently rechecks the proposal using `BigDecimal`, locks the client credit and bond inventory rows, includes active credit and shared-inventory reservations, validates inventory/market freshness and quote arithmetic, then atomically persists the quote and 15-second reservations or blocks it. Concurrent RFQs for the same bond serialize on the inventory row, preventing both from consuming the same remaining capacity.
7. RFQ submission and each status/finance-gate transition are recorded in append-only `rfq_audit_events` in the same transaction as the corresponding state change. `GET /api/rfqs/{id}/history` exposes the status-only history; it does not duplicate raw RFQ text or agent details.

Kafka processing is at-least-once. Consumers are idempotent at the RFQ/result level, and RFQ statuses are monotonic so late or duplicate events cannot overwrite a terminal decision or re-run its finance gate. The PostgreSQL transactional outbox prevents accepted RFQs from being lost between database commit and Kafka publication.

The dashboard uses Streamlit fragments to poll the core API every three seconds while keeping the rest of the page interactive. Database updates made through the API or directly in PostgreSQL appear on the next poll; this is near-real-time polling, not a push/WebSocket feed. Bond inventory shows active quote reservations and remaining quoteable capacity.

## Run With Docker Compose

Docker Desktop must be running. Python dependencies and Java build tools are only needed for local tests; Compose builds the services.

The repository ignores `.env`. If you do not already have one, create it from the sample and set `POSTGRES_PASSWORD`, `RFQ_API_KEY` (at least 32 random characters), and a Hugging Face token with Inference Providers permission. Compose refuses to start without the two required secrets, and the API rejects short or known placeholder keys. Never commit or paste these secrets into source control or support logs. Generate secrets locally and do not reuse production credentials.

```powershell
Copy-Item .env.example .env
# Edit .env and replace both placeholders; set HF_TOKEN locally if using hosted inference.
docker compose up --build
```

If `.env` already exists, preserve it and add or update the required variables rather than overwriting it. The default chat model is `google/gemma-2-2b-it`; the embedding model is `BAAI/bge-small-en-v1.5`. Without `HF_TOKEN`, the Intent Agent fails closed to manual review; there is no regex parser fallback.

For a fresh local setup, use independently generated random values for `POSTGRES_PASSWORD` and `RFQ_API_KEY`. An existing PostgreSQL volume retains its database role password; rotate that role to the new `POSTGRES_PASSWORD` before restarting the stack if its password changes. Compose publishes service ports only on loopback. The shared API key is a local-demo boundary, not per-user identity or production-grade authorization.

Services:

- Dashboard: `http://localhost:8501`
- Spring Boot API: `http://localhost:8080/api/rfqs`
- Agent worker health: `http://localhost:8081/health`
- Agent Prometheus metrics: `http://localhost:8081/metrics`
- Spring Boot health/metrics: `http://localhost:8080/actuator/health` and `http://localhost:8080/actuator/prometheus`
- Prometheus: `http://localhost:9090`
- Kafka host listener: `localhost:29092`
- PostgreSQL: `localhost:5432`

Submit an RFQ from the dashboard, or call the API with `RFQ_API_KEY` supplied by your shell's secret store/environment:

```powershell
$body = @{ clientId = 'DEMO-001'; rawText = 'We want to buy $50M nominal of Apple 2030 senior unsecured notes, targeting 4.5% yield.' } | ConvertTo-Json
$headers = @{ 'X-API-Key' = $env:RFQ_API_KEY; 'Idempotency-Key' = [guid]::NewGuid().ToString() }
$rfq = Invoke-RestMethod -Method Post -Uri 'http://localhost:8080/api/rfqs' -ContentType 'application/json' -Headers $headers -Body $body
Invoke-RestMethod -Headers @{ 'X-API-Key' = $env:RFQ_API_KEY } -Uri "http://localhost:8080/api/rfqs/$($rfq.id)"
Invoke-RestMethod -Headers @{ 'X-API-Key' = $env:RFQ_API_KEY } -Uri "http://localhost:8080/api/rfqs/$($rfq.id)/history"
```

## Local Tests

Python 3.12 or newer:

```powershell
\.venv\Scripts\python.exe -m unittest discover -s tests -v
\.venv\Scripts\python.exe -m compileall -q app streamlit_app.py tests
```

Java 21 and Maven:

```powershell
mvn -f core-api/pom.xml test
```

The tests cover API-key enforcement, Kafka event schema validation, worker retry/dead-letter behavior, and audit-transition recording. The PostgreSQL API integration test uses `pgvector/pgvector:pg16` through Testcontainers and is skipped when a compatible Docker daemon is unavailable. The production Kafka retry policy retries twice after the initial delivery and sends exhausted records to `rfq.dead-letter`; the worker dead-letter payload points to the original Kafka offset and intentionally omits request text.

The database is seeded with four synthetic clients and five synthetic bond market/inventory snapshots (including the original Apple 2030 example), plus fictional client credit documents for RAG retrieval. The dashboard loads configured client IDs from the API. RFQ text and extracted PDF/email/text content are capped at 20,000 characters; document uploads remain capped at 10 MB. When a document explicitly states a checked quantity × par = face/notional equation, intent extraction uses that face amount instead of confusing bond count with dollar notional; malformed or conflicting equations require manual review.

| Client | Credit limit | Current exposure |
|---|---:|---:|
| `DEMO-001` | $100M | $25M |
| `DEMO-002` | $50M | $12.5M |
| `DEMO-003` | $150M | $85M |
| `DEMO-004` | $25M | $5M |

Synthetic bond snapshots are Apple Inc. 2030, Microsoft Corp. 2031, Acme Robotics Inc. 2029, Northstar Energy Holdings 2032, and Cedar Retail Group 2028. Example dashboard requests:

```text
Please quote a $10M buy of Microsoft 2031 senior unsecured notes.
We want to sell $8M of Acme Robotics 2029 bonds; please provide an indicative bid.
Quote $15M of Cedar Retail Group 2028 senior notes, targeting a 5.8% yield.
```

Demo credit limits, exposures, inventory, yields, and credit documents are for software demonstration only, not production risk controls. The finance gate is authoritative and rejects missing evidence, stale/missing market data, capacity breaches, mismatched quote fields, or invalid deterministic price arithmetic. The project has not been load-tested to any latency SLA.