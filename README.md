# CPR Gold Bot v2.0 — XAU/USD CPR Breakout Bot

CPR Gold Bot is a Railway-ready automated trading bot for XAU/USD. It uses an M15 CPR breakout strategy with an H1+H4 EMA50 dual trend filter, ATR-based SL/TP, fixed-dollar risk sizing, a daily auto-tuner, Telegram alerts, and CSV signal journaling.

## Current Version

**v2.0** — Clean consolidated baseline.

## Strategy Summary

| Item | Value |
|---|---|
| Instrument | XAU/USD |
| Execution timeframe | M15 |
| Trend filter | H1 EMA50 + H4 EMA50 (dual) |
| Entry model | CPR breakout |
| Minimum score | 4/6 (London/US ≥4, Asian ≥5) |
| SL model | ATR-based (1.0× ATR, clamped $15–$17) |
| TP model | RR multiple (2.0×) |
| Risk model | Fixed-dollar: $100 (score ≥5) / $66 (score 4) |
| Break-even | Enabled — SL→entry+spread+$0.2 buffer at 1.2R (v2.1) |
| Runtime | Railway container, 5-minute cycle |

## Risk & Sizing

Risk is a fixed dollar amount keyed to score — **$100** for score ≥ 5 and **$66** for score 4 — and does not scale with balance (`account_balance_override: 0`; the live balance is used only for the margin check). Units = `position_usd / final ATR SL distance`. On a $5,000 account, $100 = 2.0% and $66 = 1.32%.

## Signal Flow

1. Fetch the latest completed M15 candle.
2. Calculate CPR levels, ATR, and H1/H4 EMA50.
3. Score the CPR breakout setup (max 6).
4. Apply the dual trend filter, session, news, spread, and cooldown guards.
5. Calculate final SL/TP/RR centrally in `bot.py`.
6. Check all caps (win cap, daily/session loss caps, concurrent-trade cap).
7. Place the trade through OANDA if all checks pass.
8. Send a Telegram alert and write a CSV journal row.
9. Backfill the final outcome when the trade closes.

## Guards & Capital Preservation

- Win cap: 1 win per session, then sit out the rest of that session.
- Loss caps: 3 losses/day, 2 losses/session.
- Direction cooldown after consecutive SLs, post-win cooldown, and a minimum re-entry wait.
- Calendar hard lock: no entries within 30 minutes before/after high-impact USD news. Fail-closed (`news_fail_closed: true`): if the calendar cache is missing/unreadable, new entries are blocked until the first successful fetch (matches Rogue-H1).
- Daily auto-tuner reviews rolling history and adjusts parameters within safe bounds.

## Sessions (SGT)

| Session | Hours | Cap | Score |
|---|---|---|---|
| Dead zone | — | — | — |
| Asian | 08:00–15:59 | 3 | ≥5 |
| London | 16:00–20:59 | 10 | ≥4 |
| US | 21:00–01:59 | 10 | ≥4 |

## Railway Files

| File | Purpose |
|---|---|
| `Procfile` | Railway start command |
| `railway.json` | Railway deployment config |
| `requirements.txt` | Python dependencies |
| `settings.json` | Runtime strategy settings |
| `settings.json.example` | Safe reference config |

## Persistent Data (`/data` volume)

| File | Purpose |
|---|---|
| `/data/settings.json` | Runtime settings (synced from bundled defaults) |
| `/data/runtime_state.json` | Cooldown, win/loss cap, and open-trade state |
| `/data/trade_history.json` | Trade records with PnL backfill |
| `/data/signal_log.csv` | Per-cycle signal journal |
| `/data/calendar_cache.json` | Economic calendar cache |
