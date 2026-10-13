from __future__ import annotations

import os
from decimal import Decimal
from typing import Any

import psycopg


def _database_url() -> str:
    url = os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not configured")
    return url


def get_credit_capacity(client_id: str) -> dict[str, Any]:
    with psycopg.connect(_database_url()) as connection:
        row = connection.execute(
            "SELECT credit_limit, current_exposure FROM client_credit_limits WHERE client_id = %s",
            (client_id,),
        ).fetchone()
    if row is None:
        raise LookupError(f"No credit profile exists for client {client_id}")
    credit_limit, current_exposure = (Decimal(value) for value in row)
    return {
        "credit_limit": credit_limit,
        "current_exposure": current_exposure,
        "remaining_credit": max(Decimal("0"), credit_limit - current_exposure),
    }


def get_bond_snapshot(issuer: str, maturity_year: int) -> dict[str, Any]:
    with psycopg.connect(_database_url()) as connection:
        row = connection.execute(
            """
            SELECT isin, issuer, maturity_year, available_notional, hedge_capacity,
                   market_mid_yield, updated_at
            FROM bond_inventory
            WHERE issuer ILIKE %s AND maturity_year = %s
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            (f"%{issuer}%", maturity_year),
        ).fetchone()
    if row is None:
        raise LookupError(f"No inventory or market snapshot for {issuer} {maturity_year}")
    return {
        "isin": row[0],
        "issuer": row[1],
        "maturity_year": row[2],
        "available_notional": Decimal(row[3]),
        "hedge_capacity": Decimal(row[4]),
        "market_mid_yield": Decimal(row[5]),
        "updated_at": row[6],
    }