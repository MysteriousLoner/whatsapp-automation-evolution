from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class ContractStore:
    def __init__(self, db_path: str) -> None:
        self._db_path = Path(db_path)
        self._lock = threading.Lock()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _ensure_schema(self) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS contracts (
                    token TEXT PRIMARY KEY,
                    jid TEXT NOT NULL,
                    mode TEXT,
                    status TEXT NOT NULL,
                    property_address TEXT,
                    property_location TEXT,
                    contract_url TEXT,
                    signed_by TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    signed_at TEXT
                )
                """
            )
            conn.commit()

    def upsert_pending_contract(
        self,
        *,
        token: str,
        jid: str,
        mode: str | None,
        property_address: str | None,
        property_location: str | None,
        contract_url: str,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO contracts (
                    token, jid, mode, status, property_address, property_location,
                    contract_url, signed_by, created_at, updated_at, signed_at
                ) VALUES (?, ?, ?, 'pending', ?, ?, ?, NULL, ?, ?, NULL)
                ON CONFLICT(token) DO UPDATE SET
                    jid=excluded.jid,
                    mode=excluded.mode,
                    status='pending',
                    property_address=excluded.property_address,
                    property_location=excluded.property_location,
                    contract_url=excluded.contract_url,
                    updated_at=excluded.updated_at
                """,
                (
                    token,
                    jid,
                    mode,
                    property_address,
                    property_location,
                    contract_url,
                    now,
                    now,
                ),
            )
            conn.commit()

    def mark_signed(self, token: str, signed_by: str, signed_at: str | None = None) -> None:
        effective_signed_at = signed_at or datetime.now(timezone.utc).isoformat()
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                UPDATE contracts
                SET status='signed', signed_by=?, signed_at=?, updated_at=?
                WHERE token=?
                """,
                (signed_by, effective_signed_at, effective_signed_at, token),
            )
            conn.commit()

    def mark_cancelled(self, token: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                UPDATE contracts
                SET status='cancelled', updated_at=?
                WHERE token=? AND status='pending'
                """,
                (now, token),
            )
            conn.commit()

    def list_contracts(self, limit: int = 200) -> list[dict[str, Any]]:
        safe_limit = max(1, min(limit, 1000))
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    token, jid, mode, status, property_address, property_location,
                    contract_url, signed_by, created_at, updated_at, signed_at
                FROM contracts
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (safe_limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_contract(self, token: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    token, jid, mode, status, property_address, property_location,
                    contract_url, signed_by, created_at, updated_at, signed_at
                FROM contracts
                WHERE token = ?
                """,
                (token,),
            ).fetchone()
        return dict(row) if row is not None else None
