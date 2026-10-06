"""
utilities/logger.py — Centralized logging with request-id trace support.
"""

import logging
import os
import sys


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(f"aishu.{name}")
    if logger.handlers:
        return logger

    from config.settings import LOG_FILE, LOG_LEVEL
    level = getattr(logging, LOG_LEVEL, logging.INFO)
    logger.setLevel(logging.DEBUG)

    fmt = logging.Formatter(
        fmt="[%(asctime)s] %(levelname)-8s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Windows consoles are often cp1252; logging an emoji or relationship arrow
    # must not raise inside logging and obscure the actual application event.
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(errors="backslashreplace")
        except (OSError, ValueError):
            pass
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(level)
    console.setFormatter(fmt)
    logger.addHandler(console)

    try:
        os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
        fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    except Exception as e:
        print(f"[WARNING] Could not create log file: {e}")

    logger.propagate = False
    return logger


def log_pipeline(log, request_id: str, stage: str, detail: str = ""):
    """Structured pipeline log entry with trace id."""
    msg = f"[{request_id}] [{stage}]"
    if detail:
        msg += f" {detail}"
    log.debug(msg)
