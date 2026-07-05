"""
Startup/runtime reconciliation helpers for the CPR Gold Bot.
Broker state is treated as the source of truth for open positions/trades.
"""
from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def reconcile_runtime_state(trader, history: list, instrument: str, now_sgt, alert=None) -> dict:
    """
    Reconcile local history with broker truth.

    What it does:
    - detects currently open trades at the broker
    - inserts a recovered FILLED record into history if an open broker trade
      exists but local history does not know about it
    - back-fills realized P&L on local FILLED trades that are now closed
    - returns a summary for logging/decision-making
    """
    summary = {
        "open_trade_ids": [],
        "open_trade_count": 0,
        "recovered_trade_ids": [],
        "backfilled_trade_ids": [],
        "recent_closed_count": 0,
    }

    try:
        open_trades = trader.get_open_trades(instrument)
    except Exception as exc:
        log.warning("Could not fetch open trades during reconciliation: %s", exc)
        open_trades = []

    summary["open_trade_ids"] = [str(t.get("id")) for t in open_trades if t.get("id")]
    summary["open_trade_count"] = len(summary["open_trade_ids"])

    local_trade_ids = {
        str(t.get("trade_id")) for t in history
        if t.get("status") == "FILLED" and t.get("trade_id") is not None
    }

    for trade in open_trades:
        trade_id = str(trade.get("id", "")).strip()
        if not trade_id or trade_id in local_trade_ids:
            continue

        current_units = _safe_float(trade.get("currentUnits"))
        direction = "BUY" if current_units > 0 else "SELL"
        entry = _safe_float(trade.get("price"))
        recovered = {
            "timestamp_sgt": now_sgt.strftime("%Y-%m-%d %H:%M:%S"),
            "mode": "RECOVERED",
            "instrument": instrument,
            "direction": direction,
            "setup": "startup_reconciled",
            "session": "Recovered",
            "macro_session": "Recovered",
            "score": None,
            "threshold": None,
            "entry": round(entry, 2) if entry > 0 else None,
            "sl_price": None,
            "tp_price": None,
            "size": abs(current_units),
            "cpr_width_pct": None,
            "estimated_risk_usd": None,
            "estimated_reward_usd": None,
            "spread_pips": None,
            "stop_pips": None,
            "tp_pips": None,
            "levels": {"source": "broker_reconciliation"},
            "details": "Recovered from broker openTrades during startup/runtime reconciliation.",
            "trade_id": trade_id,
            "status": "FILLED",
            "realized_pnl_usd": None,
            "breakeven_moved": False,
        }
        history.append(recovered)
        summary["recovered_trade_ids"].append(trade_id)
        local_trade_ids.add(trade_id)
        log.warning("Recovered open broker trade into local history: %s", trade_id)

    try:
        recent_closed = trader.get_recent_closed_trades(instrument, count=25)
        summary["recent_closed_count"] = len(recent_closed)
    except Exception as exc:
        log.warning("Could not fetch recent closed trades during reconciliation: %s", exc)
        recent_closed = []

    pnl_by_trade_id = {}
    for trade in recent_closed:
        trade_id = str(trade.get("id", "")).strip()
        if not trade_id:
            continue
        pnl = trade.get("realizedPL")
        if pnl is not None:
            pnl_by_trade_id[trade_id] = _safe_float(pnl)

    open_trade_ids = set(summary["open_trade_ids"])
    for item in history:
        if item.get("status") != "FILLED":
            continue
        trade_id = str(item.get("trade_id", "")).strip()
        if not trade_id or trade_id in open_trade_ids:
            continue
        if item.get("realized_pnl_usd") is not None:
            continue

        pnl = pnl_by_trade_id.get(trade_id)
        if pnl is None:
            pnl = trader.get_trade_pnl(trade_id)
        if pnl is not None:
            item["realized_pnl_usd"] = pnl
            # Only mark for backfill if backfill_pnl hasn't already sent the alert
            if not item.get("closed_alert_sent"):
                summary["backfilled_trade_ids"].append(trade_id)
            log.info("Reconciled closed trade %s with realized P&L $%.2f", trade_id, pnl)

    if alert and summary["recovered_trade_ids"]:
        alert.send(
            "♻️ Startup reconciliation recovered open broker trade(s): "
            + ", ".join(summary["recovered_trade_ids"])
        )

    return summary


