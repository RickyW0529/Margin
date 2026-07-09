"""Independent Tushare source-system contracts and landing identities."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, date, datetime
from typing import Any

from pydantic import BaseModel, field_validator

from margin.data.requirements import (
    ProviderEndpointRequirement,
    QuantDataRequirementCatalog,
)
from margin.news.models import ensure_utc

TUSHARE_SOURCE_SCHEMA = "source_tushare"
_ST_NAME = re.compile(r"^(?:S\*ST|\*ST|ST)", re.IGNORECASE)
_DELISTING_NAME = re.compile(r"^退市", re.IGNORECASE)


def is_st_security_name(name: str) -> bool:
    """Return whether a current A-share name carries an ST designation.

    Args:
        name: str: .

    Returns:
        bool: .
    """
    return bool(_ST_NAME.match(name.strip()))


def is_delisting_security_name(name: str) -> bool:
    """Return whether a current A-share name indicates delisting transition.

    Args:
        name: str: .

    Returns:
        bool: .
    """
    return bool(_DELISTING_NAME.match(name.strip()))


class TushareSourceCatalog:
    """Map quant-admitted Tushare APIs to dedicated source tables.."""

    def __init__(self, requirements: QuantDataRequirementCatalog) -> None:
        """Initialize from the quant endpoint admission catalog.

        Args:
            requirements: QuantDataRequirementCatalog: .

        Returns:
            None: .
        """
        self._endpoints = {
            endpoint.api_name: endpoint for endpoint in requirements.enabled_endpoints("tushare")
        }

    def endpoint(self, api_name: str) -> ProviderEndpointRequirement:
        """Return an admitted Tushare endpoint.

        Args:
            api_name: str: .

        Returns:
            ProviderEndpointRequirement: .
        """
        return self._endpoints[api_name.strip().lower()]

    def table_name(self, api_name: str) -> str:
        """Return the fully-qualified dedicated landing table name.

        Args:
            api_name: str: .

        Returns:
            str: .
        """
        normalized = api_name.strip().lower()
        if normalized not in self._endpoints:
            raise KeyError(f"Tushare endpoint is not admitted: {api_name}")
        return f"{TUSHARE_SOURCE_SCHEMA}.ts_{normalized}"

    def table_names(self) -> tuple[str, ...]:
        """Return all admitted source table names in stable order.

        Returns:
            tuple[str, ...]: .
        """
        return tuple(self.table_name(name) for name in sorted(self._endpoints))


class TushareLandingRecord(BaseModel):
    """Immutable row persisted in one endpoint-specific Tushare source table.."""

    source_row_id: str
    endpoint: str
    natural_key_hash: str
    revision_hash: str
    symbol: str | None
    business_date: date | None
    published_at: datetime | None
    available_at: datetime
    fetched_at: datetime
    source_partition: str
    raw_payload: dict[str, Any]
    raw_snapshot_id: str | None = None
    sync_run_id: str
    quality_status: str = "pending"

    model_config = {"frozen": True}

    @field_validator("published_at", "available_at", "fetched_at")
    @classmethod
    def normalize_datetime(cls, value: datetime | None) -> datetime | None:
        """Normalize source-system timestamps to UTC.

        Args:
            value: datetime | None: .

        Returns:
            datetime | None: .
        """
        return ensure_utc(value) if value is not None else None

    @classmethod
    def from_payload(
        cls,
        *,
        endpoint: ProviderEndpointRequirement,
        payload: dict[str, Any],
        fetched_at: datetime,
        sync_run_id: str,
        raw_snapshot_id: str | None = None,
    ) -> TushareLandingRecord:
        """Build stable natural-key and revision identities from one API row.

        Args:
            endpoint: ProviderEndpointRequirement: .
            payload: dict[str, Any]: .
            fetched_at: datetime: .
            sync_run_id: str: .
            raw_snapshot_id: str | None: .

        Returns:
            TushareLandingRecord: .
        """
        normalized_fetched_at = ensure_utc(fetched_at)
        natural_key = {
            field: _json_scalar(payload.get(field)) for field in endpoint.natural_key_fields
        }
        natural_key_hash = _hash_json(
            {
                "provider": endpoint.provider,
                "api_name": endpoint.api_name,
                "key": natural_key,
            }
        )
        revision_hash = _hash_json(payload)
        source_row_id = _hash_json(
            {
                "natural_key_hash": natural_key_hash,
                "revision_hash": revision_hash,
            },
            prefix="tsr",
        )
        business_date = _business_date(payload)
        published_at = _published_at(payload)
        available_at = published_at or normalized_fetched_at
        return cls(
            source_row_id=source_row_id,
            endpoint=endpoint.api_name,
            natural_key_hash=natural_key_hash,
            revision_hash=revision_hash,
            symbol=_symbol(payload),
            business_date=business_date,
            published_at=published_at,
            available_at=available_at,
            fetched_at=normalized_fetched_at,
            source_partition=(business_date.strftime("%Y-%m") if business_date else "snapshot"),
            raw_payload=dict(payload),
            raw_snapshot_id=raw_snapshot_id,
            sync_run_id=sync_run_id,
        )


def _symbol(payload: dict[str, Any]) -> str | None:
    """Extract and normalize the security symbol from a provider row.

    Args:
        payload: dict[str, Any]: .

    Returns:
        str | None: .
    """
    value = payload.get("ts_code") or payload.get("con_code")
    normalized = str(value or "").strip().upper()
    return normalized or None


def _business_date(payload: dict[str, Any]) -> date | None:
    """Return the first parseable business date from known payload fields.

    Args:
        payload: dict[str, Any]: .

    Returns:
        date | None: .
    """
    for field in (
        "trade_date",
        "end_date",
        "ann_date",
        "start_date",
        "in_date",
        "out_date",
        "list_date",
        "cal_date",
    ):
        parsed = _parse_date(payload.get(field))
        if parsed is not None:
            return parsed
    return None


def _published_at(payload: dict[str, Any]) -> datetime | None:
    """Return the first parseable publication timestamp from known fields.

    Args:
        payload: dict[str, Any]: .

    Returns:
        datetime | None: .
    """
    for field in ("f_ann_date", "ann_date", "trade_date", "cal_date"):
        parsed = _parse_date(payload.get(field))
        if parsed is not None:
            return datetime.combine(parsed, datetime.min.time(), tzinfo=UTC)
    return None


def _parse_date(value: Any) -> date | None:
    """Parse a Tushare date string in YYYYMMDD or ISO format.

    Args:
        value: Any: .

    Returns:
        date | None: .
    """
    normalized = str(value or "").strip()
    if not normalized:
        return None
    for date_format in ("%Y%m%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(normalized[:10], date_format).date()
        except ValueError:
            continue
    return None


def _json_scalar(value: Any) -> Any:
    """Coerce a payload value into a JSON-serializable scalar.

    Args:
        value: Any: .

    Returns:
        Any: .
    """
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value)


def _hash_json(payload: Any, *, prefix: str = "sha256") -> str:
    """Return a deterministic SHA-256 hash of a JSON-serializable payload.

    Args:
        payload: Any: .
        prefix: str: .

    Returns:
        str: .
    """
    encoded = json.dumps(
        payload,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return f"{prefix}:" + hashlib.sha256(encoded).hexdigest()
