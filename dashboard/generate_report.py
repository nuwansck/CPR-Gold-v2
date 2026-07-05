"""Generate CSV analytics from Rogue-H1 signal_log.csv.

Railway usage:
  python dashboard/generate_report.py

Defaults:
  input:  /data/signal_log.csv
  output: /data/dashboard/

No pandas dependency; uses Python stdlib only.
"""
from __future__ import annotations

import csv
import os
from collections import defaultdict
from datetime import datetime
from pathlib import Path

DATA_DIR = Path(os.getenv("DATA_DIR", "/data"))
INPUT = Path(os.getenv("SIGNAL_LOG_PATH", str(DATA_DIR / "signal_log.csv")))
OUT_DIR = Path(os.getenv("DASHBOARD_OUTPUT_DIR", str(DATA_DIR / "dashboard")))


def _to_float(v, default=0.0):
    try:
        if v in (None, ""):
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def _read_rows():
    if not INPUT.exists():
        raise FileNotFoundError(f"Signal log not found: {INPUT}")
    with open(INPUT, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _write(name: str, fieldnames: list[str], rows: list[dict]):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / name
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return path


def _date(row):
    ts = row.get("timestamp_sgt", "")
    return ts[:10] if len(ts) >= 10 else "UNKNOWN"


def _r_multiple(row):
    pnl = _to_float(row.get("pl_usd"), 0.0)
    risk = _to_float(row.get("position_usd"), 0.0)
    if risk <= 0 or not row.get("outcome"):
        return 0.0
    return pnl / risk


def _summarize(rows, key_fn):
    groups = defaultdict(list)
    for r in rows:
        groups[key_fn(r)].append(r)
    out = []
    for key, items in sorted(groups.items(), key=lambda x: str(x[0])):
        fired = [r for r in items if r.get("action") == "FIRED"]
        closed = [r for r in fired if r.get("outcome")]
        wins = [r for r in closed if _to_float(r.get("pl_usd")) > 0]
        losses = [r for r in closed if _to_float(r.get("pl_usd")) < 0]
        net = sum(_to_float(r.get("pl_usd")) for r in closed)
        net_r = sum(_r_multiple(r) for r in closed)
        out.append({
            "group": key,
            "signals": len(items),
            "trades": len(fired),
            "closed_trades": len(closed),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate_pct": round((len(wins) / len(closed) * 100), 2) if closed else "",
            "net_pnl": round(net, 2),
            "net_r": round(net_r, 3),
            "avg_r": round(net_r / len(closed), 3) if closed else "",
        })
    return out


def generate():
    rows = _read_rows()

    summary_fields = ["group", "signals", "trades", "closed_trades", "wins", "losses", "win_rate_pct", "net_pnl", "net_r", "avg_r"]
    paths = []
    paths.append(_write("daily_summary.csv", summary_fields, _summarize(rows, _date)))
    paths.append(_write("score_summary.csv", summary_fields, _summarize(rows, lambda r: r.get("score") or "NONE")))
    paths.append(_write("session_summary.csv", summary_fields, _summarize(rows, lambda r: r.get("session") or "UNKNOWN")))

    block_counts = defaultdict(int)
    for r in rows:
        action = r.get("action") or ""
        if action.startswith("BLOCKED") or action.startswith("SKIPPED") or action == "NOISE":
            block_counts[action] += 1
    block_rows = [{"action": k, "count": v} for k, v in sorted(block_counts.items(), key=lambda x: (-x[1], x[0]))]
    paths.append(_write("block_reason_summary.csv", ["action", "count"], block_rows))

    equity = []
    curve = 0.0
    peak = 0.0
    for r in rows:
        if r.get("action") == "FIRED" and r.get("outcome"):
            curve += _to_float(r.get("pl_usd"), 0.0)
            peak = max(peak, curve)
            equity.append({
                "timestamp_sgt": r.get("timestamp_sgt", ""),
                "trade_id": r.get("trade_id", ""),
                "outcome": r.get("outcome", ""),
                "pl_usd": r.get("pl_usd", ""),
                "cum_pnl": round(curve, 2),
                "drawdown": round(curve - peak, 2),
                "score": r.get("score", ""),
                "session": r.get("session", ""),
            })
    paths.append(_write("equity_curve.csv", ["timestamp_sgt", "trade_id", "outcome", "pl_usd", "cum_pnl", "drawdown", "score", "session"], equity))

    manifest = [{"generated_at_sgt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "input": str(INPUT), "output": str(p)} for p in paths]
    _write("manifest.csv", ["generated_at_sgt", "input", "output"], manifest)
    return paths


if __name__ == "__main__":
    for p in generate():
        print(p)
