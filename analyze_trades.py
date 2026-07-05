"""
analyze_trades.py — CPR Gold Bot Performance Dashboard
Run from the same folder as trade_history.json:

    python analyze_trades.py              # all FILLED trades
    python analyze_trades.py --all        # include FAILED orders too
    python analyze_trades.py --last 30    # last 30 days only
"""

import json
import sys
import pytz
from state_utils import TRADE_HISTORY_FILE
from collections import defaultdict
from datetime import datetime, timedelta

_SGT = pytz.timezone("Asia/Singapore")

HISTORY_FILE = TRADE_HISTORY_FILE
# Removed: ARCHIVE_FILE — archival removed; 90-day rolling window in trade_history.json is sufficient

# ─────────────────────────────────────────────────────────────
# Load
# ─────────────────────────────────────────────────────────────

def load_trades(include_failed=False, last_days=None):
    trades = []
    if HISTORY_FILE.exists():
        try:
            data = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
            if isinstance(data, list):
                trades.extend(data)
        except Exception as e:
            print(f"⚠️  Could not read {HISTORY_FILE}: {e}")

    if not include_failed:
        trades = [t for t in trades if t.get("status") == "FILLED"]

    if last_days:
        cutoff = datetime.now(_SGT) - timedelta(days=last_days)
        filtered = []
        for t in trades:
            ts = t.get("timestamp_sgt", "")
            try:
                dt = _SGT.localize(datetime.strptime(ts, "%Y-%m-%d %H:%M:%S"))
                if dt >= cutoff:
                    filtered.append(t)
            except Exception:
                filtered.append(t)
        trades = filtered

    # Sort chronologically
    trades.sort(key=lambda t: t.get("timestamp_sgt", ""))
    return trades


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────

def classify(trade):
    """Return 'WIN', 'LOSS', or 'OPEN' for a trade."""
    pnl = trade.get("realized_pnl_usd")
    if pnl is None:
        return "OPEN"
    return "WIN" if pnl > 0 else "LOSS"


def r_multiple(trade):
    """
    Estimate R multiple from pnl vs estimated_risk_usd.
    Returns None for open trades or missing data.
    """
    pnl  = trade.get("realized_pnl_usd")
    risk = trade.get("estimated_risk_usd")
    if pnl is None or not risk or risk == 0:
        return None
    return round(pnl / risk, 2)


def max_streak(outcomes, target):
    """Longest consecutive run of `target` ('WIN' or 'LOSS') in outcomes list."""
    best = cur = 0
    for o in outcomes:
        if o == target:
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    return best


# ─────────────────────────────────────────────────────────────
# Stats builders
# ─────────────────────────────────────────────────────────────

def overall_stats(trades):
    closed = [t for t in trades if classify(t) != "OPEN"]
    open_  = [t for t in trades if classify(t) == "OPEN"]

    if not closed:
        return None, open_

    wins   = [t for t in closed if classify(t) == "WIN"]
    losses = [t for t in closed if classify(t) == "LOSS"]

    gross_profit = sum(t["realized_pnl_usd"] for t in wins)
    gross_loss   = abs(sum(t["realized_pnl_usd"] for t in losses))
    net_pnl      = gross_profit - gross_loss
    profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else float("inf")
    win_rate      = round(len(wins) / len(closed) * 100, 1)

    r_vals = [r_multiple(t) for t in closed if r_multiple(t) is not None]
    avg_r  = round(sum(r_vals) / len(r_vals), 2) if r_vals else None

    outcomes   = [classify(t) for t in closed]
    max_loss_s = max_streak(outcomes, "LOSS")
    max_win_s  = max_streak(outcomes, "WIN")

    # Dates
    first_date = closed[0].get("timestamp_sgt", "?")[:10]
    last_date  = closed[-1].get("timestamp_sgt", "?")[:10]

    stats = {
        "total_trades":   len(closed),
        "wins":           len(wins),
        "losses":         len(losses),
        "open":           len(open_),
        "win_rate":       win_rate,
        "profit_factor":  profit_factor,
        "net_pnl":        round(net_pnl, 2),
        "gross_profit":   round(gross_profit, 2),
        "gross_loss":     round(gross_loss, 2),
        "avg_r":          avg_r,
        "max_win_streak": max_win_s,
        "max_loss_streak":max_loss_s,
        "first_trade":    first_date,
        "last_trade":     last_date,
    }
    return stats, open_


