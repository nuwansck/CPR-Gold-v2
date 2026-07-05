# CPR Gold Bot v2.2 — Design and Operations Document

## 1. Executive Summary

CPR Gold Bot v2.0 is a Railway-ready automated trading bot for XAU/USD. It uses an M15 CPR breakout strategy, an H1+H4 EMA50 dual trend filter, ATR-based SL/TP, fixed-dollar risk sizing, a daily auto-tuner, Telegram state-change alerts, and CSV signal journaling.

## 2. Strategy Specification

| Item | Setting |
|---|---|
| Instrument | XAU/USD |
| Timeframe | M15 |
| Trend filter | H1 EMA50 + H4 EMA50 (dual, with H4 buffer) |
| Entry | CPR breakout, score-gated |
| Minimum score | 4 (Asian 5) |
| SL | ATR-based, 1.0× ATR, clamped $15–$17 |
| TP | RR multiple, 2.0× |
| Max RR | 2.0 |
| Risk model | Fixed-dollar: $100 (score ≥5) / $66 (score 4) |

## 3. Risk Logic

SL, TP, and RR checks are centralized in `bot.py`; `signals.py` scores the setup only. Risk is a fixed dollar amount per score and does not scale with balance — the live balance is used only for the margin check. Units = `position_usd / final ATR SL distance`.

## 4. Capital Preservation

- Win cap: 1 win/session, then sit out.
- Loss caps: 3/day, 2/session.
- Direction and post-win cooldowns; minimum re-entry wait.
- Calendar hard lock: 30 minutes before/after high-impact USD news. Fail-closed: a missing/unreadable calendar blocks new entries until the first successful fetch (`news_fail_closed: true`).

## 5. Sessions (SGT)

| Session | Hours | Cap | Threshold |
|---|---|---|---|
| Asian | 08:00–15:59 | 3 | ≥5 |
| London | 16:00–20:59 | 10 | ≥4 |
| US | 21:00–01:59 | 10 | ≥4 |

## 6. Infrastructure

5-minute cycle, Railway container deployment, persistent settings on the `/data` volume, SQLite history with 90-day rolling retention, a daily auto-tuner, and scheduled Telegram performance reports (daily, session, weekly, monthly).
