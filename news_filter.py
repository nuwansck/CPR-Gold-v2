import json
import logging
from datetime import datetime, timedelta

import pytz

from state_utils import CALENDAR_CACHE_FILE

log = logging.getLogger(__name__)

# Default penalty applied to signal score when a medium-impact news event
# is active. Negative value intentionally reduces score.
# Configurable via settings.json: "news_medium_penalty_score": -1
DEFAULT_MEDIUM_PENALTY = -1


class NewsFilter:
    """Classify USD events for Gold and decide hard block vs soft penalty.

    V2.0 logic:
    - Major events: hard block within configured window
    - Medium events: no hard block, apply soft score penalty when nearby
    - Minor/irrelevant events: ignore

    The medium penalty score is now configurable via settings.json
    (key: news_medium_penalty_score, default: -1).
    """

    MAJOR_KEYWORDS = [
        "fomc", "non-farm", "nfp", "powell", "rate decision",
        "fed chair", "federal reserve",
    ]
    MEDIUM_KEYWORDS = [
        "cpi", "core cpi", "pce", "core pce", "unemployment",
        "jobless claims",
    ]

    def __init__(self, before_minutes: int = 30, after_minutes: int = 30,
                 lookahead_minutes: int = 120, medium_penalty: int = DEFAULT_MEDIUM_PENALTY):
        self.before_minutes    = before_minutes
        self.after_minutes     = after_minutes
        self.lookahead_minutes = lookahead_minutes
        self.medium_penalty    = int(medium_penalty)
        self.sg_tz = pytz.timezone("Asia/Singapore")
        self.path = CALENDAR_CACHE_FILE

    def classify_event(self, event: dict) -> str | None:
        name     = str(event.get("name", "")).lower()
        currency = str(event.get("currency", "")).upper()
        impact   = str(event.get("impact", "")).lower()

        if currency != "USD":
            return None
        # Accept all impact values that calendar_fetcher passes through.
        # FF feed now returns "high" / "medium" (lowercased on storage).
        # Legacy values ("3", "red", "medium-high") kept for cache compatibility.
        if impact not in {"high", "medium", "3", "red", "medium-high"}:
            return None

        if any(k in name for k in self.MAJOR_KEYWORDS):
            return "major"
        if any(k in name for k in self.MEDIUM_KEYWORDS):
            return "medium"
        return None

    def get_status_now(self) -> dict:
        if not self.path.exists():
            return {"blocked": False, "penalty": 0, "reason": "No calendar_cache.json found", "severity": None}

        try:
            with open(self.path, "r", encoding="utf-8") as f:
                events = json.load(f)
        except Exception as e:
            log.warning("Could not read calendar_cache.json (%s) — skipping news check.", e)
            return {"blocked": False, "penalty": 0, "reason": f"Calendar cache unreadable — news check skipped ({e})", "severity": None}

        now = datetime.now(self.sg_tz)
        active_medium = None

        for event in events:
            severity = self.classify_event(event)
            if not severity:
                continue

            event_time = self.sg_tz.localize(datetime.strptime(event["time_sgt"], "%Y-%m-%d %H:%M"))
            window_start = event_time - timedelta(minutes=self.before_minutes)
            window_end = event_time + timedelta(minutes=self.after_minutes)
            if not (window_start <= now <= window_end):
                continue

            if severity == "major":
                return {
                    "blocked": True,
                    "penalty": 0,
                    "reason": f"Blocked by major news: {event['name']} at {event['time_sgt']} SGT",
                    "severity": severity,
                    "event": event,
                }
            if severity == "medium" and active_medium is None:
                active_medium = {
                    "blocked": False,
                    "penalty": self.medium_penalty,
                    "reason": f"Medium news nearby: {event['name']} at {event['time_sgt']} SGT",
                    "severity": severity,
                    "event": event,
                }

        # Lookahead: scan for upcoming events in the next N minutes (informational only)
        lookahead_events = []
        for event in events:
            severity = self.classify_event(event)
            if not severity:
                continue
            try:
                event_time = self.sg_tz.localize(datetime.strptime(event["time_sgt"], "%Y-%m-%d %H:%M"))
            except Exception:
                continue
            window_start = event_time - timedelta(minutes=self.before_minutes)
            window_end   = event_time + timedelta(minutes=self.after_minutes)
            in_window = window_start <= now <= window_end
            if not in_window:
                lookahead_end = now + timedelta(minutes=self.lookahead_minutes)
                if now <= event_time <= lookahead_end:
                    mins_away = int((event_time - now).total_seconds() // 60)
                    lookahead_events.append({
                        "name": event["name"],
                        "time_sgt": event["time_sgt"],
                        "severity": severity,
                        "mins_away": mins_away,
                    })

        result = active_medium or {"blocked": False, "penalty": 0, "reason": "No blocking news", "severity": None}
        result["lookahead"] = lookahead_events
        return result

    def is_blocked_now(self) -> tuple[bool, str]:
        status = self.get_status_now()
        return bool(status.get("blocked")), str(status.get("reason", "No blocking news"))
