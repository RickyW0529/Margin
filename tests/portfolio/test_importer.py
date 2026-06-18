"""Tests for position data models and the trade importer (0201 acceptance)."""

from __future__ import annotations

import csv
import io
from datetime import datetime
from pathlib import Path

import pytest

from margin.portfolio.importer import (
    BrokerImportPlugin,
    ImportValidationError,
    TradeImporter,
    TradeValidationError,
    compute_raw_hash,
    validate_trade_fields,
)
from margin.portfolio.models import (
    ImportRecord,
    TradeSide,
    TradeSource,
    make_trade,
)


class TestTradeModel:
    """Tests for the trade model factory and frozen trade behavior."""

    def test_make_trade_standardizes_symbol(self):
        """Verify that make_trade appends the exchange suffix to a raw symbol."""
        t = make_trade(
            portfolio_id="pf_1",
            symbol="000001",
            side=TradeSide.BUY,
            quantity=100,
            price=10.5,
            traded_at=datetime(2026, 6, 17),
        )
        assert t.symbol == "000001.SZ"

    def test_trade_amount_auto_calculated(self):
        """Verify that the trade amount includes quantity, price, fee, and tax."""
        t = make_trade(
            portfolio_id="pf_1",
            symbol="000001.SZ",
            side=TradeSide.BUY,
            quantity=100,
            price=10.0,
            traded_at=datetime(2026, 6, 17),
            fee=5.0,
            tax=3.0,
        )
        assert t.amount == 100 * 10.0 + 5.0 + 3.0

    def test_trade_is_frozen(self):
        """Verify that trade instances are immutable after creation."""
        t = make_trade(
            portfolio_id="pf_1",
            symbol="000001.SZ",
            side=TradeSide.BUY,
            quantity=100,
            price=10.0,
            traded_at=datetime(2026, 6, 17),
        )
        with pytest.raises(Exception):
            t.quantity = 200


class TestValidateTradeFields:
    """Tests for field-level validation of trade input data."""

    def test_valid(self):
        """Verify that valid trade fields pass validation without raising."""
        validate_trade_fields("000001.SZ", "buy", 100, 10.0, datetime(2026, 6, 17))

    def test_empty_symbol(self):
        """Verify that an empty symbol raises a TradeValidationError."""
        with pytest.raises(TradeValidationError, match="symbol"):
            validate_trade_fields("", "buy", 100, 10.0, datetime(2026, 6, 17))

    def test_invalid_side(self):
        """Verify that an unsupported side value raises a TradeValidationError."""
        with pytest.raises(TradeValidationError, match="side"):
            validate_trade_fields("000001.SZ", "hold", 100, 10.0, datetime(2026, 6, 17))

    def test_zero_quantity(self):
        """Verify that a zero quantity raises a TradeValidationError."""
        with pytest.raises(TradeValidationError, match="quantity"):
            validate_trade_fields("000001.SZ", "buy", 0, 10.0, datetime(2026, 6, 17))

    def test_negative_price(self):
        """Verify that a negative price raises a TradeValidationError."""
        with pytest.raises(TradeValidationError, match="price"):
            validate_trade_fields("000001.SZ", "buy", 100, -1.0, datetime(2026, 6, 17))

    def test_future_date(self):
        """Verify that a future trade date raises a TradeValidationError."""
        with pytest.raises(TradeValidationError, match="future"):
            validate_trade_fields(
                "000001.SZ", "buy", 100, 10.0, datetime(2099, 1, 1)
            )


class TestComputeRawHash:
    """Tests for the deterministic raw-content hash helper."""

    def test_deterministic(self):
        """Verify that hashing the same rows produces identical digests."""
        rows = [{"a": 1}, {"b": 2}]
        assert compute_raw_hash(rows) == compute_raw_hash(rows)

    def test_different_rows(self):
        """Verify that differing row content yields different hashes."""
        assert compute_raw_hash([{"a": 1}]) != compute_raw_hash([{"a": 2}])

    def test_starts_with_sha256(self):
        """Verify that the hash digest is prefixed with the algorithm name."""
        assert compute_raw_hash([]).startswith("sha256:")


