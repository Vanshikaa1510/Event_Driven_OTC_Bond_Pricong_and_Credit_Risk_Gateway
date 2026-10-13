from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.worker import consume_rfqs


load_dotenv()
logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    worker_task = asyncio.create_task(consume_rfqs(), name="rfq-kafka-consumer")
    try:
        yield
    finally:
        worker_task.cancel()
        try:
            await worker_task
        except asyncio.CancelledError:
            pass


app = FastAPI(title="OTC RFQ LangGraph Worker", version="0.1.0", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str | bool]:
    task = next((task for task in asyncio.all_tasks() if task.get_name() == "rfq-kafka-consumer"), None)
    return {"status": "ok" if task is not None and not task.done() else "degraded", "consumer_running": task is not None and not task.done()}


@app.get("/metrics")
async def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)