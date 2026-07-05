"""signal_logger.py — Rogue-H1 v2.0

CSV signal journal for Railway /data persistence.

Logs every meaningful signal evaluation to /data/signal_log.csv so demo runs
can be reviewed later and used for future AI/ML training.

Controlled by settings:
  signal_logging_enabled: true/false
  signal_log_min_score:   minimum score to keep when action=NOISE
  signal_telegram_updates_enabled: true/false is handled by bot.py templates
"""
from __future__ import annotations

import csv
import logging
import os
from datetime import datetime
from pathlib import Path

import pytz

log = logging.getLogger(__name__)

_SGT = pytz.timezone("Asia/Singapore")
_DATA_DIR = Path(os.getenv("DATA_DIR", "/data"))
_LOG_FILE = _DATA_DIR / "signal_log.csv"

_FIELDNAMES = [
    "timestamp_sgt",
    "day_of_week",
    "session",
    "hour_sgt",
    "symbol",
    "timeframe",
    "direction",
    "score",
    "raw_score",
    "news_penalty",
    "setup",
    "current_price",
    "entry_price",
    "sl_usd",
    "tp_usd",
    "rr_ratio",
    "position_usd",
    "risk_model",
    "effective_balance",
    "units",
    "pivot",
    "tc",
    "bc",
    "r1",
    "r2",
    "s1",
    "s2",
    "pdh",
    "pdl",
    "cpr_width_pct",
    "atr",
    "sma20",
    "sma50",
    "trend_filter_tf",
    "trend_price",
    "trend_ema_value",
    "h4_trend",
    "spread_pips",
    "news_status",
    "action",
    "block_reason",
    "details",
    "signal_candle_sgt",
    "signal_fingerprint",
    "outcome",
    "pl_usd",
    "trade_id",
    "daily_pnl",
    "daily_equity_loss_cap_percent",
    "daily_equity_loss_cap_amount",
]


def _ensure_header() -> None:
    _LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not _LOG_FILE.exists() or _LOG_FILE.stat().st_size == 0:
        with open(_LOG_FILE, "w", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=_FIELDNAMES).writeheader()


def _safe(v, default=""):
    return default if v is None else v


def log_signal(
    *,
    settings: dict | None,
    score: int,
    direction: str,
    session: str,
    levels: dict,
    action: str,
    block_reason: str = "",
    details: str = "",
    raw_score: int | None = None,
    news_penalty: int = 0,
    news_status: str = "",
    spread_pips=None,
    sl_usd=None,
    tp_usd=None,
    rr_ratio=None,
    position_usd=None,
    units=None,
    trade_id: str = "",
    daily_pnl=None,
    daily_equity_loss_cap_percent=None,
    daily_equity_loss_cap_amount=None,
    effective_balance=None,
    signal_candle_sgt=None,
    signal_fingerprint=None,
) -> None:
    """Append one signal evaluation row to signal_log.csv."""
    settings = settings or {}
    if not bool(settings.get("signal_logging_enabled", False)):
        return

    min_score = int(settings.get("signal_log_min_score", 0))
    if action == "NOISE" and int(score or 0) < min_score:
        return

    try:
        _ensure_header()
        now_sgt = datetime.now(_SGT)
        h4_trend = ""
        if levels.get("h1_trend_bullish") is True:
            h4_trend = "BULLISH"
        elif levels.get("h1_trend_bullish") is False:
            h4_trend = "BEARISH"

        row = {
            "timestamp_sgt": now_sgt.strftime("%Y-%m-%d %H:%M:%S"),
            "day_of_week": now_sgt.strftime("%A"),
            "session": session or "",
            "hour_sgt": now_sgt.hour,
            "symbol": settings.get("instrument_display", "XAU/USD"),
            "timeframe": settings.get("timeframe", "H1"),
            "direction": direction,
            "score": score,
            "raw_score": _safe(raw_score, score),
            "news_penalty": news_penalty,
            "setup": levels.get("setup", ""),
            "current_price": levels.get("current_price", ""),
            "entry_price": levels.get("entry", ""),
            "sl_usd": _safe(sl_usd),
            "tp_usd": _safe(tp_usd),
            "rr_ratio": _safe(rr_ratio),
            "position_usd": _safe(position_usd),
            "risk_model": "fixed",
            "effective_balance": _safe(effective_balance, settings.get("account_balance_override") or settings.get("fallback_account_balance", "")),
            "units": _safe(units),
            "pivot": levels.get("pivot", ""),
            "tc": levels.get("tc", ""),
            "bc": levels.get("bc", ""),
            "r1": levels.get("r1", ""),
            "r2": levels.get("r2", ""),
            "s1": levels.get("s1", ""),
            "s2": levels.get("s2", ""),
            "pdh": levels.get("pdh", ""),
            "pdl": levels.get("pdl", ""),
            "cpr_width_pct": levels.get("cpr_width_pct", ""),
            "atr": levels.get("atr", ""),
            "sma20": levels.get("sma20", ""),
            "sma50": levels.get("sma50", ""),
            "trend_filter_tf": levels.get("trend_filter_tf", ""),
            "trend_price": levels.get("trend_price", ""),
            "trend_ema_value": levels.get("trend_ema_value", ""),
            "h4_trend": h4_trend,
            "spread_pips": _safe(spread_pips),
            "news_status": news_status,
            "action": action,
            "block_reason": block_reason,
            "details": details,
            "signal_candle_sgt": _safe(signal_candle_sgt, levels.get("signal_candle_sgt", "")),
            "signal_fingerprint": _safe(signal_fingerprint, levels.get("signal_fingerprint", "")),
            "outcome": "",
            "pl_usd": "",
            "trade_id": trade_id,
            "daily_pnl": _safe(daily_pnl),
            "daily_equity_loss_cap_percent": _safe(daily_equity_loss_cap_percent),
            "daily_equity_loss_cap_amount": _safe(daily_equity_loss_cap_amount),
        }
        with open(_LOG_FILE, "a", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=_FIELDNAMES, extrasaction="ignore").writerow(row)
        log.debug("Signal journal row written: %s score=%s action=%s", direction, score, action)
    except Exception as exc:
        log.warning("signal_logger: failed to write row: %s", exc)


def backfill_outcome(trade_id: str, outcome: str, pl_usd: float, settings: dict | None = None) -> None:
    """Back-fill trade outcome into the matching FIRED row."""
    if settings and not settings.get("signal_logging_enabled", False):
        return
    if not _LOG_FILE.exists() or not trade_id:
        return
    try:
        rows = []
        updated = 0
        with open(_LOG_FILE, "r", newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row.get("action") == "FIRED" and row.get("trade_id") == str(trade_id) and not row.get("outcome"):
                    row["outcome"] = outcome
                    row["pl_usd"] = round(float(pl_usd), 2)
                    updated += 1
                rows.append(row)
        if updated:
            with open(_LOG_FILE, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=_FIELDNAMES)
                writer.writeheader()
                writer.writerows(rows)
            log.info("signal_logger: backfilled %s $%.2f for trade %s", outcome, pl_usd, trade_id)
    except Exception as exc:
        log.warning("signal_logger: backfill_outcome failed: %s", exc)


def get_signal_log_path() -> Path:
    return _LOG_FILE
