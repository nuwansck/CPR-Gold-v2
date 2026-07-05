# Changelog

## v2.3 — 2026-07-05 — Force-sync tuned caps onto the volume

Built from the uploaded v2.2 package (caps already edited to 4/2/2/1). Strategy
unchanged. This release makes those caps actually apply on Railway.

Problem: config_loader only injects MISSING keys and never overwrites existing
volume values, so the hand-edited cap block was ignored on deploy — the volume
kept 20/10/10/3 (visible on the startup card as London 10 / US 10 / Asian 3).

Fix:
- Added max_trades_day, max_wins_day, max_trades_london/us/asian to
  VERSION_FORCE_SYNC_KEYS (version-gated, one-time overwrite on upgrade).
- Updated DEFAULTS to 4 / 2 / 2 / 1 and bumped version 2.2 → 2.3 so the gate fires.
- Auto-tuner keys (signal_threshold, rr_ratio, atr_sl_multiplier, cooldowns) are
  NOT in the set and are preserved.

Effective caps after deploy: day 4, wins 1/session, London 2 / US 2 / Asian 1,
loss caps 3/day & 2/session, 10% equity cap, 6h post-win cooldown (all unchanged).
Startup card should now read LONDON cap 2 / US cap 2 / ASIAN cap 1.


# Changelog

## v2.2 — 2026-07-05 — Startup visibility + version roll-up

Strategy unchanged. Operational/visibility update on top of v2.1.1.

- **Startup Telegram card** now shows protection status so config drift is
  visible on boot:
  `Break-even: ✅ ON (1.2R)  |  Equity cap: ✅ 10%/day` and `Journal: ✅ ON`.
  `msg_startup` gained `breakeven_enabled`, `breakeven_trigger_r`,
  `daily_equity_cap_enabled`, `daily_equity_cap_percent`, `signal_logging_enabled`
  (all wired from settings in scheduler.py).
- Version rolled to 2.2 across code, settings, and docs. The version-gated
  force-sync (breakeven_enabled / breakeven_trigger_usd) re-arms on the
  2.1.1 → 2.2 change; it is a no-op if those values are already correct.
- README / CONFLUENCE updated to reflect enabled break-even, daily equity cap,
  and signal journal.


# Changelog

## v2.1.1 — 2026-07-05 — Hotfix: force-enable breakeven on upgrade

The v2.1 boot on Railway synced all NEW keys but could not flip two PRE-EXISTING
keys, because config_loader only injects missing keys and never overwrites
existing ones (to protect auto-tuner state). Result: on a volume upgraded from
v2.0, `breakeven_enabled` stayed `false` and `breakeven_trigger_usd` stayed
`20.0` — so breakeven was silently OFF despite the package being correct.

Fix:
- Added a version-gated `VERSION_FORCE_SYNC_KEYS` overwrite in
  `ensure_persistent_settings()` for `breakeven_enabled` and
  `breakeven_trigger_usd`. It fires once when the persistent version differs
  from the bundled version, then leaves the keys alone. Auto-tuner-owned keys
  (e.g. `signal_threshold`) are NOT touched.
- Bumped version to 2.1.1 so the gate re-triggers (the first v2.1 boot had
  already written `version: 2.1` to the volume).

Verified by simulating an upgraded volume: breakeven_enabled false→true,
trigger 20→10, signal_threshold preserved.


# Changelog

## v2.1 — 2026-07-05 — Operational parity with Rogue-H1 (strategy unchanged)

Strategy logic (M15 CPR breakout, dual H1+H4 EMA50 filter, scoring, thresholds,
sessions, SL/TP model) is **unchanged**. This release only adds risk-management,
safety and observability features so CPR and Rogue-H1 differ by strategy alone.

Added / changed:
- **Daily equity loss cap (#1):** new `daily_equity_loss_cap_enabled` (true) /
  `daily_equity_loss_cap_percent` (10%). Blocks new entries once the day's
  realised+unrealised P&L reaches −10% of effective balance; resets next trading day.
- **Break-even (#2):** enabled and aligned to Rogue-H1 semantics — moves SL to
  entry + spread + `breakeven_profit_buffer_usd` ($0.2) once profit ≥
  `breakeven_trigger_r` (1.2R). Partial-close available but off by default.
  Replaces the old (disabled) partial-close-at-1R behaviour.
- **Signal journal + dashboard (#3):** ported `signal_logger.py` and
  `dashboard/generate_report.py`. Logs FIRED trades and back-fills TP/SL/BE
  outcomes to `/data/signal_log.csv`; equity-cap blocks are logged too.
  Enabled via `signal_logging_enabled` (true), `signal_log_min_score` (4).
- **ATR-unavailable hard block (#4a):** if ATR is unavailable, the signal is now
  hard-blocked (previously the exhaustion check was silently skipped and the
  trade could still fire on a degraded ATR-based SL).
- **Bug fix (pre-existing):** `msg_daily_cap` was called with kwargs
  (`day_start_sgt`/`day_end_sgt`/`day_reset_sgt`) the template never accepted,
  which would raise a TypeError the moment the daily loss cap fired. Fixed to
  use `reset_time_sgt`.

Not changed (deliberately, to keep the A/B clean):
- CPR-width hard block and the tightened moderate CPR-width band remain
  Rogue-only. These change which trades are taken and would blur the M15-vs-H1
  comparison; revisit only after demo data.


# CPR Gold Bot v2.0 — Changelog

## v2.0 — Baseline

Clean consolidated baseline. CPR Gold Bot is an XAU/USD (M15) CPR breakout bot with an H1+H4 EMA50 dual trend filter, fixed-dollar risk sizing, ATR-based SL/TP, session/news/spread/cooldown guards, an auto-tuner, CSV analytics, and Telegram alerts.

Risk & sizing:
- Fixed-dollar risk keyed to score: $100 (score ≥ 5) and $66 (score 4). Risk does not scale with balance; the live balance is used only for the margin check.
- RR 2.0, `max_rr_ratio` 2.0. ATR-based SL (1.0× ATR, clamped $15–$17).

Strategy:
- M15 CPR breakout, H1 EMA50 + H4 EMA50 dual trend filter, R2/S2 exhaustion guard.
- Entry threshold 4; sessions Asian/London/US (SGT) with per-session thresholds and caps.

News safety:
- Fail-closed news filter (`news_fail_closed: true`): if the economic-calendar cache is missing or unreadable, new entries are blocked until the first successful fetch, instead of trading through. Matches Rogue-H1. Reflected in the startup Telegram card and the startup calendar warning.

Guards & protection:
- Win cap (1 win/session), loss caps (3/day, 2/session), direction cooldown, post-win cooldown, min re-entry wait, 30/30-minute calendar hard lock (fail-closed).

Infrastructure:
- 5-minute cycle, Railway deployment, persistent settings on `/data` volume, SQLite history with 90-day rolling retention, daily auto-tuner, Telegram alerts and scheduled performance reports.
