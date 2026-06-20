"""Position import module — manual entry, CSV/Excel import, broker plugin protocol,
validation, and audit.

Corresponds to specs 02 §3 interface contracts (POST /portfolios/{id}/trades, /imports).
Corresponds to plans 0201 work items:
  0201.1 Manual trade entry interface
  0201.2 CSV/Excel import, field validation, and error reporting
  0201.3 Broker export file adapter plugin protocol
  0201.4 Import audit — record entry time, source, and raw row hash

Principle (product §15 item 10): do not connect to broker accounts by default,
do not store broker passwords, and do not place automatic orders.
"""

from __future__ import annotations

import csv
import hashlib
import io
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from margin.portfolio.models import (
    ImportRecord,
    Trade,
    TradeSide,
    TradeSource,
    make_trade,
)

# ---------------------------------------------------------------------------
# Import exceptions
# ---------------------------------------------------------------------------


class ImportValidationError(ValueError):
    """Raised when an import file fails field validation.

    Attributes:
        errors: A list of per-row error details.
        record: The audit record for the failed import, if one was created.
    """

    def __init__(
        self,
        message: str,
        errors: list[str] | None = None,
        record: ImportRecord | None = None,
    ) -> None:
        """Initialize the validation error.

        Args:
            message: Human-readable error message.
            errors: Optional list of per-row error messages.
            record: Optional audit record associated with the failure.
        """
        super().__init__(message)
        self.errors = errors or []
        self.record = record


class TradeValidationError(ValueError):
    """Raised when a single trade record fails data validation.

    This exception is typically raised by ``validate_trade_fields`` or during row
    conversion when a required field is missing, malformed, or violates a business
    rule (for example a future trade timestamp).
    """


# ---------------------------------------------------------------------------
# 0201.3 Broker export file adapter plugin protocol
# ---------------------------------------------------------------------------


class BrokerImportPlugin(ABC):
    """Broker export file adapter plugin protocol (architecture §20.2).

    Different brokers produce different export formats; this protocol lets plugins adapt
    each format. Plugins only parse the file format and must not store broker passwords
    or connect to broker accounts.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Return the plugin name (e.g. ``htsc`` / ``dongfang``).

        Returns:
            The unique name of the broker plugin.
        """

    @property
    @abstractmethod
    def supported_extensions(self) -> list[str]:
        """Return supported file extensions (e.g. ``[".csv", ".xls"]``).

        Returns:
            A list of file extensions the plugin can parse.
        """

    @abstractmethod
    def parse(self, file_path: Path) -> list[dict[str, Any]]:
        """Parse a broker export file and return a list of raw trade dictionaries.

        Each returned dictionary should contain ``symbol``, ``side``, ``quantity``,
        ``price``, and ``traded_at`` keys, or keys that can be mapped to these fields
        through ``field_mapping``.

        Args:
            file_path: Path to the broker export file.

        Returns:
            A list of raw trade rows as dictionaries.
        """


# ---------------------------------------------------------------------------
# Trade validation
# ---------------------------------------------------------------------------


def validate_trade_fields(
    symbol: str,
    side: str,
    quantity: float,
    price: float,
    traded_at: datetime,
) -> None:
    """Validate the legality of trade fields.

    Args:
        symbol: Trading symbol. Must be a non-empty string.
        side: Trade side. Must match a valid ``TradeSide`` value.
        quantity: Trade quantity. Must be positive.
        price: Trade price. Must be positive.
        traded_at: Trade timestamp. Must not be in the future.

    Raises:
        TradeValidationError: If any field fails validation.
    """
    if not symbol or not symbol.strip():
        raise TradeValidationError("symbol is required")

    try:
        TradeSide(side)
    except ValueError:
        valid = [s.value for s in TradeSide]
        raise TradeValidationError(
            f"side must be one of {valid}, got '{side}'"
        ) from None

    if quantity <= 0:
        raise TradeValidationError(f"quantity must be positive, got {quantity}")

    if price <= 0:
        raise TradeValidationError(f"price must be positive, got {price}")

    normalized_traded_at = (
        traded_at.replace(tzinfo=UTC)
        if traded_at.tzinfo is None
        else traded_at.astimezone(UTC)
    )
    if normalized_traded_at > datetime.now(UTC):
        raise TradeValidationError(
            f"traded_at cannot be in the future: {traded_at}"
        )