def session_stats(trades):
    """Win rate and P&L per macro session (Asian / London / US)."""
    buckets = defaultdict(list)
    for t in trades:
        macro = t.get("macro_session", t.get("session", "Unknown"))
        if classify(t) != "OPEN":
            buckets[macro].append(t)

    results = {}
    for session, ts in sorted(buckets.items()):
        wins  = [t for t in ts if classify(t) == "WIN"]
        pnl   = sum(t["realized_pnl_usd"] for t in ts)
        r_vals = [r_multiple(t) for t in ts if r_multiple(t) is not None]
        avg_r  = round(sum(r_vals) / len(r_vals), 2) if r_vals else None
        results[session] = {
            "trades":    len(ts),
            "win_rate":  round(len(wins) / len(ts) * 100, 1),
            "net_pnl":   round(pnl, 2),
            "avg_r":     avg_r,
        }
    return results


def setup_stats(trades):
    """Win rate per setup type (Top CPR Breakout, PDH Breakout, etc.)."""
    buckets = defaultdict(list)
    for t in trades:
        setup = t.get("setup", "Unknown")
        if classify(t) != "OPEN":
            buckets[setup].append(t)

    results = {}
    for setup, ts in sorted(buckets.items()):
        wins = [t for t in ts if classify(t) == "WIN"]
        pnl  = sum(t["realized_pnl_usd"] for t in ts)
        results[setup] = {
            "trades":   len(ts),
            "win_rate": round(len(wins) / len(ts) * 100, 1),
            "net_pnl":  round(pnl, 2),
        }
    return results


def score_stats(trades):
    """Win rate by signal score (3, 4, 5)."""
    buckets = defaultdict(list)
    for t in trades:
        score = t.get("score")
        if score is not None and classify(t) != "OPEN":
            buckets[score].append(t)

    results = {}
    for score in sorted(buckets.keys()):
        ts   = buckets[score]
        wins = [t for t in ts if classify(t) == "WIN"]
        results[score] = {
            "trades":   len(ts),
            "win_rate": round(len(wins) / len(ts) * 100, 1),
        }
    return results


def monthly_pnl(trades):
    """Net P&L grouped by month."""
    buckets = defaultdict(float)
    for t in trades:
        pnl = t.get("realized_pnl_usd")
        if pnl is None:
            continue
        month = t.get("timestamp_sgt", "????-??")[:7]
        buckets[month] += pnl
    return {m: round(v, 2) for m, v in sorted(buckets.items())}


# ─────────────────────────────────────────────────────────────
# Display
# ─────────────────────────────────────────────────────────────

SEP  = "─" * 50
SEP2 = "═" * 50

def bar(value, max_val, width=20, fill="█", empty="░"):
    if max_val == 0:
        return empty * width
    filled = int(round(value / max_val * width))
    return fill * filled + empty * (width - filled)


