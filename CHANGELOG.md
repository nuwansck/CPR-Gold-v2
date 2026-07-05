# CPR Gold Bot v2.0 — Changelog

## v2.0 — Baseline

Clean consolidated baseline. CPR Gold Bot is an XAU/USD (M15) CPR breakout bot with an H1+H4 EMA50 dual trend filter, fixed-dollar risk sizing, ATR-based SL/TP, session/news/spread/cooldown guards, an auto-tuner, CSV analytics, and Telegram alerts.

Risk & sizing:
- Fixed-dollar risk keyed to score: $100 (score ≥ 5) and $66 (score 4). Risk does not scale with balance; the live balance is used only for the margin check.
- RR 2.0, `max_rr_ratio` 2.0. ATR-based SL (1.0× ATR, clamped $15–$17).

Strategy:
- M15 CPR breakout, H1 EMA50 + H4 EMA50 dual trend filter, R2/S2 exhaustion guard.
- Entry threshold 4; sessions Asian/London/US (SGT) with per-session thresholds and caps.

Guards & protection:
- Win cap (1 win/session), loss caps (3/day, 2/session), direction cooldown, post-win cooldown, min re-entry wait, 30/30-minute calendar hard lock (fail-closed).

Infrastructure:
- 5-minute cycle, Railway deployment, persistent settings on `/data` volume, SQLite history with 90-day rolling retention, daily auto-tuner, Telegram alerts and scheduled performance reports.
