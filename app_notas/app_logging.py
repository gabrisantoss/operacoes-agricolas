from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from app_config import LOG_DIR, LOG_LEVEL, LOG_PATH


_CONFIGURED = False


def setup_logging() -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return

    level = getattr(logging, LOG_LEVEL, logging.INFO)
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )

    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    if not any(getattr(handler, "_app_notas_handler", False) for handler in root_logger.handlers):
        LOG_DIR.mkdir(parents=True, exist_ok=True)

        file_handler = RotatingFileHandler(
            Path(LOG_PATH),
            maxBytes=1_000_000,
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        file_handler._app_notas_handler = True
        root_logger.addHandler(file_handler)

        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        stream_handler._app_notas_handler = True
        root_logger.addHandler(stream_handler)

    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    setup_logging()
    return logging.getLogger(name)
