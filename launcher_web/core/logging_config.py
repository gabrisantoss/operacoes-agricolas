from __future__ import annotations

import logging
import os
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path


LOG_SUBDIRS = ("portal", "notas", "colaboradores", "balanca-api", "analises")


class RequestLogDefaults(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        defaults = {
            "request_id": "-",
            "user": "-",
            "route": "-",
            "method": "-",
            "status": "-",
            "system": "-",
        }
        for key, value in defaults.items():
            if not hasattr(record, key):
                setattr(record, key, value)
        return True


def ensure_log_dirs(log_root: Path) -> None:
    for name in LOG_SUBDIRS:
        (log_root / name).mkdir(parents=True, exist_ok=True)


def configure_portal_logging(log_root: Path, portal_log_dir: Path) -> logging.Logger:
    ensure_log_dirs(log_root)
    portal_log_dir.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("portal_agricola")
    logger.setLevel(logging.INFO)
    logger.propagate = False

    if not logger.handlers:
        retention_days = max(int(os.environ.get("PORTAL_LOG_RETENTION_DAYS", "30")), 1)
        handler = TimedRotatingFileHandler(
            portal_log_dir / "portal.log",
            when="midnight",
            interval=1,
            backupCount=retention_days,
            encoding="utf-8",
            delay=True,
        )
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s level=%(levelname)s request_id=%(request_id)s "
                "user=%(user)s method=%(method)s route=%(route)s "
                "status=%(status)s system=%(system)s message=%(message)s"
            )
        )
        handler.addFilter(RequestLogDefaults())
        logger.addHandler(handler)

    return logger
