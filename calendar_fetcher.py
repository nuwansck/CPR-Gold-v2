"""
Forex Factory calendar fetcher for the CPR Gold Bot.

Architecture-only improvements:
- Uses /data/runtime_state.json cooldown tracking
- Backs off after HTTP 429 responses
- Avoids noisy warnings for expected next-week 404 responses
- Keeps the existing calendar_cache.json if refresh is skipped or fails

Strategy is unchanged. This only affects how often the news calendar is refreshed.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta

import pytz
import requests

from config_loader import load_settings
from state_utils import CALENDAR_CACHE_FILE, RUNTIME_STATE_FILE, load_json, save_json, parse_sgt_timestamp

log = logging.getLogger(__name__)

SGT = pytz.timezone("Asia/Singapore")
CACHE_PATH = CALENDAR_CACHE_FILE
FF_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
NEXT_WEEK_URL = "https://nfs.faireconomy.media/ff_calendar_nextweek.json"

GOLD_KEYWORDS = [
    "fomc", "fed", "powell", "cpi", "pce",
    "non-farm", "nfp", "unemployment",
    "core cpi", "core pce", "rate decision",
    "interest rate", "monetary policy",
    "gdp", "retail sales", "durable goods",
    "ism", "pmi",
]


def _now_sgt() -> datetime:
    return datetime.now(SGT)


# _parse_sgt — canonical implementation lives in state_utils.parse_sgt_timestamp.
# Alias kept so existing call sites in this file need no change.
_parse_sgt = parse_sgt_timestamp


def _load_runtime_state() -> dict:
    state = load_json(RUNTIME_STATE_FILE, {})
    return state if isinstance(state, dict) else {}


def _save_runtime_state(state: dict) -> None:
    save_json(RUNTIME_STATE_FILE, state)


def _is_gold_relevant(title: str, country: str, impact: str) -> bool:
    if country.upper() != "USD":
        return False
    # FF feed returns 'High', 'Medium', 'Low' (capitalised) or legacy '3'/'red'/'medium-high'
    if impact.lower() not in {"high", "medium", "3", "red", "medium-high"}:
        return False
    title_lower = title.lower()
    return any(kw in title_lower for kw in GOLD_KEYWORDS)


def _date_fmt(date_str: str) -> str:
    """Return the strptime format string that matches date_str, or the FF default."""
    for fmt in ("%m-%d-%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            datetime.strptime(date_str, fmt)
            return fmt
        except ValueError:
            continue
    return "%m-%d-%Y"


def _parse_ff_event(event: dict) -> dict | None:
    """Parse a single Forex Factory event into a normalised calendar entry.

    FF API date field formats seen in the wild:
      New (current): "2026-03-18T14:00:00-04:00"  — ISO 8601 with UTC offset, time field empty
      Legacy:        "03-18-2026"                   — date only, time in separate 'time' field

    Both are handled. The ISO path takes priority because fromisoformat() will
    raise ValueError on legacy date-only strings (no 'T' separator).
    """
    title    = event.get("title", "")
    country  = event.get("country", "")
    impact   = event.get("impact", "")
    date_str = event.get("date", "")
    time_str = event.get("time", "")

    if not _is_gold_relevant(title, country, impact):
        return None

    dt_sgt = None

    # ── PATH A: ISO 8601 datetime with embedded timezone (current FF API) ──
    # Example: "2026-03-18T14:00:00-04:00"
    # fromisoformat() returns a timezone-aware datetime — convert directly to SGT.
    # The time field is empty in this format; the date field carries everything.
    if "T" in date_str:
        try:
            dt_aware = datetime.fromisoformat(date_str)
            dt_sgt   = dt_aware.astimezone(SGT)
            log.debug(
                "calendar_fetcher: [ISO] parsed %r | %s → %s SGT  impact=%r",
                title, date_str, dt_sgt.strftime("%Y-%m-%d %H:%M"), impact,
            )
        except Exception as exc:
            log.warning(
                "calendar_fetcher: skipping relevant event — ISO datetime parse failed | "
                "title=%r  date=%r  error=%s",
                title, date_str, exc,
            )
            return None

    # ── PATH B: Legacy date-only string + separate time field ──────────────
    # Example date: "03-18-2026", time: "2:00pm"
    else:
        et_tz   = pytz.timezone("America/New_York")
        dt_date = None
        for fmt in ("%m-%d-%Y", "%Y-%m-%d", "%d-%m-%Y"):
            try:
                dt_date = datetime.strptime(date_str, fmt)
                break
            except ValueError:
                continue

        if dt_date is None:
            log.warning(
                "calendar_fetcher: skipping relevant event — unrecognised date format | "
                "title=%r  date=%r  time=%r  impact=%r",
                title, date_str, time_str, impact,
            )
            return None

        try:
            if not time_str or time_str.lower() in {"all day", "tentative", ""}:
                dt_naive = dt_date.replace(hour=8, minute=30)
                log.debug(
                    "calendar_fetcher: %r has no specific time (%r) — defaulting to 08:30 ET",
                    title, time_str,
                )
            else:
                # Normalise "2:00pm" → "2:00 PM" for strptime
                time_clean = re.sub(r"([ap]m)", r" \1", time_str, flags=re.IGNORECASE).strip().upper()
                dt_naive   = None
                date_fmt   = _date_fmt(date_str)
                for time_fmt in (f"{date_fmt} %I:%M %p", f"{date_fmt} %H:%M"):
                    try:
                        dt_naive = datetime.strptime(f"{date_str} {time_clean}", time_fmt)
                        break
                    except ValueError:
                        try:
                            dt_naive = datetime.strptime(f"{date_str} {time_str}", f"{date_fmt} %H:%M")
                            break
                        except ValueError:
                            continue
                if dt_naive is None:
                    raise ValueError(f"no matching time format for time_str={time_str!r}")

            dt_et  = et_tz.localize(dt_naive)
            dt_sgt = dt_et.astimezone(SGT)
            log.debug(
                "calendar_fetcher: [legacy] parsed %r | %s ET → %s SGT  impact=%r",
                title, dt_et.strftime("%Y-%m-%d %H:%M"), dt_sgt.strftime("%Y-%m-%d %H:%M"), impact,
            )
        except Exception as exc:
            log.warning(
                "calendar_fetcher: skipping relevant event — time parse failed | "
                "title=%r  date=%r  time=%r  impact=%r  error=%s",
                title, date_str, time_str, impact, exc,
            )
            return None

    return {
        "name":     title,
        "currency": country.upper(),
        "impact":   impact.lower(),   # preserve actual severity: "high" or "medium"
        "time_sgt": dt_sgt.strftime("%Y-%m-%d %H:%M"),
    }


def _fetch_ff_events(url: str, suppress_404: bool = False) -> tuple[list, int | None]:
    try:
        r = requests.get(url, timeout=15, headers={"User-Agent": "CPRGoldBot/1.1"})
        if r.status_code == 200:
            data = r.json()
            events = data if isinstance(data, list) else []
            usd_events = [e for e in events if e.get("country", "").upper() == "USD"]
            impact_values = sorted({str(e.get("impact", "")) for e in usd_events})
            log.info(
                "FF feed OK: %d total events | %d USD | impact values seen: %s",
                len(events), len(usd_events), impact_values,
            )
            return events, 200
        if r.status_code == 404 and suppress_404:
            log.info("FF next-week feed not yet published (HTTP 404) — keeping current cache.")
            return [], 404
        log.warning("Forex Factory fetch HTTP %s from %s", r.status_code, url)
        return [], r.status_code
    except Exception as exc:
        log.warning("Forex Factory fetch error (%s): %s", url, exc)
        return [], None


def _load_existing_cache() -> list:
    if not CACHE_PATH.exists():
        return []
    try:
        with CACHE_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception as exc:
        log.warning("Could not read existing calendar_cache.json: %s", exc)
        return []


def _deduplicate(events: list) -> list:
    seen = set()
    out = []
    for e in events:
        key = (e.get("name", "").lower(), e.get("time_sgt", ""))
        if key not in seen:
            seen.add(key)
            out.append(e)
    return out


def _prune_old_events(events: list, days_ahead: int = 14) -> list:
    now    = _now_sgt()
    cutoff = now + timedelta(days=days_ahead)
    kept   = []
    for e in events:
        try:
            dt = SGT.localize(datetime.strptime(e["time_sgt"], "%Y-%m-%d %H:%M"))
            if now <= dt <= cutoff:
                kept.append(e)
            # else: event is in the past or beyond 14 days — silently drop (expected)
        except Exception as exc:
            log.warning(
                "calendar_fetcher: dropping cached event with unparseable time_sgt | "
                "name=%r  time_sgt=%r  error=%s",
                e.get("name"), e.get("time_sgt"), exc,
            )
    return kept


def _should_skip_fetch(settings: dict, state: dict) -> tuple[bool, str | None]:
    now = _now_sgt()
    next_allowed = _parse_sgt(state.get("calendar_next_allowed_fetch_sgt"))
    if next_allowed and now < next_allowed:
        return True, f"backoff_active_until={next_allowed.strftime('%Y-%m-%d %H:%M:%S')}"

    interval_min = int(settings.get("calendar_fetch_interval_min", 60))
    last_success = _parse_sgt(state.get("calendar_last_success_sgt"))
    if last_success and (now - last_success) < timedelta(minutes=interval_min):
        return True, f"cooldown_active_last_success={last_success.strftime('%Y-%m-%d %H:%M:%S')}"

    return False, None


def run_fetch() -> bool:
    log.info("Fetching economic calendar from Forex Factory...")

    settings = load_settings()
    state = _load_runtime_state()
    now = _now_sgt()
    state["calendar_last_attempt_sgt"] = now.strftime("%Y-%m-%d %H:%M:%S")

    skip, reason = _should_skip_fetch(settings, state)
    if skip:
        state["calendar_last_fetch_result"] = f"skipped:{reason}"
        _save_runtime_state(state)
        log.info("Skipping calendar refresh — %s", reason)
        return False

    today_weekday = now.weekday()
    suppress_nextweek_404 = today_weekday < 3

    this_week, status_this = _fetch_ff_events(FF_URL)
    next_week, status_next = _fetch_ff_events(NEXT_WEEK_URL, suppress_404=suppress_nextweek_404)
    all_raw = this_week + next_week

    if status_this == 429 or status_next == 429:
        retry_after_min = int(settings.get("calendar_retry_after_min", 15))
        next_allowed = now + timedelta(minutes=retry_after_min)
        state["calendar_last_fetch_result"] = "rate_limited_429"
        state["calendar_next_allowed_fetch_sgt"] = next_allowed.strftime("%Y-%m-%d %H:%M:%S")
        _save_runtime_state(state)
        log.warning("Calendar fetch rate-limited (HTTP 429) — backing off until %s SGT.", next_allowed.strftime("%Y-%m-%d %H:%M:%S"))
        return False

    if not all_raw:
        state["calendar_last_fetch_result"] = "no_events_kept_existing_cache"
        _save_runtime_state(state)
        log.warning("No events fetched — keeping existing calendar_cache.json unchanged.")
        return False

    parsed = [e for e in (_parse_ff_event(ev) for ev in all_raw) if e is not None]
    log.info("Parsed %d gold-relevant events from %d total", len(parsed), len(all_raw))

    if not parsed:
        # Diagnostic: show ALL USD high/medium-impact events in the feed so the
        # operator can see exactly which titles exist vs which keywords matched.
        # Impact filter must mirror _is_gold_relevant exactly.
        _relevant_impacts = {"high", "medium", "3", "red", "medium-high"}
        usd_high = [
            f"{e.get('title', '')} [{e.get('impact', '')}]"
            for e in all_raw
            if e.get("country", "").upper() == "USD"
            and str(e.get("impact", "")).lower() in _relevant_impacts
        ]
        state["calendar_last_fetch_result"] = "no_relevant_events_kept_existing_cache"
        _save_runtime_state(state)
        log.warning(
            "calendar_fetcher: 0 events parsed. USD high/medium-impact titles in feed "
            "(check keywords vs titles): %s",
            usd_high[:20],
        )
        log.warning("No relevant events found in feed — keeping existing cache.")
        return False

    existing = _load_existing_cache()
    merged = _deduplicate(parsed + existing)
    pruned = _prune_old_events(merged, days_ahead=14)
    pruned.sort(key=lambda e: e.get("time_sgt", ""))

    # Atomic write — consistent with all other state file writes in this codebase
    save_json(CACHE_PATH, pruned)

    state["calendar_last_success_sgt"] = now.strftime("%Y-%m-%d %H:%M:%S")
    state["calendar_last_fetch_result"] = f"success:{len(pruned)}_events"
    state.pop("calendar_next_allowed_fetch_sgt", None)
    _save_runtime_state(state)

    log.info("calendar_cache.json updated — %d events saved (next 14 days).", len(pruned))
    return True


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    success = run_fetch()
    if not success:
        log.warning("Falling back to existing calendar_cache.json")
