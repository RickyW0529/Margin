"""Quant data adapter contract.

The adapter consumes only frozen valuation-discovery input snapshots and data
warehouse repositories. It must not import AKShare, Tushare, news, RAG, or LLM
providers.
"""

from __future__ import annotations

from typing import Protocol

import pandas as pd

from margin.valuation_discovery.models import QuantInputSnapshot


class QuantDataAdapter(Protocol):
    """Load a quant-ready cross-section from a frozen input snapshot."""

    def load_cross_section(self, snapshot: QuantInputSnapshot) -> pd.DataFrame:
        """Return one row per security with standardized indicator columns."""
