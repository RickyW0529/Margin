"""Centralized SQL query factory for Margin.

All SQL statements — raw text clauses and SQLAlchemy ORM query builders — are
defined here and re-exported for repository and service modules to consume.
Repository classes retain session/transaction management and row-to-domain
mapping; query construction lives in this package.
"""

from __future__ import annotations

import importlib
from typing import Any

__all__ = [
    "backtest_queries",
    "core_queries",
    "data_queries",
    "dashboard_queries",
    "evidence_queries",
    "health_queries",
    "news_queries",
    "raw_statements",
    "research_queries",
    "strategy_queries",
    "valuation_queries",
    "vector_queries",
]


def __getattr__(name: str) -> Any:
    """Process __getattr__.

    Args:
        name: str: .

    Returns:
        Any: .
    """
    if name in __all__:
        return importlib.import_module(f"{__name__}.{name}")
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
