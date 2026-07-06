# Changelog

## v2.6 — 2026-07-06 — Fix reported RR + actual-risk logging (data integrity)

No strategy or execution change — trades are placed exactly as before. Fixes two
data-integrity bugs surfaced by the first live trade, so signal_log.csv / trade
records are accurate for analysis.

- **derive_rr_ratio** returned the signal engine's fixed-pct *recommendation*
  ratio (e.g. 3.0 = 0.75%/0.25%) instead of the ACTUAL placed reward:risk
  (tp_usd/sl_usd, e.g. 2.0). Now computed from the real SL/TP. The RR gate and
  the logged/CSV RR now reflect the order actually placed. (CPR min_rr=max_rr=2.0,
  so no trading behavior changes — the placed RR was always 2.0; only the
  reported number was wrong.)
- **estimated_risk_usd** logged the *intended* $100 even when margin protection
  down-scaled the position (e.g. 6.6→4.7 units → ~$70 real risk). Now logs the
  actual risk = units × sl_usd, so risk and reward in the record are consistent.
- `levels['rr_ratio']` in the trade record is now set to the actual placed RR
  (was showing the stale 3.0 recommendation).

NOTE (operational, not a code issue): at simulated gold ~$4,183 on a $5.3k
account, a full $100-risk position needs ~$3.9k margin, so margin protection
down-scales it (real risk ~$70) and hits CPR (tight SL, more units) harder than
Rogue (wider SL, fewer units). To restore the $100 risk model and equalise the
A/B, raise the demo account balance (~$25–50k). This is an OANDA-side change.

# Changelog

## v2.5 — 2026-07-05 — Bundle-wins-on-version-bump (settings sync, fixed for good)

No strategy or settings-value changes. Fixes the recurring "I edited a setting
but it didn't apply" problem permanently.

- Replaced the per-key VERSION_FORCE_SYNC_KEYS allow-list with a general rule:
  on ANY version bump, the bundled settings.json overwrites the /data volume for
  ALL keys EXCEPT an explicit auto-tuner protect-list (signal_threshold,
  rr_ratio, atr_sl_multiplier, sl_direction_cooldown_min, loss_streak_cooldown_min,
  consecutive_sl_guard). Those keep the tuner's learning across deploys.
- Workflow from now on: edit any setting → bump the version → redeploy → it applies.
  No more adding keys to a force-sync list.
- Verified by simulation: an arbitrary edited key applies on version bump; a
  tuner-owned key on the volume is preserved.


# Changelog

## v2.4 — 2026-07-05 — Same-setup cooldown 10→30 (anti-churn)

Strategy unchanged. Raises `same_setup_cooldown_min` from 10 to 30 minutes
(2 M15 candles) so CPR doesn't immediately re-take the same level after a
stop-out during a chop patch. Width hard-block intentionally NOT added — that
stays a CPR-vs-Rogue difference.

Fix: added `same_setup_cooldown_min` to VERSION_FORCE_SYNC_KEYS + bumped 2.3→2.4
so the new value force-syncs onto the /data volume (a plain settings.json edit
would have been ignored, same as the earlier cap issue).


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