def startup_oanda_reconcile(
    trader,
    history: list,
    instrument: str,
    today_sgt: str,
    now_sgt,
) -> dict:
    """Reconcile today's closed trades from OANDA before the first bot cycle.

    Problem it solves:
    ──────────────────────────
    After a mid-day redeploy the bot boots with a fresh in-memory state and
    reads history.json from the persistent volume.  If any trades closed
    between the last successful save and the restart they will be absent from
    history, so daily_totals() under-counts losses and the loss cap fails to
    fire correctly.

    Fix:
    ────
    On every startup call OANDA's transactions endpoint for today's SGT date,
    collect every closing ORDER_FILL, and for each one:
      1. If the trade_id already exists in history with realized_pnl_usd set
         → already known, skip.
      2. If the trade_id exists but pnl is None → fill it in (backfill).
      3. If the trade_id is absent entirely → insert a synthetic FILLED record.

    history is mutated in place.  The caller (bot.py run_bot_cycle) is
    responsible for calling save_history() if the returned summary shows any
    changes.

    Returns a summary dict with keys:
      injected    — list of trade_ids newly inserted
      backfilled  — list of trade_ids whose pnl was filled in
      skipped     — count of already-known trades
      errors      — any non-fatal error messages
    """
    import pytz
    from datetime import datetime

    SGT = pytz.timezone("Asia/Singapore")

    summary = {
        "injected":   [],
        "backfilled": [],
        "skipped":    0,
        "errors":     [],
    }

    try:
        closing_txns = trader.get_today_closed_transactions(instrument, today_sgt)
    except Exception as exc:
        msg = f"startup_oanda_reconcile: could not fetch transactions: {exc}"
        log.warning(msg)
        summary["errors"].append(msg)
        return summary

    if not closing_txns:
        log.info("startup_oanda_reconcile: no closing transactions found for %s on %s", instrument, today_sgt)
        return summary

    # Build a lookup of what history already knows, keyed by trade_id
    history_by_trade_id: dict = {}
    for item in history:
        tid = str(item.get("trade_id", "")).strip()
        if tid:
            history_by_trade_id[tid] = item

    for txn in closing_txns:
        trades_closed = txn.get("tradesClosed", [])
        if not trades_closed:
            continue

        for tc in trades_closed:
            trade_id = str(tc.get("tradeID", "")).strip()
            if not trade_id:
                continue

            raw_pnl = tc.get("realizedPL")
            try:
                pnl = float(raw_pnl) if raw_pnl is not None else None
            except (TypeError, ValueError):
                pnl = None

            # Parse close time from transaction (UTC) → SGT string
            close_time_str = ""
            txn_time = txn.get("time", "")
            if txn_time:
                try:
                    dt_utc = datetime.strptime(txn_time[:19], "%Y-%m-%dT%H:%M:%S")
                    dt_sgt = pytz.utc.localize(dt_utc).astimezone(SGT)
                    close_time_str = dt_sgt.strftime("%Y-%m-%d %H:%M:%S")
                except Exception:
                    close_time_str = ""

            if trade_id in history_by_trade_id:
                existing = history_by_trade_id[trade_id]
                if existing.get("realized_pnl_usd") is None and pnl is not None:
                    existing["realized_pnl_usd"] = pnl
                    if close_time_str:
                        existing.setdefault("closed_at_sgt", close_time_str)
                    summary["backfilled"].append(trade_id)
                    log.info(
                        "startup_oanda_reconcile: backfilled pnl=%.2f for trade %s",
                        pnl, trade_id,
                    )
                else:
                    summary["skipped"] += 1
                continue

            # Trade not in history at all — infer direction from closing units
            # Closing a SELL trade means buying back → closing units > 0 → original was SELL
            closing_units = _safe_float(txn.get("units", 0))
            direction = "SELL" if closing_units > 0 else "BUY"

            record = {
                "timestamp_sgt":      close_time_str or now_sgt.strftime("%Y-%m-%d %H:%M:%S"),
                "closed_at_sgt":      close_time_str,
                "mode":               "BROKER_RECONCILED",
                "instrument":         instrument,
                "direction":          direction,
                "setup":              "broker_reconciled_startup",
                "session":            "Reconciled",
                "macro_session":      "Reconciled",
                "score":              None,
                "threshold":          None,
                "entry":              None,
                "sl_price":           None,
                "tp_price":           None,
                "size":               abs(_safe_float(tc.get("units", closing_units))),
                "cpr_width_pct":      None,
                "estimated_risk_usd": None,
                "estimated_reward_usd": None,
                "spread_pips":        None,
                "stop_pips":          None,
                "tp_pips":            None,
                "levels":             {"source": "startup_oanda_reconcile"},
                "details":            "Injected by startup_oanda_reconcile — was missing from history.json after redeploy.",
                "trade_id":           trade_id,
                "status":             "FILLED",
                "realized_pnl_usd":   pnl,
                "breakeven_moved":    False,
                "closed_alert_sent":  True,  # suppress backfill Telegram alert for this
            }
            history.append(record)
            history_by_trade_id[trade_id] = record
            summary["injected"].append(trade_id)
            log.warning(
                "startup_oanda_reconcile: injected missing closed trade %s pnl=%.2f direction=%s",
                trade_id, pnl or 0, direction,
            )

    log.info(
        "startup_oanda_reconcile complete: injected=%d backfilled=%d skipped=%d",
        len(summary["injected"]), len(summary["backfilled"]), summary["skipped"],
    )
    return summary
