"""
================================================================================
Project:     River Vortex — Smart Home Hub for the River Song AI Ecosystem
File:        telemetry/logger.py
Purpose:     Logging configuration for River Vortex. Sets up structured
             logging with file rotation, console output, and optional
             JSON formatting for log aggregation. Called once at startup
             by main.py before any other subsystem initializes.
Author:      [Author Placeholder]
Version:     1.0.0
Date:        2026-05-25
License:     Internal Use Only — River Song AI / riversongai.com
================================================================================
"""

import logging
import logging.handlers
import os
import sys
from pathlib import Path

from core.constants import LOG_DIR, LOG_RETENTION_DAYS, LOG_ROTATION_SIZE_MB


def setup_logging(
    log_level: str = "INFO",
    log_dir: str = LOG_DIR,
    enable_json: bool = False,
) -> None:
    """
    Configure the root logger for River Vortex.

    Sets up:
    - Console handler (stdout) with colored level names
    - Rotating file handler in log_dir/river-vortex.log
    - Optional JSON formatter for log aggregation pipelines

    This function is idempotent — calling it multiple times is safe.

    Args:
        log_level:   Logging level string (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        log_dir:     Directory for log files. Created if it does not exist.
        enable_json: If True, use JSON formatting for the file handler.
    """
    numeric_level = getattr(logging, log_level.upper(), logging.INFO)

    root_logger = logging.getLogger()
    if root_logger.handlers:
        # Already configured — update level only
        root_logger.setLevel(numeric_level)
        return

    root_logger.setLevel(numeric_level)

    # ── Console handler ───────────────────────────────────────────────────────
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(numeric_level)
    console_handler.setFormatter(_ConsoleFormatter())
    root_logger.addHandler(console_handler)

    # ── File handler ──────────────────────────────────────────────────────────
    log_path = Path(log_dir)
    try:
        log_path.mkdir(parents=True, exist_ok=True)
        log_file = log_path / "river-vortex.log"

        file_handler = logging.handlers.RotatingFileHandler(
            filename=str(log_file),
            maxBytes=LOG_ROTATION_SIZE_MB * 1024 * 1024,
            backupCount=LOG_RETENTION_DAYS,
            encoding="utf-8",
        )
        file_handler.setLevel(numeric_level)
        file_handler.setFormatter(
            _JsonFormatter() if enable_json else _FileFormatter()
        )
        root_logger.addHandler(file_handler)
        logging.getLogger(__name__).debug("Log file: %s", log_file)

    except (PermissionError, OSError) as exc:
        # Log directory not writable — console only
        logging.getLogger(__name__).warning(
            "Cannot write log file to '%s': %s — logging to console only.", log_dir, exc
        )

    # Suppress noisy third-party loggers
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("websockets").setLevel(logging.WARNING)


# ─────────────────────────────────────────────────────────────────────────────
# Formatters
# ─────────────────────────────────────────────────────────────────────────────

class _ConsoleFormatter(logging.Formatter):
    """
    Console log formatter with ANSI color codes for log levels.

    Makes it easy to spot warnings and errors in the terminal during
    development and on-device debugging.
    """

    LEVEL_COLORS = {
        "DEBUG":    "\033[36m",   # Cyan
        "INFO":     "\033[32m",   # Green
        "WARNING":  "\033[33m",   # Yellow
        "ERROR":    "\033[31m",   # Red
        "CRITICAL": "\033[35m",   # Magenta
    }
    RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        """Format a log record with color-coded level name."""
        color = self.LEVEL_COLORS.get(record.levelname, "")
        record.levelname = f"{color}{record.levelname:<8}{self.RESET}"
        formatter = logging.Formatter(
            fmt="%(asctime)s %(levelname)s %(name)s — %(message)s",
            datefmt="%H:%M:%S",
        )
        return formatter.format(record)


class _FileFormatter(logging.Formatter):
    """Standard text formatter for log files."""

    def __init__(self) -> None:
        """Initialize with a fixed format string."""
        super().__init__(
            fmt="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )


class _JsonFormatter(logging.Formatter):
    """
    JSON log formatter for structured log aggregation.

    Outputs one JSON object per line, compatible with log shippers
    like Filebeat, Fluentd, or Loki.
    """

    def format(self, record: logging.LogRecord) -> str:
        """Format a log record as a JSON string."""
        import json
        from datetime import datetime, timezone

        payload = {
            "timestamp": datetime.fromtimestamp(
                record.created, tz=timezone.utc
            ).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload)
