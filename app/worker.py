from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from aiokafka.structs import TopicPartition
from prometheus_client import Counter

from app.agent_engine import DEFAULT_HF_MODEL
from app.rfq_graph import process_rfq


logger = logging.getLogger(__name__)
MESSAGES = Counter("rfq_agent_messages_total", "RFQ messages handled by the agent worker", ["outcome"])
try:
    MAX_ATTEMPTS = int(os.getenv("RFQ_MAX_ATTEMPTS", "3"))
except ValueError as exc:
    raise RuntimeError("RFQ_MAX_ATTEMPTS must be a positive integer.") from exc
if MAX_ATTEMPTS < 1:
    raise RuntimeError("RFQ_MAX_ATTEMPTS must be a positive integer.")
SCHEMA_VERSION = 1


def _json_bytes(value: dict[str, Any]) -> bytes:
    return json.dumps(value, separators=(",", ":"), default=str).encode("utf-8")


def _validate_received_event(raw_value: bytes) -> dict[str, Any]:
    if not isinstance(raw_value, (bytes, bytearray, str)):
        raise ValueError("Kafka event value must be JSON text.")
    event = json.loads(raw_value)
    if not isinstance(event, dict):
        raise ValueError("Kafka event must be a JSON object.")
    version = event.get("schema_version")
    if not isinstance(version, int) or isinstance(version, bool) or version != SCHEMA_VERSION:
        raise ValueError("Unsupported or missing Kafka event schema_version.")
    if not isinstance(event.get("event_id"), str) or not isinstance(event.get("rfq_id"), str):
        raise ValueError("Kafka event must contain valid event_id and rfq_id UUIDs.")
    try:
        UUID(event["event_id"])
        UUID(event["rfq_id"])
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValueError("Kafka event must contain valid event_id and rfq_id UUIDs.") from exc
    if not isinstance(event.get("client_id"), str) or not event["client_id"].strip() or len(event["client_id"]) > 64:
        raise ValueError("Kafka event client_id is missing or invalid.")
    if not isinstance(event.get("raw_text"), str) or not event["raw_text"].strip() or len(event["raw_text"]) > 20_000:
        raise ValueError("Kafka event raw_text is missing or invalid.")
    created_at = event.get("created_at")
    if not isinstance(created_at, str):
        raise ValueError("Kafka event created_at must be an ISO-8601 timestamp.")
    try:
        timestamp = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Kafka event created_at must be an ISO-8601 timestamp.") from exc
    if timestamp.tzinfo is None:
        raise ValueError("Kafka event created_at must include a timezone.")
    return event


def _dead_letter_event(message: Any, error_type: str, rfq_id: str | None = None) -> dict[str, Any]:
    event: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "error_type": error_type,
        "failed_at": datetime.now(timezone.utc).isoformat(),
        "source": {
            "topic": getattr(message, "topic", None),
            "partition": getattr(message, "partition", None),
            "offset": getattr(message, "offset", None),
        },
    }
    if rfq_id:
        event["rfq_id"] = rfq_id
    return event


async def _handle_message(
    message: Any,
    producer: AIOKafkaProducer,
    hf_token: str | None,
    hf_model: str,
) -> None:
    try:
        event = _validate_received_event(message.value)
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
        await producer.send_and_wait(
            "rfq.dead-letter",
            _json_bytes(_dead_letter_event(message, type(exc).__name__)),
            key=getattr(message, "key", None),
        )
        MESSAGES.labels(outcome="invalid_dead_letter").inc()
        return

    rfq_id = event["rfq_id"]
    key = rfq_id.encode("utf-8")
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            await producer.send_and_wait(
                "rfq.status",
                _json_bytes({"schema_version": 1, "rfq_id": rfq_id, "status": "PROCESSING"}),
                key=key,
            )
            result = await asyncio.to_thread(
                process_rfq,
                event["raw_text"],
                event["client_id"],
                hf_token=hf_token,
                hf_model=hf_model,
            )
            if (
                not isinstance(result, dict)
                or result.get("status") not in {"QUOTE_PROPOSED", "REJECTED", "NEEDS_REVIEW"}
                or not isinstance(result.get("steps"), list)
            ):
                raise ValueError("Agent result does not match schema version 1.")
            await producer.send_and_wait(
                "rfq.processed",
                _json_bytes(
                    {
                        "schema_version": 1,
                        "rfq_id": rfq_id,
                        "client_id": event["client_id"],
                        "result": result,
                        "processed_at": datetime.now(timezone.utc).isoformat(),
                    }
                ),
                key=key,
            )
            MESSAGES.labels(outcome=result["status"].lower()).inc()
            return
        except Exception as exc:
            logger.warning(
                "RFQ %s agent attempt %s/%s failed with %s",
                rfq_id,
                attempt,
                MAX_ATTEMPTS,
                type(exc).__name__,
            )
            if attempt < MAX_ATTEMPTS:
                await asyncio.sleep(min(2**attempt, 10))
                continue
            await producer.send_and_wait(
                "rfq.dead-letter",
                _json_bytes(_dead_letter_event(message, type(exc).__name__, rfq_id)),
                key=key,
            )
            await producer.send_and_wait(
                "rfq.status",
                _json_bytes({"schema_version": 1, "rfq_id": rfq_id, "status": "FAILED"}),
                key=key,
            )
            MESSAGES.labels(outcome="dead_letter").inc()


async def consume_rfqs() -> None:
    bootstrap_servers = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
    consumer = AIOKafkaConsumer(
        "rfq.received",
        bootstrap_servers=bootstrap_servers,
        group_id=os.getenv("KAFKA_GROUP_ID", "rfq-agent-workers"),
        enable_auto_commit=False,
        auto_offset_reset="earliest",
        max_poll_interval_ms=600000,
    )
    producer = AIOKafkaProducer(bootstrap_servers=bootstrap_servers, acks="all", enable_idempotence=True)
    consumer_started = False
    producer_started = False
    try:
        await consumer.start()
        consumer_started = True
        await producer.start()
        producer_started = True
        logger.info("RFQ agent worker connected to Kafka at %s", bootstrap_servers)
        async for message in consumer:
            try:
                await _handle_message(
                    message,
                    producer,
                    os.getenv("HF_TOKEN"),
                    os.getenv("HF_MODEL", DEFAULT_HF_MODEL),
                )
                await consumer.commit()
            except Exception:
                logger.exception("Failed to publish RFQ worker output; source offset will not be committed")
                consumer.seek(TopicPartition(message.topic, message.partition), message.offset)
                await asyncio.sleep(1)
    finally:
        if producer_started:
            await producer.stop()
        if consumer_started:
            await consumer.stop()