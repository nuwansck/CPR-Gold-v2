"""reporting.py — CPR Gold Bot Telegram Performance Reports

Three scheduled reports, all reading directly from /data/trade_history.json
on the Railway persistent volume. No archive file needed — the 90-day rolling
window covers all report periods.

Schedule (Asia/Singapore timezone, managed by scheduler.py):
  Monthly  — First Monday of each month at 08:00 SGT
  Weekly   — Every Monday at 08:15 SGT  (covers Mon–Fri prior week)
  Daily    — Mon–Fri at 09:30 SGT       (covers prior trading day, 30 min before Asian open)

Usage (called by scheduler.py):
    from reporting import send_daily_report, send_weekly_report, send_monthly_report
"""
from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import datetime, timedelta

import pytz

from config_loader import load_settings
from state_utils import TRADE_HISTORY_FILE
from telegram_alert import TelegramAlert
from telegram_templates import msg_daily_report, msg_session_report, msg_weekly_report, msg_monthly_report

log = logging.getLogger(__name__)
SGT = pytz.timezone("Asia/Singapore")


# ── Data loading ───────────────────────────────────────────────────────────────

def _load_history() -> list:
    """Load trade_history.json from /data. Returns [] on any error."""
    if not TRADE_HISTORY_FILE.exists():
        return []
    try:
        data = json.loads(TRADE_HISTORY_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception as exc:
        log.warning("reporting: could not read trade_history.json: %s", exc)
        return []


def _parse_ts(ts: str | None) -> datetime | None:
    """Parse a SGT timestamp string to an aware datetime, or None."""
    if not ts:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return SGT.localize(datetime.strptime(ts, fmt))
        except Exception:
            pass
    return None


def _filled(history: list) -> list:
    """Return only FILLED trades with a realized PnL."""
    return [
        t for t in history
        if t.get("status") == "FILLED" and isinstance(t.get("realized_pnl_usd"), (int, float))
    ]


def _trades_in_window(filled: list, start: datetime, end: datetime) -> list:
    """Filter filled trades whose timestamp_sgt falls within [start, end)."""
    result = []
    for t in filled:
        dt = _parse_ts(t.get("timestamp_sgt"))
        if dt and start <= dt < end:
            result.append(t)
    return result


# ── Stats builders ─────────────────────────────────────────────────────────────

def _stats(trades: list) -> dict:
    """Compute standard stats dict from a list of filled trades."""
    if not trades:
        return {
            "count": 0, "wins": 0, "losses": 0,
            "net_pnl": 0.0, "gross_profit": 0.0, "gross_loss": 0.0,
            "win_rate": 0.0, "profit_factor": None,
            "avg_r": None, "max_win_streak": 0, "max_loss_streak": 0,
            "best_trade": None, "worst_trade": None,
        }

    wins   = [t for t in trades if t["realized_pnl_usd"] > 0]
    losses = [t for t in trades if t["realized_pnl_usd"] < 0]

    gross_profit = sum(t["realized_pnl_usd"] for t in wins)
    gross_loss   = abs(sum(t["realized_pnl_usd"] for t in losses))
    net_pnl      = gross_profit - gross_loss
    win_rate     = round(len(wins) / len(trades) * 100, 1) if trades else 0.0
    pf           = round(gross_profit / gross_loss, 2) if gross_loss > 0 else None

    # R-multiple (uses estimated_risk_usd added by C-01 fix)
    r_vals = []
    for t in trades:
        risk = t.get("estimated_risk_usd")
        if risk and risk > 0:
            r_vals.append(round(t["realized_pnl_usd"] / risk, 2))
    avg_r = round(sum(r_vals) / len(r_vals), 2) if r_vals else None

    # Streaks
    outcomes = ["W" if t["realized_pnl_usd"] > 0 else "L" for t in trades]
    max_win_s = max_loss_s = cur = 0
    prev = None
    for o in outcomes:
        if o == prev:
            cur += 1
        else:
            cur = 1
            prev = o
        if o == "W":
            max_win_s = max(max_win_s, cur)
        else:
            max_loss_s = max(max_loss_s, cur)

    # Best and worst individual trade
    def _trade_summary(t):
        raw_time = t.get("closed_at_sgt") or t.get("timestamp_sgt") or ""
        hhmm = raw_time[11:16] if len(raw_time) >= 16 else raw_time
        return {
            "pnl":  round(t["realized_pnl_usd"], 2),
            "time": hhmm,
        }

    best_trade  = _trade_summary(max(trades, key=lambda t: t["realized_pnl_usd"]))
    worst_trade = _trade_summary(min(trades, key=lambda t: t["realized_pnl_usd"]))

    return {
        "count":          len(trades),
        "wins":           len(wins),
        "losses":         len(losses),
        "net_pnl":        round(net_pnl, 2),
        "gross_profit":   round(gross_profit, 2),
        "gross_loss":     round(gross_loss, 2),
        "win_rate":       win_rate,
        "profit_factor":  pf,
        "avg_r":          avg_r,
        "max_win_streak": max_win_s,
        "max_loss_streak":max_loss_s,
        "best_trade":     best_trade,
        "worst_trade":    worst_trade,
    }


def _session_breakdown(trades: list) -> dict[str, dict]:
    """Win rate + PnL per macro session."""
    buckets: dict[str, list] = defaultdict(list)
    for t in trades:
        sess = t.get("macro_session") or t.get("session") or "Unknown"
        buckets[sess].append(t)
    result = {}
    for sess, ts in sorted(buckets.items()):
        wins = [t for t in ts if t["realized_pnl_usd"] > 0]
        result[sess] = {
            "count":    len(ts),
            "win_rate": round(len(wins) / len(ts) * 100, 1),
            "net_pnl":  round(sum(t["realized_pnl_usd"] for t in ts), 2),
        }
    return result


def _setup_breakdown(trades: list) -> dict[str, dict]:
    """Win rate + PnL per setup type."""
    buckets: dict[str, list] = defaultdict(list)
    for t in trades:
        setup = t.get("setup") or "Unknown"
        buckets[setup].append(t)
    result = {}
    for setup, ts in sorted(buckets.items()):
        wins = [t for t in ts if t["realized_pnl_usd"] > 0]
        result[setup] = {
            "count":    len(ts),
            "win_rate": round(len(wins) / len(ts) * 100, 1),
            "net_pnl":  round(sum(t["realized_pnl_usd"] for t in ts), 2),
        }
    return result


def _score_breakdown(trades: list) -> dict[int, dict]:
    """Win rate per signal score."""
    buckets: dict[int, list] = defaultdict(list)
    for t in trades:
        score = t.get("score")
        if score is not None:
            buckets[int(score)].append(t)
    result = {}
    for score in sorted(buckets.keys()):
        ts   = buckets[score]
        wins = [t for t in ts if t["realized_pnl_usd"] > 0]
        result[score] = {
            "count":    len(ts),
            "win_rate": round(len(wins) / len(ts) * 100, 1),
        }
    return result


# ── Window helpers ─────────────────────────────────────────────────────────────

def _prior_trading_day(now: datetime) -> tuple[datetime, datetime]:
    """Return (start, end) for the prior trading day in SGT.
    On Monday, looks back to Friday. Skips Saturday/Sunday.
    """
    day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    day -= timedelta(days=1)
    # Step back over weekend
    while day.weekday() in (5, 6):
        day -= timedelta(days=1)
    return day, day + timedelta(days=1)


def _current_week_window(now: datetime) -> tuple[datetime, datetime]:
    """Return (Mon 00:00, now) for the current week."""
    days_since_mon = now.weekday()
    week_start = (now - timedelta(days=days_since_mon)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return week_start, now


def _prior_week_window(now: datetime) -> tuple[datetime, datetime, str]:
    """Return (Mon 00:00, Fri 23:59:59, label) for the prior Mon–Fri week."""
    days_since_mon = now.weekday()
    this_mon = (now - timedelta(days=days_since_mon)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    prior_mon = this_mon - timedelta(days=7)
    prior_fri = this_mon - timedelta(seconds=1)
    label = f"{prior_mon.strftime('%d %b')} – {prior_fri.strftime('%d %b %Y')}"
    return prior_mon, this_mon, label


def _current_month_window(now: datetime) -> tuple[datetime, datetime]:
    """Return (1st of current month 00:00, now)."""
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return month_start, now


def _prior_month_window(now: datetime) -> tuple[datetime, datetime, str]:
    """Return (1st of prior month, 1st of current month, label)."""
    first_this = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    last_prior = first_this - timedelta(seconds=1)
    first_prior = last_prior.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    label = first_prior.strftime("%B %Y")
    return first_prior, first_this, label


def _is_first_monday_of_month(now: datetime) -> bool:
    """True if today (SGT) is the first Monday of the calendar month."""
    return now.weekday() == 0 and now.day <= 7


# ── Report senders ─────────────────────────────────────────────────────────────

def send_session_report(session_key: str) -> None:
    """Send a performance summary for a single completed session.

    session_key: "Asian" | "London" | "US"
    Called ~5 min after each session closes so all trades are settled.
    """
    from config_loader import load_settings
    _BANNERS = {"Asian": "🌏 ASIAN", "London": "🇬🇧 LONDON", "US": "🗽 US"}
    # Session windows in SGT (start_hour, end_hour inclusive)
    _WINDOWS = {
        "Asian":  (8,  15),
        "London": (16, 20),
        "US":     (21, 0),   # 21–23 + 00
    }
    try:
        settings = load_settings()
        now      = datetime.now(SGT)
        filled   = _filled(_load_history())

        # Build window for this session on today's trading day
        start_h, end_h = _WINDOWS.get(session_key, (16, 20))
        # For US session end crosses midnight: use today's date for 21–23 and yesterday for 00
        today = now.date()
        if session_key == "US":
            # US runs 21:00 yesterday → 00:59 today (SGT)
            # We fire at 01:05 SGT so "today" is the next calendar day
            from datetime import timedelta
            sess_start = datetime(today.year, today.month, today.day, 21, 0, 0, tzinfo=SGT) - timedelta(days=1)
            sess_end   = datetime(today.year, today.month, today.day, 0, 59, 59, tzinfo=SGT)
        else:
            sess_start = datetime(today.year, today.month, today.day, start_h, 0, 0, tzinfo=SGT)
            sess_end   = datetime(today.year, today.month, today.day, end_h, 59, 59, tzinfo=SGT)

        sess_trades = _trades_in_window(filled, sess_start, sess_end)
        sess_stats  = _stats(sess_trades)

        # Next session time for display
        _next_times = {
            "Asian":  f"London ({int(settings.get('session_start_hour_sgt', 16)):02d}:00 SGT)",
            "London": "US (21:00 SGT)",
            "US":     "Asian (08:00 SGT tomorrow)",
        }
        next_sess = _next_times.get(session_key, "")

        msg = msg_session_report(
            session_name = session_key,
            banner       = _BANNERS.get(session_key, session_key),
            session_stats= sess_stats,
            report_time  = now.strftime("%H:%M SGT"),
            next_session = next_sess,
        )
        ok = TelegramAlert().send(msg)
        if ok:
            log.info("%s session report sent.", session_key)
        else:
            log.warning("%s session report send failed.", session_key)
    except Exception as exc:
        log.exception("send_session_report(%s) error: %s", session_key, exc)


def send_asian_session_report()  -> None: send_session_report("Asian")
def send_london_session_report() -> None: send_session_report("London")
def send_us_session_report()     -> None: send_session_report("US")


def send_daily_report() -> None:
    """Send daily performance summary at 09:30 SGT Mon–Fri.

    Covers:
      - Prior trading day  (yesterday, or Friday if today is Monday)
      - Week-to-date       (Monday 00:00 → now)
      - Month-to-date      (1st → now)
    """
    try:
        now    = datetime.now(SGT)
        filled = _filled(_load_history())

        # Prior day
        pd_start, pd_end   = _prior_trading_day(now)
        pd_trades          = _trades_in_window(filled, pd_start, pd_end)
        pd_stats           = _stats(pd_trades)
        pd_label           = pd_start.strftime("%A %d %b")

        # Week-to-date
        wtd_start, wtd_end = _current_week_window(now)
        wtd_trades         = _trades_in_window(filled, wtd_start, wtd_end)
        wtd_stats          = _stats(wtd_trades)

        # Month-to-date
        mtd_start, mtd_end = _current_month_window(now)
        mtd_trades         = _trades_in_window(filled, mtd_start, mtd_end)
        mtd_stats          = _stats(mtd_trades)

        # Open positions count (trades with no realized_pnl yet)
        open_count = sum(
            1 for t in _load_history()
            if t.get("status") == "FILLED" and t.get("realized_pnl_usd") is None
        )

        _rep_settings = load_settings()
        _sess_hour = int(_rep_settings.get('session_start_hour_sgt', 16))
        msg = msg_daily_report(
            day_label   = pd_label,
            day_stats   = pd_stats,
            wtd_stats   = wtd_stats,
            mtd_stats   = mtd_stats,
            open_count  = open_count,
            report_time = now.strftime("%H:%M SGT"),
            session_start_sgt=f"{_sess_hour:02d}:00 SGT",
        )
        ok = TelegramAlert().send(msg)
        if ok:
            log.info("Daily report sent.")
        else:
            log.warning("Daily report send failed.")
    except Exception as exc:
        log.exception("send_daily_report error: %s", exc)


def send_weekly_report() -> None:
    """Send weekly performance report every Monday at 08:15 SGT.

    Covers the prior Mon–Fri trading week with full breakdown.
    """
    try:
        now    = datetime.now(SGT)
        filled = _filled(_load_history())

        pw_start, pw_end, pw_label = _prior_week_window(now)
        pw_trades                  = _trades_in_window(filled, pw_start, pw_end)
        pw_stats                   = _stats(pw_trades)
        sessions                   = _session_breakdown(pw_trades)
        setups                     = _setup_breakdown(pw_trades)

        msg = msg_weekly_report(
            week_label = pw_label,
            stats      = pw_stats,
            sessions   = sessions,
            setups     = setups,
            report_time= now.strftime("%H:%M SGT"),
        )
        ok = TelegramAlert().send(msg)
        if ok:
            log.info("Weekly report sent.")
        else:
            log.warning("Weekly report send failed.")
    except Exception as exc:
        log.exception("send_weekly_report error: %s", exc)


def send_monthly_report() -> None:
    """Send monthly performance report on the first Monday of each month at 08:00 SGT.

    Covers the prior full calendar month with session, setup, and score breakdown.
    Also shows month-over-month PnL delta when prior-prior month data exists.
    The first-Monday guard is enforced here so the scheduler can use a simple
    weekly cron without needing a complex calendar trigger.
    """
    try:
        now = datetime.now(SGT)

        if not _is_first_monday_of_month(now):
            log.info("Monthly report skipped — not first Monday of month (%s)", now.strftime("%d %b"))
            return

        filled = _filled(_load_history())

        pm_start, pm_end, pm_label = _prior_month_window(now)
        pm_trades                  = _trades_in_window(filled, pm_start, pm_end)
        pm_stats                   = _stats(pm_trades)
        sessions                   = _session_breakdown(pm_trades)
        setups                     = _setup_breakdown(pm_trades)
        scores                     = _score_breakdown(pm_trades)

        # Month-over-month delta: compare prior month PnL vs the month before that
        ppm_start = (pm_start.replace(day=1) - timedelta(days=1)).replace(
            day=1, hour=0, minute=0, second=0, microsecond=0
        )
        ppm_trades = _trades_in_window(filled, ppm_start, pm_start)
        ppm_pnl    = round(sum(t["realized_pnl_usd"] for t in ppm_trades), 2) if ppm_trades else None
        mom_delta  = round(pm_stats["net_pnl"] - ppm_pnl, 2) if ppm_pnl is not None else None

        msg = msg_monthly_report(
            month_label = pm_label,
            stats       = pm_stats,
            sessions    = sessions,
            setups      = setups,
            scores      = scores,
            mom_delta   = mom_delta,
            prior_month_pnl = ppm_pnl,
            report_time = now.strftime("%H:%M SGT"),
        )
        ok = TelegramAlert().send(msg)
        if ok:
            log.info("Monthly report sent for %s.", pm_label)
        else:
            log.warning("Monthly report send failed.")
    except Exception as exc:
        log.exception("send_monthly_report error: %s", exc)
