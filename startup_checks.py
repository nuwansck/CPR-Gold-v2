from __future__ import annotations

from pathlib import Path

from config_loader import DATA_DIR, SETTINGS_FILE, load_secrets, load_settings
from state_utils import CALENDAR_CACHE_FILE


def run_startup_checks() -> list[str]:
    settings = load_settings()
    secrets = load_secrets()
    warnings: list[str] = []

    if not Path(DATA_DIR).exists():
        warnings.append(f'DATA_DIR missing: {DATA_DIR}')
    if not Path(SETTINGS_FILE).exists():
        warnings.append(f'settings file missing: {SETTINGS_FILE}')
    if not secrets.get('OANDA_ACCOUNT_ID'):
        warnings.append('OANDA_ACCOUNT_ID not set; broker calls will fail until configured')
    if not secrets.get('OANDA_API_KEY'):
        warnings.append('OANDA_API_KEY not set; broker calls will fail until configured')
    if not secrets.get('TELEGRAM_TOKEN') or not secrets.get('TELEGRAM_CHAT_ID'):
        warnings.append('Telegram not fully configured; alerts will be skipped')
    if int(settings.get('cycle_minutes', 5)) <= 0:
        warnings.append('cycle_minutes must be > 0')
    margin_safety = float(settings.get('margin_safety_factor', 0.6))
    if not 0 < margin_safety <= 1:
        warnings.append('margin_safety_factor must be between 0 and 1')
    retry_safety = float(settings.get('margin_retry_safety_factor', 0.4))
    if not 0 < retry_safety <= 1:
        warnings.append('margin_retry_safety_factor must be between 0 and 1')
    if retry_safety > margin_safety:
        warnings.append('margin_retry_safety_factor should not exceed margin_safety_factor')

    xau_margin_override = float(settings.get('xau_margin_rate_override', 0.20) or 0.20)
    if not 0.05 <= xau_margin_override <= 1:
        warnings.append('xau_margin_rate_override must be between 0.05 and 1.00')

    # L-04 fix: warn if the news filter has no calendar data yet
    if not CALENDAR_CACHE_FILE.exists():
        warnings.append(
            'calendar_cache.json not found — news filter will pass all trades until '
            'the first successful calendar fetch completes. This resolves automatically '
            'on the first bot cycle.'
        )

    return warnings
