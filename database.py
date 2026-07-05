"""Lightweight SQLite persistence for the re-architected CPR bot.

Used for observability and durability only. It does not alter signal generation
or trade decision logic.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

from config_loader import DATA_DIR

DB_PATH = Path(DATA_DIR) / "cpr_gold.db"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Database:
    def __init__(self, db_path: Path | None = None):
        self.db_path = Path(db_path or DB_PATH)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS bot_state (
                    state_key TEXT PRIMARY KEY,
                    state_value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS cycle_runs (
                    run_id TEXT PRIMARY KEY,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    status TEXT NOT NULL,
                    summary_json TEXT,
                    error_text TEXT
                );

                CREATE TABLE IF NOT EXISTS signals_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT,
                    logged_at TEXT NOT NULL,
                    pair TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    side TEXT,
                    score REAL,
                    payload_json TEXT
                );

                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT,
                    created_at TEXT NOT NULL,
                    pair TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    side TEXT,
                    score REAL,
                    status TEXT NOT NULL,
                    payload_json TEXT,
                    broker_trade_id TEXT,
                    note TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_signals_logged_at ON signals_log(logged_at);
                CREATE INDEX IF NOT EXISTS idx_signals_pair_timeframe ON signals_log(pair, timeframe);
                CREATE INDEX IF NOT EXISTS idx_trades_created_at ON trades(created_at);
                CREATE INDEX IF NOT EXISTS idx_trades_pair_status ON trades(pair, status);
                CREATE INDEX IF NOT EXISTS idx_cycles_started_at ON cycle_runs(started_at);
                """
            )

    @contextmanager
    def cycle(self) -> Iterator[str]:
        run_id = uuid.uuid4().hex[:12]
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO cycle_runs (run_id, started_at, status) VALUES (?, ?, ?)",
                (run_id, utc_now_iso(), "RUNNING"),
            )
        try:
            yield run_id
        except Exception as exc:
            self.finish_cycle(run_id, status="FAILED", error_text=str(exc))
            raise

    def finish_cycle(self, run_id: str, status: str, summary: dict | None = None, error_text: str | None = None) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE cycle_runs
                SET finished_at = ?, status = ?, summary_json = ?, error_text = ?
                WHERE run_id = ?
                """,
                (utc_now_iso(), status, json.dumps(summary or {}), error_text, run_id),
            )

    def upsert_state(self, key: str, value: Any) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO bot_state (state_key, state_value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(state_key) DO UPDATE SET
                    state_value=excluded.state_value,
                    updated_at=excluded.updated_at
                """,
                (key, json.dumps(value), utc_now_iso()),
            )

    def get_state(self, key: str, default: Any = None) -> Any:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT state_value FROM bot_state WHERE state_key = ?",
                (key,),
            ).fetchone()
        if not row:
            return default
        try:
            return json.loads(row["state_value"])
        except Exception:
            return default

    def record_signal(self, signal: dict, timeframe: str = "H1", run_id: str | None = None) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO signals_log (run_id, logged_at, pair, timeframe, side, score, payload_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    utc_now_iso(),
                    signal.get("pair", ""),
                    signal.get("timeframe", timeframe),
                    signal.get("side"),
                    signal.get("score"),
                    json.dumps(signal),
                ),
            )

    def record_trade_attempt(self, signal: dict, ok: bool, note: str = "", broker_trade_id: str | None = None, run_id: str | None = None) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO trades (run_id, created_at, pair, timeframe, side, score, status, payload_json, broker_trade_id, note)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    utc_now_iso(),
                    signal.get("pair", ""),
                    signal.get("timeframe", "H1"),
                    signal.get("side"),
                    signal.get("score"),
                    "PLACED" if ok else "FAILED",
                    json.dumps(signal),
                    broker_trade_id,
                    note,
                ),
            )

    def latest_cycles(self, limit: int = 20) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM cycle_runs ORDER BY started_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def purge_old_data(self, retention_days: int = 90, vacuum: bool = False) -> dict[str, int | str]:
        """Delete rows older than the rolling retention window.

        This implements a true rolling cleanup window. Example: with
        retention_days=90, once data exceeds 90 days, only rows older than the
        latest 90-day window are removed. Newer rows remain intact.
        """
        retention_days = max(1, int(retention_days))
        cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
        cutoff_iso = cutoff.isoformat()

        with self.connect() as conn:
            cycle_deleted = conn.execute(
                "DELETE FROM cycle_runs WHERE started_at < ?",
                (cutoff_iso,),
            ).rowcount
            signal_deleted = conn.execute(
                "DELETE FROM signals_log WHERE logged_at < ?",
                (cutoff_iso,),
            ).rowcount
            trade_deleted = conn.execute(
                "DELETE FROM trades WHERE created_at < ?",
                (cutoff_iso,),
            ).rowcount
            conn.commit()
            if vacuum:
                conn.execute("VACUUM")

        summary = {
            "retention_days": retention_days,
            "cutoff_utc": cutoff_iso,
            "cycle_runs_deleted": int(cycle_deleted),
            "signals_deleted": int(signal_deleted),
            "trades_deleted": int(trade_deleted),
            "vacuum": "yes" if vacuum else "no",
        }
        self.upsert_state("last_retention_cleanup", {
            **summary,
            "ran_at": utc_now_iso(),
        })
        return summary