def compute_raw_hash(rows: list[dict[str, Any]]) -> str:
    """Compute a SHA256 hash of raw rows for import audit.

    Args:
        rows: A list of raw row dictionaries.

    Returns:
        A ``sha256:<hexdigest>`` string representing the row hash.
    """
    import json

    serialized = json.dumps(rows, sort_keys=True, default=str, ensure_ascii=False)
    return "sha256:" + hashlib.sha256(serialized.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# 0201.1 / 0201.2 / 0201.4 Importer
# ---------------------------------------------------------------------------


class TradeImporter:
    """Trade record importer.

    Supports manual entry, CSV/Excel import, and broker plugin import.
    Every import produces an ``ImportRecord`` audit record.
    Format errors reject writes and report field errors explicitly; rows are never
    silently dropped.
    """

    def __init__(self) -> None:
        """Initialize the importer with empty state."""
        self._import_records: list[ImportRecord] = []
        self._import_counter = 0
        self._broker_plugins: dict[str, BrokerImportPlugin] = {}

    def register_broker_plugin(self, plugin: BrokerImportPlugin) -> None:
        """Register a broker import plugin.

        Args:
            plugin: A ``BrokerImportPlugin`` implementation to register.
        """
        self._broker_plugins[plugin.name] = plugin

    def add_trade_manual(
        self,
        portfolio_id: str,
        symbol: str,
        side: str,
        quantity: float,
        price: float,
        traded_at: datetime,
        fee: float = 0.0,
        tax: float = 0.0,
        note: str | None = None,
    ) -> Trade:
        """Manually enter a single trade (corresponds to POST /portfolios/{id}/trades).

        Args:
            portfolio_id: Portfolio identifier.
            symbol: Trading symbol.
            side: Trade side as a string.
            quantity: Trade quantity.
            price: Trade price.
            traded_at: Trade timestamp.
            fee: Optional transaction fee.
            tax: Optional transaction tax.
            note: Optional human-readable note.

        Returns:
            The created ``Trade`` instance.

        Raises:
            TradeValidationError: If validation fails. No silent writes occur.
        """
        validate_trade_fields(symbol, side, quantity, price, traded_at)

        trade = make_trade(
            portfolio_id=portfolio_id,
            symbol=symbol,
            side=TradeSide(side),
            quantity=quantity,
            price=price,
            traded_at=traded_at,
            fee=fee,
            tax=tax,
            source=TradeSource.MANUAL,
            note=note,
        )

        self._record_import(
            portfolio_id=portfolio_id,
            source=TradeSource.MANUAL,
            trade_count=1,
            rejected_count=0,
        )
        return trade

    def import_csv(
        self,
        portfolio_id: str,
        file_path: Path,
        field_mapping: dict[str, str] | None = None,
    ) -> tuple[list[Trade], ImportRecord]:
        """Import trades from a CSV file (corresponds to POST /portfolios/{id}/imports).

        Args:
            portfolio_id: Portfolio identifier.
            file_path: Path to the CSV file.
            field_mapping: Mapping from CSV column names to canonical field names.
                Defaults to ``symbol`` / ``side`` / ``quantity`` / ``price`` /
                ``traded_at`` / ``fee`` / ``tax`` / ``note``.

        Returns:
            A tuple of (list of successfully imported trades, import audit record).

        Raises:
            ImportValidationError: If the file format or field validation fails.
        """
        mapping = field_mapping or _DEFAULT_CSV_MAPPING

        try:
            with open(file_path, encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                raw_rows = list(reader)
        except Exception as exc:
            raise ImportValidationError(f"Failed to read CSV: {exc}") from exc

        return self._process_rows(
            portfolio_id=portfolio_id,
            raw_rows=raw_rows,
            mapping=mapping,
            source=TradeSource.CSV,
            file_name=file_path.name,
        )

    def import_csv_bytes(
        self,
        portfolio_id: str,
        content: str,
        field_mapping: dict[str, str] | None = None,
    ) -> tuple[list[Trade], ImportRecord]:
        """Import trades from CSV string content.

        Useful for tests and for accepting CSV payloads through an API.

        Args:
            portfolio_id: Portfolio identifier.
            content: CSV content as a string.
            field_mapping: Optional mapping from CSV column names to canonical field names.

        Returns:
            A tuple of (list of successfully imported trades, import audit record).
        """
        mapping = field_mapping or _DEFAULT_CSV_MAPPING

        reader = csv.DictReader(io.StringIO(content))
        raw_rows = list(reader)

        return self._process_rows(
            portfolio_id=portfolio_id,
            raw_rows=raw_rows,
            mapping=mapping,
            source=TradeSource.CSV,
        )

    def import_excel(
        self,
        portfolio_id: str,
        file_path: Path,
        field_mapping: dict[str, str] | None = None,
    ) -> tuple[list[Trade], ImportRecord]:
        """Import trades from an Excel file.

        Args:
            portfolio_id: Portfolio identifier.
            file_path: Path to the Excel file.
            field_mapping: Optional mapping from column names to canonical field names.

        Returns:
            A tuple of (list of successfully imported trades, import audit record).

        Raises:
            ImportError: If pandas is not installed.
            ImportValidationError: If field validation fails.
        """
        try:
            import pandas as pd
        except ImportError as exc:
            raise ImportError("pandas is required for Excel import") from exc

        mapping = field_mapping or _DEFAULT_CSV_MAPPING
        df = pd.read_excel(file_path)
        raw_rows = df.to_dict("records")

        return self._process_rows(
            portfolio_id=portfolio_id,
            raw_rows=raw_rows,
            mapping=mapping,
            source=TradeSource.EXCEL,
            file_name=file_path.name,
        )

    def import_broker(
        self,
        portfolio_id: str,
        file_path: Path,
        plugin_name: str,
        field_mapping: dict[str, str] | None = None,
    ) -> tuple[list[Trade], ImportRecord]:
        """Import trades from a broker export file using a plugin.

        Corresponds to plans 0201.3: broker export file adapter plugin protocol.
        Plugins only parse the file format and must not store broker passwords or
        connect to broker accounts.

        Args:
            portfolio_id: Portfolio identifier.
            file_path: Path to the broker export file.
            plugin_name: Name of the registered broker plugin to use.
            field_mapping: Optional mapping from raw keys to canonical field names.

        Returns:
            A tuple of (list of successfully imported trades, import audit record).

        Raises:
            ImportValidationError: If the plugin is not registered, the file extension
                is unsupported, or field validation fails.
        """
        if plugin_name not in self._broker_plugins:
            raise ImportValidationError(
                f"Broker plugin '{plugin_name}' not registered"
            )

        plugin = self._broker_plugins[plugin_name]
        if file_path.suffix.lower() not in plugin.supported_extensions:
            raise ImportValidationError(
                f"Plugin '{plugin_name}' does not support extension '{file_path.suffix}'"
            )

        raw_rows = plugin.parse(file_path)
        mapping = field_mapping or {}

        return self._process_rows(
            portfolio_id=portfolio_id,
            raw_rows=raw_rows,
            mapping=mapping,
            source=TradeSource.BROKER_PLUGIN,
            file_name=file_path.name,
        )

    def _process_rows(
        self,
        portfolio_id: str,
        raw_rows: list[dict[str, Any]],
        mapping: dict[str, str],
        source: TradeSource,
        file_name: str | None = None,
    ) -> tuple[list[Trade], ImportRecord]:
        """Process raw rows: map fields, validate, create trades, and record audit.

        Args:
            portfolio_id: Portfolio identifier.
            raw_rows: List of raw row dictionaries from the import source.
            mapping: Mapping from raw keys to canonical field names.
            source: Source type of the import (CSV, Excel, broker plugin, etc.).
            file_name: Optional original file name for the audit record.

        Returns:
            A tuple of (list of successfully imported trades, import audit record).

        Raises:
            ImportValidationError: If any row fails validation. The audit record is
                included in the exception.
        """
        trades: list[Trade] = []
        errors: list[str] = []

        for idx, row in enumerate(raw_rows, start=1):
            try:
                mapped = _apply_mapping(row, mapping)
                row_hash = compute_raw_hash([row])
                trade = self._row_to_trade(portfolio_id, mapped, source, row_hash)
                trades.append(trade)
            except (TradeValidationError, KeyError, ValueError) as exc:
                errors.append(f"Row {idx}: {exc}")

        raw_hash = compute_raw_hash(raw_rows)
        if errors:
            record = self._record_import(
                portfolio_id=portfolio_id,
                source=source,
                trade_count=0,
                rejected_count=len(errors),
                file_name=file_name,
                raw_hash=raw_hash,
                errors=errors,
            )
            raise ImportValidationError(
                f"Import rejected: {len(errors)} row(s) failed validation",
                errors=errors,
                record=record,
            )

        record = self._record_import(
            portfolio_id=portfolio_id,
            source=source,
            trade_count=len(trades),
            rejected_count=len(errors),
            file_name=file_name,
            raw_hash=raw_hash,
            errors=errors,
        )
        return trades, record

    def _row_to_trade(
        self,
        portfolio_id: str,
        row: dict[str, Any],
        source: TradeSource,
        raw_hash: str | None = None,
    ) -> Trade:
        """Convert a mapped row into a validated ``Trade``.

        Args:
            portfolio_id: Portfolio identifier.
            row: Mapped row dictionary containing canonical trade fields.
            source: Source type for the trade.
            raw_hash: Optional raw row hash for audit linkage.

        Returns:
            The created ``Trade`` instance.

        Raises:
            TradeValidationError: If required fields are missing or invalid.
        """
        symbol = str(row.get("symbol", "")).strip()
        side = str(row.get("side", "")).strip().lower()
        quantity = float(row.get("quantity", 0))
        price = float(row.get("price", 0))
        traded_at_raw = row.get("traded_at")

        traded_at = _parse_datetime(traded_at_raw)
        if traded_at is None:
            raise TradeValidationError(
                f"Cannot parse traded_at: '{traded_at_raw}'"
            )

        validate_trade_fields(symbol, side, quantity, price, traded_at)

        return make_trade(
            portfolio_id=portfolio_id,
            symbol=symbol,
            side=TradeSide(side),
            quantity=quantity,
            price=price,
            traded_at=traded_at,
            fee=float(row.get("fee", 0) or 0),
            tax=float(row.get("tax", 0) or 0),
            source=source,
            raw_hash=raw_hash,
        )

    def _record_import(
        self,
        portfolio_id: str,
        source: TradeSource,
        trade_count: int,
        rejected_count: int,
        file_name: str | None = None,
        raw_hash: str | None = None,
        errors: list[str] | None = None,
    ) -> ImportRecord:
        """Create and store an import audit record.

        Args:
            portfolio_id: Portfolio identifier.
            source: Source type of the import.
            trade_count: Number of trades successfully imported.
            rejected_count: Number of rows rejected during validation.
            file_name: Optional original file name.
            raw_hash: Optional hash of the raw import data.
            errors: Optional list of per-row error messages.

        Returns:
            The created ``ImportRecord`` instance.
        """
        import uuid

        self._import_counter += 1
        record = ImportRecord(
            import_id=f"imp_{uuid.uuid4().hex[:12]}",
            portfolio_id=portfolio_id,
            source=source,
            file_name=file_name,
            trade_count=trade_count,
            rejected_count=rejected_count,
            raw_hash=raw_hash,
            errors=errors or [],
        )
        self._import_records.append(record)
        return record

    @property
    def import_records(self) -> list[ImportRecord]:
        """Return all import audit records.

        Returns:
            A list copy of all recorded ``ImportRecord`` instances.
        """
        return list(self._import_records)


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


_DEFAULT_CSV_MAPPING: dict[str, str] = {
    "symbol": "symbol",
    "side": "side",
    "quantity": "quantity",
    "price": "price",
    "traded_at": "traded_at",
    "fee": "fee",
    "tax": "tax",
    "note": "note",
}
"""Default mapping from CSV column names to canonical trade field names."""


def _apply_mapping(row: dict[str, Any], mapping: dict[str, str]) -> dict[str, Any]:
    """Map raw row keys to canonical field names according to ``mapping``.

    Args:
        row: Raw row dictionary from an import source.
        mapping: Mapping from raw key to canonical field name. Keys not present in
            ``mapping`` pass through unchanged.

    Returns:
        A new dictionary with mapped canonical keys.
    """
    mapped: dict[str, Any] = {}
    for raw_key, value in row.items():
        raw_key_str = str(raw_key).strip()
        target_key = mapping.get(raw_key_str, raw_key_str)
        mapped[target_key] = value
    return mapped


def _parse_datetime(value: Any) -> datetime | None:
    """Parse a value into a ``datetime`` using several common formats.

    Supported formats include ``%Y-%m-%d``, ``%Y-%m-%d %H:%M:%S``, ``%Y%m%d``,
    ``%Y/%m/%d``, and ``%Y/%m/%d %H:%M:%S``.

    Args:
        value: A date/time value of any type. ``None`` and empty strings return
            ``None``.

    Returns:
        A parsed ``datetime`` instance, or ``None`` if parsing fails.
    """
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value

    value_str = str(value).strip()
    formats = [
        "%Y-%m-%d",
        "%Y-%m-%d %H:%M:%S",
        "%Y%m%d",
        "%Y/%m/%d",
        "%Y/%m/%d %H:%M:%S",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(value_str[:19], fmt)
        except ValueError:
            continue
    return None
