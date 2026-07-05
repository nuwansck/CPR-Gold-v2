from __future__ import annotations

import logging
import os
import re
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from config_loader import DATA_DIR

_LOG_CONFIGURED = False
_SECRET_PATTERNS = [
    re.compile(r'(Bearer\s+)[A-Za-z0-9\-_.]+', re.IGNORECASE),
    re.compile(r'(OANDA_API_KEY=)[^\s]+', re.IGNORECASE),
    re.compile(r'(TELEGRAM_TOKEN=)[^\s]+', re.IGNORECASE),
    re.compile(r"(Authorization['\"]?\s*[:=]\s*['\"]?Bearer\s+)[A-Za-z0-9\-_.]+", re.IGNORECASE),
]


class SecretRedactionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            rendered = record.getMessage()
            for pattern in _SECRET_PATTERNS:
                rendered = pattern.sub(r'\1***REDACTED***', rendered)
            record.msg = rendered
            record.args = ()
        except Exception:
            pass
        return True


class ContextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        if not hasattr(record, 'run_id'):
            record.run_id = '-'
        if not hasattr(record, 'pair'):
            record.pair = '-'
        if not hasattr(record, 'event'):
            record.event = '-'
        return super().format(record)



def configure_logging(level: str | None = None) -> None:
    global _LOG_CONFIGURED
    if _LOG_CONFIGURED:
        return

    log_level = (level or os.environ.get('LOG_LEVEL', 'INFO')).upper()
    root = logging.getLogger()
    root.setLevel(getattr(logging, log_level, logging.INFO))
    root.handlers.clear()

    fmt = ContextFormatter(fmt='%(asctime)s %(levelname)s %(name)s run=%(run_id)s pair=%(pair)s event=%(event)s — %(message)s')
    redaction = SecretRedactionFilter()

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    console.addFilter(redaction)
    root.addHandler(console)

    try:
        logs_dir = Path(DATA_DIR) / 'logs'
        logs_dir.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(logs_dir / 'cpr_gold_bot.log', maxBytes=1_000_000, backupCount=5, encoding='utf-8')
        file_handler.setFormatter(fmt)
        file_handler.addFilter(redaction)
        root.addHandler(file_handler)
    except Exception:
        pass

    logging.captureWarnings(True)
    _LOG_CONFIGURED = True


class LogContext(logging.LoggerAdapter):
    def process(self, msg, kwargs):
        extra = kwargs.setdefault('extra', {})
        for k, v in self.extra.items():
            extra.setdefault(k, v)
        return msg, kwargs



def get_logger(name: str, **extra) -> logging.LoggerAdapter:
    return LogContext(logging.getLogger(name), extra)
