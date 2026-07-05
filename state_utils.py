from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

import pytz

# DATA_DIR is the single source of truth — defined in config_loader.py.
# Importing here avoids the duplicate Path(os.environ.get(...)) definition
# that previously existed in both modules.
from config_loader import DATA_DIR

logger = logging.getLogger(__name__)

SG_TZ = pytz.timezone('Asia/Singapore')

CALENDAR_CACHE_FILE = DATA_DIR / 'calendar_cache.json'
SCORE_CACHE_FILE    = DATA_DIR / 'signal_cache.json'
OPS_STATE_FILE      = DATA_DIR / 'ops_state.json'
TRADE_HISTORY_FILE  = DATA_DIR / 'trade_history.json'
RUNTIME_STATE_FILE  = DATA_DIR / 'runtime_state.json'
# Removed: TRADE_HISTORY_ARCHIVE_FILE — archival removed; 90-day rolling window is sufficient
# Removed: LAST_TRADE_CANDLE_FILE     — never used anywhere in the codebase


def load_json(path: Path, default: Any):
    try:
        if path.exists():
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(default, dict) and not isinstance(data, dict):
                    return default.copy()
                if isinstance(default, list) and not isinstance(data, list):
                    return default.copy()
                return data
    except Exception as exc:
        logger.warning('Failed to load %s: %s', path, exc)
    return default.copy() if isinstance(default, (dict, list)) else default


def save_json(path: Path, data: Any):
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile('w', delete=False, dir=str(path.parent), encoding='utf-8') as tmp:
            json.dump(data, tmp, indent=2)
            temp_name = tmp.name
        os.replace(temp_name, path)
    except Exception as exc:
        logger.warning('Failed to save %s: %s', path, exc)


def update_runtime_state(**kwargs) -> None:
    state = load_json(RUNTIME_STATE_FILE, {})
    if not isinstance(state, dict):
        state = {}
    state.update(kwargs)
    state['updated_at_sgt'] = datetime.now(SG_TZ).strftime('%Y-%m-%d %H:%M:%S')
    save_json(RUNTIME_STATE_FILE, state)


def parse_sgt_timestamp(value: str | None) -> datetime | None:
    """Parse a SGT timestamp string into a timezone-aware datetime.

    Accepts both '%Y-%m-%d %H:%M:%S' and ISO '%Y-%m-%dT%H:%M:%S' formats.
    Returns None if value is falsy or unparseable.

    Canonical implementation — imported by bot.py and calendar_fetcher.py
    so the logic lives in exactly one place.
    """
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return SG_TZ.localize(datetime.strptime(value, fmt))
        except Exception:
            pass
    return None