def print_report(trades, label="ALL TIME"):
    stats, open_trades = overall_stats(trades)

    print(f"\n{SEP2}")
    print("  📊  CPR GOLD BOT — PERFORMANCE REPORT")
    print(f"  Period: {label}")
    print(SEP2)

    if not stats:
        print("\n  ⚠️  No closed trades found yet.")
        if open_trades:
            print(f"  {len(open_trades)} trade(s) currently open / pending.")
        print("\n  Run the bot and collect some trades first!\n")
        return

    # ── Overall ──────────────────────────────────────────────
    print(f"\n  📈  OVERALL  ({stats['first_trade']} → {stats['last_trade']})")
    print(SEP)
    print(f"  Total trades    : {stats['total_trades']}  "
          f"({stats['wins']}W / {stats['losses']}L"
          + (f" / {stats['open']}open)" if stats['open'] else ")"))
    print(f"  Win rate        : {stats['win_rate']}%")
    print(f"  Profit factor   : {stats['profit_factor']}")
    print(f"  Net P&L         : ${stats['net_pnl']:+.2f}  "
          f"(Gross profit ${stats['gross_profit']:.2f} | Loss ${stats['gross_loss']:.2f})")
    if stats['avg_r']:
        print(f"  Avg R           : {stats['avg_r']}R")
    print(f"  Max win streak  : {stats['max_win_streak']}")
    print(f"  Max loss streak : {stats['max_loss_streak']}")

    # ── Session breakdown ────────────────────────────────────
    sess = session_stats(trades)
    if sess:
        print("\n  🌍  BY SESSION")
        print(SEP)
        best  = max(sess, key=lambda s: sess[s]["win_rate"])
        worst = min(sess, key=lambda s: sess[s]["win_rate"])
        max_wr = max(v["win_rate"] for v in sess.values())

        for name, s in sess.items():
            tag = "  ← BEST " if name == best else ("  ← WORST" if name == worst else "")
            b   = bar(s["win_rate"], max_wr)
            r_str = f"  avg {s['avg_r']}R" if s['avg_r'] else ""
            print(f"  {name:<16} {b}  {s['win_rate']:>5.1f}%  "
                  f"({s['trades']} trades, ${s['net_pnl']:+.2f}){r_str}{tag}")

        print(f"\n  Best session  : {best}")
        print(f"  Worst session : {worst}")

    # ── Setup breakdown ──────────────────────────────────────
    setups = setup_stats(trades)
    if setups:
        print("\n  🎯  BY SETUP")
        print(SEP)
        max_wr = max(v["win_rate"] for v in setups.values()) if setups else 1
        for name, s in setups.items():
            b = bar(s["win_rate"], max_wr)
            print(f"  {name:<26} {b}  {s['win_rate']:>5.1f}%  "
                  f"({s['trades']} trades, ${s['net_pnl']:+.2f})")

    # ── Score breakdown ──────────────────────────────────────
    scores = score_stats(trades)
    if scores:
        print("\n  🔢  BY SIGNAL SCORE")
        print(SEP)
        max_wr = max(v["win_rate"] for v in scores.values()) if scores else 1
        for score, s in scores.items():
            b = bar(s["win_rate"], max_wr)
            print(f"  Score {score}   {b}  {s['win_rate']:>5.1f}%  ({s['trades']} trades)")

    # ── Monthly P&L ──────────────────────────────────────────
    monthly = monthly_pnl(trades)
    if len(monthly) > 1:
        print("\n  📅  MONTHLY P&L")
        print(SEP)
        max_abs = max(abs(v) for v in monthly.values()) or 1
        for month, pnl in monthly.items():
            b    = bar(abs(pnl), max_abs, fill="█" if pnl >= 0 else "▒")
            print(f"  {month}   {b}  ${pnl:+.2f}")

    # ── Verdict ──────────────────────────────────────────────
    print(f"\n{SEP2}")
    print("  🩺  VERDICT")
    print(SEP)
    pf   = stats["profit_factor"]
    wr   = stats["win_rate"]
    n    = stats["total_trades"]
    mls  = stats["max_loss_streak"]

    if n < 30:
        print(f"  ⚠️  Sample too small ({n} trades). Need 50–100 for reliable conclusions.")
    else:
        if pf >= 1.3 and wr >= 48:
            print(f"  ✅  System looks healthy (PF {pf}, WR {wr}%). Keep running.")
        elif pf >= 1.0:
            print(f"  🟡  Marginal edge (PF {pf}, WR {wr}%). Watch for improvement.")
        else:
            print(f"  🔴  Negative expectancy (PF {pf}). Review signal logic before live.")

    if mls >= 6:
        print(f"  ⚠️  Max losing streak is {mls} — check drawdown rules.")
    elif mls >= 4:
        print(f"  ℹ️  Max losing streak: {mls} — within normal range.")

    if sess:
        worst_wr = sess[worst]["win_rate"]
        if worst_wr < 40 and sess[worst]["trades"] >= 10:
            print(f"  💡  Consider disabling {worst} session (WR {worst_wr}% over "
                  f"{sess[worst]['trades']} trades).")

    print(SEP2)
    print()


# ─────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    include_failed = "--all"   in sys.argv
    last_days      = None

    if "--last" in sys.argv:
        idx = sys.argv.index("--last")
        try:
            last_days = int(sys.argv[idx + 1])
        except (IndexError, ValueError):
            print("Usage: python analyze_trades.py --last <days>")
            sys.exit(1)

    trades = load_trades(include_failed=include_failed, last_days=last_days)

    if not trades:
        print("\n⚠️  No trades found.")
        print(f"   Expected file: {HISTORY_FILE.resolve()}")
        print("   Make sure you run this from the same folder as trade_history.json\n")
        sys.exit(0)

    label = f"LAST {last_days} DAYS" if last_days else "ALL TIME"
    print_report(trades, label=label)
