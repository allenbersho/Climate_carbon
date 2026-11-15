"""Structured JSON logging configuration for CarbonTrack."""

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any


class JSONFormatter(logging.Formatter):
    """Custom logging formatter outputting single-line structured JSON logs."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # Attach exception traceback if present
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)

        # Attach custom extra fields if provided
        if hasattr(record, "extra_data") and isinstance(record.extra_data, dict):
            log_entry.update(record.extra_data)

        return json.dumps(log_entry, default=str)


def setup_logging(log_level: str = "INFO", log_format: str = "json") -> None:
    """Configure application logging handlers and formatters."""
    root_logger = logging.getLogger()
    numeric_level = getattr(logging, log_level.upper(), logging.INFO)
    root_logger.setLevel(numeric_level)

    # Avoid duplicate handlers if re-executed
    if not root_logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        if log_format.lower() == "json":
            handler.setFormatter(JSONFormatter())
        else:
            handler.setFormatter(
                logging.Formatter(
                    "[%(asctime)s] %(levelname)s in %(module)s: %(message)s"
                )
            )
        root_logger.addHandler(handler)
    else:
        # Update existing handlers if present
        for handler in root_logger.handlers:
            if log_format.lower() == "json":
                handler.setFormatter(JSONFormatter())
