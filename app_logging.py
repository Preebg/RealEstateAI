"""Structured logging and optional Sentry reporting for RealEstateAI."""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any, Protocol

_CONFIGURED = False
_SENTRY_ENABLED = False
_USE_STRUCTLOG = False

try:
    import structlog

    _USE_STRUCTLOG = True
except ImportError:
    structlog = None  # type: ignore[assignment]


class AppLogger(Protocol):
    def info(self, event: str, **context: Any) -> None: ...
    def warning(self, event: str, **context: Any) -> None: ...
    def error(self, event: str, **context: Any) -> None: ...


class _StdlibLogger:
    """JSON-style fallback when structlog is not installed."""

    def __init__(self, name: str) -> None:
        self._logger = logging.getLogger(name)

    def _emit(self, level: int, event: str, **context: Any) -> None:
        payload = {
            "event": event,
            "level": logging.getLevelName(level),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **context,
        }
        if "exc_info" in context and context["exc_info"] is not None:
            self._logger.log(level, json.dumps(payload), exc_info=context["exc_info"])
        else:
            self._logger.log(level, json.dumps(payload))

    def info(self, event: str, **context: Any) -> None:
        self._emit(logging.INFO, event, **context)

    def warning(self, event: str, **context: Any) -> None:
        self._emit(logging.WARNING, event, **context)

    def error(self, event: str, **context: Any) -> None:
        self._emit(logging.ERROR, event, **context)


def _init_sentry() -> None:
    global _SENTRY_ENABLED
    dsn = os.getenv("SENTRY_DSN", "").strip()
    if not dsn:
        return
    try:
        import sentry_sdk
    except ImportError:
        logging.getLogger("app_logging").warning(
            "SENTRY_DSN is set but sentry-sdk is not installed; skipping Sentry."
        )
        return

    sentry_sdk.init(
        dsn=dsn,
        environment=os.getenv("SENTRY_ENVIRONMENT", "development"),
        traces_sample_rate=float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0.1")),
    )
    _SENTRY_ENABLED = True


def configure_logging(component: str = "app") -> AppLogger:
    """Configure logging once; return a bound logger for the given component."""
    global _CONFIGURED
    if not _CONFIGURED:
        log_level = os.getenv("LOG_LEVEL", "INFO").upper()
        level = getattr(logging, log_level, logging.INFO)
        logging.basicConfig(
            format="%(message)s",
            stream=sys.stdout,
            level=level,
        )
        if _USE_STRUCTLOG and structlog is not None:
            structlog.configure(
                processors=[
                    structlog.contextvars.merge_contextvars,
                    structlog.processors.add_log_level,
                    structlog.processors.TimeStamper(fmt="iso"),
                    structlog.processors.StackInfoRenderer(),
                    structlog.processors.format_exc_info,
                    structlog.processors.JSONRenderer(),
                ],
                wrapper_class=structlog.make_filtering_bound_logger(level),
                context_class=dict,
                logger_factory=structlog.PrintLoggerFactory(),
                cache_logger_on_first_use=True,
            )
        _init_sentry()
        _CONFIGURED = True
    return get_logger(component)


def get_logger(component: str) -> AppLogger:
    if not _CONFIGURED:
        return configure_logging(component)
    if _USE_STRUCTLOG and structlog is not None:
        return structlog.get_logger().bind(component=component)  # type: ignore[return-value]
    return _StdlibLogger(f"realestateai.{component}")


def report_error(
    logger: AppLogger,
    event: str,
    exc: BaseException,
    *,
    level: str = "error",
    **context: Any,
) -> None:
    """Log a structured error and send it to Sentry when configured."""
    log_fn = getattr(logger, level, logger.error)
    log_fn(
        event,
        error=str(exc),
        error_type=type(exc).__name__,
        exc_info=exc,
        **context,
    )
    if _SENTRY_ENABLED:
        import sentry_sdk

        with sentry_sdk.push_scope() as scope:
            for key, value in context.items():
                scope.set_extra(key, value)
            scope.set_tag("component", context.get("component", "unknown"))
            sentry_sdk.capture_exception(exc)
