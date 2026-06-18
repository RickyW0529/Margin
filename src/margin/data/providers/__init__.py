"""Concrete data provider implementations for external A-share data sources."""

from margin.data.providers.akshare_provider import AKShareProvider
from margin.data.providers.tushare_provider import TushareProvider

__all__ = ["AKShareProvider", "TushareProvider"]
