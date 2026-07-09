"""Structured logging configuration using structlog.

Renders logs either as JSON (production) or as a colored console stream
(development). Both stdlib ``logging`` and structlog bound loggers share the
same processors so that third-party library output is formatted consistently.
"""

from __future__ import annotations

import logging
import sys

import structlog

from margin.core.audit import SecretRedactingProcessor


def configure_logging(
    *,
    log_level: str = "INFO",
    log_format: str = "json",
    secret_values: tuple[str, ...] = (),
) -> None:
    """Configure structlog and stdlib logging for Margin.

    Args:
        log_level: str: .
        log_format: str: .
        secret_values: tuple[str, ...]: .

    Returns:
        None: .
    """
    redactor = SecretRedactingProcessor(secret_values=secret_values)
    # Shared processors run for both stdlib logging and structlog bound loggers.
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.stdlib.ExtraAdder(),
        redactor,
    ]

    if log_format == "json":
        formatter = structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=shared_processors,
            processors=[
                structlog.processors.dict_tracebacks,
                redactor,
                structlog.processors.JSONRenderer(),
            ],
        )
    else:
        formatter = structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=shared_processors,
            processors=[redactor, structlog.dev.ConsoleRenderer()],
        )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    root_logger = logging.getLogger()
    # Remove existing handlers to avoid duplicate log lines after reconfiguration.
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(log_level.upper())

    structlog.configure(
        processors=shared_processors + [structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, log_level.upper())),
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
