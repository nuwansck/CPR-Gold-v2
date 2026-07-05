"""config_loader.py — Settings authority for CPR Gold Bot v2.0

Single source of truth for all setting defaults (DEFAULTS dict).
Both bot.py and auto_tuner.py import apply_defaults() and save_settings()
from here so no defaults can drift between files.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("DATA_DIR", "/data")).resolve()
DATA_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_SETTINGS_PATH = BASE_DIR / "settings.json"
SETTINGS_FILE         = DATA_DIR / "settings.json"
SECRETS_JSON_PATH     = BASE_DIR / "secrets.json"


# ── Single source of truth for all setting defaults ────────────────────────────
# Keys defined here → injected by apply_defaults(), load_settings(), and
# ensure_persistent_settings(). No other file should call settings.setdefault()
# for these keys.
DEFAULTS: dict = {
    # Identity
    "bot_name":                    "CPR Gold Bot v2.0",
    "version":                     "1.1",
    "instrument":                  "XAU_USD",
    "instrument_display":          "XAU/USD",
    "timeframe":                   "M15",
    "demo_mode":                   True,
    "trade_gold":                  True,
    "enabled":                     True,
    "cycle_minutes":               5,
    # Signal
    "signal_threshold":            4,
    "position_full_usd":           100,
    "position_partial_usd":        66,
    "account_balance_override":    0,
    # SL / TP / RR
    "sl_mode":                     "atr_based",
    "tp_mode":                     "rr_multiple",
    "rr_ratio":                    2.0,
    "max_rr_ratio":                3.0,
    "atr_sl_multiplier":           1.0,
    "sl_min_atr_mult":             0.8,
    "sl_min_usd":                  15.0,
    "sl_max_usd":                  17.0,
    "fixed_sl_usd":                20.0,
    "fixed_tp_usd":                None,
    "sl_pct":                      0.0025,
    "tp_pct":                      0.0075,
    "trailing_stop_atr_mult":      0,       # 0 = disabled; default in execution code was 0.5 — explicit 0 prevents silent activation
    # Breakeven (v2.1 — enabled, Rogue-aligned semantics)
    "breakeven_enabled":               True,
    "breakeven_trigger_r":             1.2,
    "breakeven_trigger_usd":           10.0,
    "breakeven_include_spread":        True,
    "breakeven_spread_adjust":         True,
    "breakeven_profit_buffer_usd":     0.2,
    "breakeven_partial_close_enabled": False,
    # Daily equity loss cap (v2.1 #1)
    "daily_equity_loss_cap_enabled":   True,
    "daily_equity_loss_cap_percent":   10.0,
    # Signal journal + dashboard (v2.1 #3)
    "signal_logging_enabled":          True,
    "signal_log_min_score":            4,
    "dashboard_enabled":               True,
    "dashboard_output_dir":            "/data/dashboard",
    # Trend filters
    "h1_trend_filter_enabled":     True,
    "h1_ema_period":               50,
    "h4_trend_filter_enabled":     True,
    "h4_ema_period":               50,
    "h4_ema_buffer_pct":           0.15,
    "require_candle_close":        True,
    "exhaustion_atr_mult":         2.5,
    # Margin / sizing
    "margin_safety_factor":        0.75,
    "margin_retry_safety_factor":  0.4,
    "xau_margin_rate_override":    0.05,
    "auto_scale_on_margin_reject": True,
    "telegram_show_margin":        True,
    # Sessions
    "session_only":                True,
    "session_thresholds":          {"Asian": 5, "London": 4, "US": 4},
    "spread_limits":               {"London": 140, "US": 140, "Asian": 120},
    "max_spread_pips":             160,
    "asian_session_enabled":       True,
    "london_session_enabled":      True,
    "us_session_enabled":          True,
    "session_start_hour_sgt":      16,
    "session_end_hour_sgt":        1,
    "trading_day_start_hour_sgt":  8,
    "midnight_guard_min":          0,
    # Trade caps
    "max_trades_day":              20,
    "max_wins_day":                1,
    "max_losing_trades_day":       3,
    "max_losing_trades_session":   2,
    "max_concurrent_trades":       1,
    "max_trades_london":           10,
    "max_trades_us":               10,
    "max_trades_asian":            3,
    # Cooldowns / guards
    "loss_streak_cooldown_min":    60,
    "consecutive_sl_guard":        2,
    "sl_direction_cooldown_min":   180,
    "min_reentry_wait_min":        10,      # global post-SL cooldown (any setup)
    "same_setup_cooldown_min":     10,      # same-setup-name re-entry cooldown
    "post_win_candle_block":       True,
    "post_win_cooldown_hours":     6,
    # News
    "news_filter_enabled":         True,
    "news_block_before_min":       30,
    "news_block_after_min":        30,
    "news_fail_closed":             True,
    "news_lookahead_min":          120,
    "news_medium_penalty_score":   -1,
    # Calendar / reporting / infrastructure
    "friday_cutoff_hour_sgt":      23,
    "friday_cutoff_minute_sgt":    0,
    "calendar_fetch_interval_min": 60,
    "calendar_retry_after_min":    15,
    "daily_report_hour_sgt":       8,
    "session_report_hour_sgt":     2,
    "session_report_minute_sgt":   0,
    "asian_report_hour_sgt":       16,
    "asian_report_minute_sgt":     5,
    "london_report_hour_sgt":      21,
    "london_report_minute_sgt":    5,
    "us_report_hour_sgt":          1,
    "us_report_minute_sgt":        5,
    "db_retention_days":           90,
    "db_cleanup_hour_sgt":         0,
    "db_cleanup_minute_sgt":       15,
    "db_vacuum_weekly":            True,
}


def apply_defaults(settings: dict) -> dict:
    """Apply DEFAULTS to settings dict in-place using setdefault.

    Call this instead of scattered individual setdefault() calls.
    Single source of truth — if a key is missing here, it is missing everywhere.
    """
    for k, v in DEFAULTS.items():
        settings.setdefault(k, v)
    return settings


# ── Internal helpers ───────────────────────────────────────────────────────────

def _read_json(path: Path, default: Any = None) -> Any:
    try:
        if path.exists():
            with path.open("r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as exc:
        logger.warning("Failed to read %s: %s", path, exc)
    return default


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    os.replace(tmp, path)


# ── Persistent settings management ────────────────────────────────────────────

def ensure_persistent_settings() -> Path:
    """Sync bundled settings.json → DATA_DIR/settings.json.

    On first boot: bootstrap from DEFAULTS merged with bundled settings.json.
    On subsequent boots: inject any NEW keys from DEFAULTS that the persistent
    volume is missing (added in new deployments). Never overwrite existing keys
    — those belong to the auto-tuner or manual edits.

    bot_name is synced on every deploy (version indicator).
    signal_threshold is NOT force-synced — auto-tuner may have raised it.
    Legacy version force-sync removed — version reset to 1.0 baseline.
    """
    bundled = _read_json(DEFAULT_SETTINGS_PATH, {})
    if not isinstance(bundled, dict):
        bundled = {}

    if SETTINGS_FILE.exists():
        persistent = _read_json(SETTINGS_FILE, {})
        if not isinstance(persistent, dict):
            persistent = {}

        # Inject keys missing from persistent volume (new deployments).
        # DEFAULTS is the canonical source; bundled settings.json may override.
        effective_defaults = dict(DEFAULTS)
        effective_defaults.update({k: v for k, v in bundled.items() if k in DEFAULTS})
        changed = {k: v for k, v in effective_defaults.items() if k not in persistent}

        # Always sync bot_name — it's a version indicator, not a tunable.
        bundled_bot_name = bundled.get("bot_name") or DEFAULTS.get("bot_name")
        if bundled_bot_name and persistent.get("bot_name") != bundled_bot_name:
            changed["bot_name"] = bundled_bot_name

        # Always sync version too — also a version indicator, not a tunable.
        # Without this a stale persistent volume keeps its old version string.
        bundled_version = bundled.get("version") or DEFAULTS.get("version")
        if bundled_version and persistent.get("version") != bundled_version:
            changed["version"] = bundled_version

        # v2.2 upgrade: force-overwrite keys whose VALUES changed this release
        # (not just newly-added keys). Runs only when the persistent version
        # differs from the bundled version, so it fires once per upgrade and then
        # leaves these keys alone. These are NOT auto-tuner-owned.
        VERSION_FORCE_SYNC_KEYS = ("breakeven_enabled", "breakeven_trigger_usd")
        if bundled_version and persistent.get("version") != bundled_version:
            for _fk in VERSION_FORCE_SYNC_KEYS:
                if _fk in effective_defaults and persistent.get(_fk) != effective_defaults[_fk]:
                    changed[_fk] = effective_defaults[_fk]

        if changed:
            persistent.update(changed)
            _write_json(SETTINGS_FILE, persistent)
            logger.info(
                "Synced %d key(s) to persistent settings: %s",
                len(changed), list(changed.keys()),
            )
        return SETTINGS_FILE

    # First boot — bootstrap from DEFAULTS, then overlay bundled settings.json
    merged = dict(DEFAULTS)
    merged.update(bundled)
    _write_json(SETTINGS_FILE, merged)
    logger.info("Bootstrapped persistent settings → %s", SETTINGS_FILE)
    return SETTINGS_FILE


# ── Settings cache ─────────────────────────────────────────────────────────────
# Avoids re-reading disk on every 5-minute cycle. Invalidated by mtime change
# so manual edits take effect on the very next cycle without restarting.

_settings_cache: dict  = {}
_settings_mtime: float = 0.0


def load_settings() -> dict:
    global _settings_cache, _settings_mtime
    ensure_persistent_settings()

    try:
        mtime = SETTINGS_FILE.stat().st_mtime
    except OSError:
        mtime = 0.0

    if _settings_cache and mtime == _settings_mtime:
        return _settings_cache

    settings = _read_json(SETTINGS_FILE, {})
    if not isinstance(settings, dict):
        settings = {}

    apply_defaults(settings)   # one call — no scattered setdefault() chains

    _settings_cache = settings
    _settings_mtime = mtime
    return settings


def save_settings(settings: dict) -> None:
    """Write settings to the persistent volume and invalidate the in-memory cache."""
    global _settings_cache, _settings_mtime
    _write_json(SETTINGS_FILE, settings)
    _settings_cache = {}
    _settings_mtime = 0.0
    logger.info("Saved settings → %s", SETTINGS_FILE)


def load_secrets() -> dict:
    """Load secrets with environment variables taking priority over secrets.json."""
    file_secrets: dict = {}
    if SECRETS_JSON_PATH.exists():
        loaded = _read_json(SECRETS_JSON_PATH, {})
        if isinstance(loaded, dict):
            file_secrets = loaded

    return {
        "OANDA_API_KEY":    os.environ.get("OANDA_API_KEY")    or file_secrets.get("OANDA_API_KEY",    ""),
        "OANDA_ACCOUNT_ID": os.environ.get("OANDA_ACCOUNT_ID") or file_secrets.get("OANDA_ACCOUNT_ID", ""),
        "TELEGRAM_TOKEN":   os.environ.get("TELEGRAM_TOKEN")   or file_secrets.get("TELEGRAM_TOKEN",   ""),
        "TELEGRAM_CHAT_ID": os.environ.get("TELEGRAM_CHAT_ID") or file_secrets.get("TELEGRAM_CHAT_ID", ""),
        "DATA_DIR":         str(DATA_DIR),
    }


def get_bool_env(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}