class TestTradeImporterManual:
    """Tests for manually adding individual trades through TradeImporter."""

    def test_add_trade_manual_success(self):
        """Verify that a valid manual trade is created with the correct source."""
        importer = TradeImporter()
        trade = importer.add_trade_manual(
            portfolio_id="pf_1",
            symbol="000001.SZ",
            side="buy",
            quantity=1000,
            price=10.5,
            traded_at=datetime(2026, 6, 17),
        )
        assert trade.symbol == "000001.SZ"
        assert trade.side == TradeSide.BUY
        assert trade.source == TradeSource.MANUAL
        assert trade.quantity == 1000

    def test_add_trade_manual_validation_error(self):
        """Verify that invalid manual trade input raises a TradeValidationError."""
        importer = TradeImporter()
        with pytest.raises(TradeValidationError):
            importer.add_trade_manual(
                portfolio_id="pf_1",
                symbol="",
                side="buy",
                quantity=100,
                price=10.0,
                traded_at=datetime(2026, 6, 17),
            )

    def test_manual_import_record_created(self):
        """Verify that adding a manual trade records a successful import record."""
        importer = TradeImporter()
        importer.add_trade_manual(
            portfolio_id="pf_1",
            symbol="000001.SZ",
            side="buy",
            quantity=100,
            price=10.0,
            traded_at=datetime(2026, 6, 17),
        )
        records = importer.import_records
        assert len(records) == 1
        assert records[0].source == TradeSource.MANUAL
        assert records[0].trade_count == 1
        assert records[0].rejected_count == 0


