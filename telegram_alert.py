"""
Telegram Alert System — RF Scalp Bot v2.0

Retries up to 3 times on 5xx errors with exponential backoff.
HTTP 429 (rate-limit) respects the Retry-After header.
4xx errors (bad token, bad chat_id) are NOT retried — config errors.

v2.0: send_document() added for scheduled weekly trade history export.
"""
import logging
import os
import time
from pathlib import Path

import requests

from config_loader import load_secrets, load_settings

log = logging.getLogger(__name__)

_MAX_RETRIES  = 3
_RETRY_DELAYS = (2, 5)

_DATA_DIR = Path(os.getenv("DATA_DIR", "/data"))


class TelegramAlert:
    def __init__(self):
        secrets      = load_secrets()
        self.token   = secrets.get("TELEGRAM_TOKEN", "")
        self.chat_id = secrets.get("TELEGRAM_CHAT_ID", "")

    def send(self, message: str) -> bool:
        if not self.token or not self.chat_id:
            log.warning("Telegram not configured.")
            return False

        _bot_name = load_settings().get("bot_name", "RF Scalp")
        url  = f"https://api.telegram.org/bot{self.token}/sendMessage"
        text = f"\U0001f916 {_bot_name}\n{chr(0x2500) * 22}\n{message}"

        for attempt in range(_MAX_RETRIES):
            try:
                r = requests.post(
                    url,
                    data={"chat_id": self.chat_id, "text": text},
                    timeout=10,
                )
                if r.status_code == 200:
                    if attempt:
                        log.info("Telegram sent (attempt %d).", attempt + 1)
                    else:
                        log.info("Telegram sent!")
                    return True

                if r.status_code == 429:
                    retry_after = int(r.headers.get("Retry-After", 5))
                    log.warning(
                        "Telegram rate-limited (429) — waiting %ds (attempt %d/%d).",
                        retry_after, attempt + 1, _MAX_RETRIES,
                    )
                    time.sleep(retry_after)
                    continue

                if r.status_code < 500:
                    log.warning("Telegram %s (no retry): %s", r.status_code, r.text[:200])
                    return False

                log.warning("Telegram 5xx (attempt %d/%d): HTTP %s",
                            attempt + 1, _MAX_RETRIES, r.status_code)
                if attempt < len(_RETRY_DELAYS):
                    time.sleep(_RETRY_DELAYS[attempt])

            except requests.RequestException as exc:
                log.warning("Telegram network error (attempt %d/%d): %s",
                            attempt + 1, _MAX_RETRIES, exc)
                if attempt < len(_RETRY_DELAYS):
                    time.sleep(_RETRY_DELAYS[attempt])

        log.error("Telegram failed after %d attempts.", _MAX_RETRIES)
        return False

    def send_document(self, file_path: Path, caption: str = "") -> bool:
        """Send a file as a Telegram document attachment."""
        if not self.token or not self.chat_id:
            log.warning("Telegram not configured.")
            return False
        if not file_path.exists():
            log.warning("send_document: file not found: %s", file_path)
            return False

        url = f"https://api.telegram.org/bot{self.token}/sendDocument"
        try:
            with open(file_path, "rb") as fh:
                r = requests.post(
                    url,
                    data={"chat_id": self.chat_id, "caption": caption},
                    files={"document": (file_path.name, fh, "application/json")},
                    timeout=30,
                )
            if r.status_code == 200:
                log.info("Telegram document sent: %s", file_path.name)
                return True
            log.warning("Telegram document failed: HTTP %s: %s",
                        r.status_code, r.text[:200])
            return False
        except Exception as exc:
            log.warning("Telegram document error: %s", exc)
            return False