class TestTradeImporterCSV:
    """Tests for importing trades from CSV content, files, and custom field mappings."""

    def _make_csv(self, rows: list[dict]) -> str:
        """Build a CSV string from row dictionaries using the standard trade layout.

        Args:
            rows: Dictionaries containing values for the standard trade columns.

        Returns:
            A UTF-8 CSV string with a header and one row per dictionary.
        """
        output = io.StringIO()
        writer = csv.DictWriter(
            output,
            fieldnames=["symbol", "side", "quantity", "price", "traded_at", "fee", "tax"],
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
        return output.getvalue()

    def test_import_csv_success(self):
        """Verify that a valid CSV produces trades and a matching import record."""
        importer = TradeImporter()
        content = self._make_csv([
            {
                "symbol": "000001.SZ", "side": "buy",
                "quantity": "1000", "price": "10.5",
                "traded_at": "2026-06-17", "fee": "5", "tax": "3",
            },
            {
                "symbol": "600000.SH", "side": "buy",
                "quantity": "500", "price": "8.0",
                "traded_at": "2026-06-17", "fee": "0", "tax": "0",
            },
        ])

        trades, record = importer.import_csv_bytes("pf_1", content)

        assert len(trades) == 2
        assert trades[0].symbol == "000001.SZ"
        assert trades[1].symbol == "600000.SH"
        assert trades[0].source == TradeSource.CSV
        assert record.trade_count == 2
        assert record.rejected_count == 0
        assert record.raw_hash is not None
        assert record.raw_hash.startswith("sha256:")
        assert trades[0].raw_hash is not None
        assert trades[0].raw_hash.startswith("sha256:")
        assert trades[0].raw_hash != trades[1].raw_hash

    def test_import_csv_with_errors_rejects_entire_file(self):
        """Verify that validation errors in a CSV reject the whole file and record errors."""
        importer = TradeImporter()
        content = self._make_csv([
            {
                "symbol": "000001.SZ", "side": "buy",
                "quantity": "100", "price": "10",
                "traded_at": "2026-06-17", "fee": "0", "tax": "0",
            },
            {
                "symbol": "", "side": "buy",
                "quantity": "100", "price": "10",
                "traded_at": "2026-06-17", "fee": "0", "tax": "0",
            },
            {
                "symbol": "600000.SH", "side": "bad",
                "quantity": "100", "price": "10",
                "traded_at": "2026-06-17", "fee": "0", "tax": "0",
            },
        ])

        with pytest.raises(ImportValidationError) as exc_info:
            importer.import_csv_bytes("pf_1", content)

        record = exc_info.value.record
        assert record is not None
        assert record.trade_count == 0
        assert record.rejected_count == 2
        assert len(record.errors) == 2
        assert "Row 2" in record.errors[0]
        assert "Row 3" in record.errors[1]
        assert importer.import_records == [record]

    def test_import_csv_file(self, tmp_path):
        """Verify that import_csv reads a file and preserves the file name in the record."""
        importer = TradeImporter()
        csv_path = tmp_path / "trades.csv"
        csv_path.write_text(
            "symbol,side,quantity,price,traded_at,fee,tax\n"
            "000001.SZ,buy,1000,10.5,2026-06-17,5,3\n",
            encoding="utf-8",
        )

        trades, record = importer.import_csv("pf_1", csv_path)

        assert len(trades) == 1
        assert record.file_name == "trades.csv"

    def test_import_csv_field_mapping(self):
        """Verify that custom CSV headers can be mapped to the standard trade fields."""
        importer = TradeImporter()
        content = "code,direction,qty,px,date\n000001.SZ,buy,1000,10.5,2026-06-17\n"
        mapping = {
            "code": "symbol",
            "direction": "side",
            "qty": "quantity",
            "px": "price",
            "date": "traded_at",
        }

        trades, record = importer.import_csv_bytes("pf_1", content, mapping)

        assert len(trades) == 1
        assert trades[0].symbol == "000001.SZ"
        assert trades[0].quantity == 1000.0


class TestBrokerPlugin:
    """Tests for broker plugin registration and broker-specific imports."""

    def test_broker_plugin_import(self, tmp_path):
        """Verify that a registered broker plugin can parse and import trades."""
        class MockBrokerPlugin(BrokerImportPlugin):
            """Minimal broker plugin returning a single parsed trade row."""

            @property
            def name(self) -> str:
                return "mock_broker"

            @property
            def supported_extensions(self) -> list[str]:
                return [".csv"]

            def parse(self, file_path: Path) -> list[dict]:
                return [
                    {
                        "symbol": "000001.SZ", "side": "buy",
                        "quantity": 500, "price": 10.0,
                        "traded_at": "2026-06-15",
                    },
                ]

        importer = TradeImporter()
        importer.register_broker_plugin(MockBrokerPlugin())

        csv_path = tmp_path / "broker_export.csv"
        csv_path.write_text("dummy", encoding="utf-8")

        trades, record = importer.import_broker("pf_1", csv_path, "mock_broker")

        assert len(trades) == 1
        assert trades[0].source == TradeSource.BROKER_PLUGIN
        assert record.source == TradeSource.BROKER_PLUGIN
        assert record.file_name == "broker_export.csv"

    def test_unregistered_plugin_raises(self, tmp_path):
        """Verify that importing with an unknown broker name raises an error."""
        importer = TradeImporter()
        csv_path = tmp_path / "test.csv"
        csv_path.write_text("dummy", encoding="utf-8")

        with pytest.raises(ImportValidationError, match="not registered"):
            importer.import_broker("pf_1", csv_path, "nonexistent")

    def test_unsupported_extension_raises(self, tmp_path):
        """Verify that a broker plugin rejects files with unsupported extensions."""
        class MockPlugin(BrokerImportPlugin):
            """Broker plugin that only accepts CSV files."""

            @property
            def name(self) -> str:
                return "csv_only"

            @property
            def supported_extensions(self) -> list[str]:
                return [".csv"]

            def parse(self, file_path: Path) -> list[dict]:
                return []

        importer = TradeImporter()
        importer.register_broker_plugin(MockPlugin())

        txt_path = tmp_path / "test.txt"
        txt_path.write_text("dummy", encoding="utf-8")

        with pytest.raises(ImportValidationError, match="extension"):
            importer.import_broker("pf_1", txt_path, "csv_only")


class TestImportRecord:
    """Tests for the immutable import record model."""

    def test_frozen(self):
        """Verify that ImportRecord instances are immutable after creation."""
        record = ImportRecord(
            import_id="imp_1",
            portfolio_id="pf_1",
            source=TradeSource.CSV,
            trade_count=10,
        )
        with pytest.raises(Exception):
            record.trade_count = 999
