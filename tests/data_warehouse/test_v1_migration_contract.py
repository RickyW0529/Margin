"""test_v1_migration_contract module."""

from __future__ import annotations

from pathlib import Path

VERSIONS_DIR = Path("alembic/versions")


def _read(name: str) -> str:
    """Execute _read logic.

    Args:
        name: str: .

    Returns:
        str: .
    """
    return VERSIONS_DIR.joinpath(name).read_text(encoding="utf-8")


def test_v1_warehouse_migration_files_are_chained() -> None:
    """test_v1_warehouse_migration_files_are_chained implementation.

    Returns:
        None: .
    """
    assert 'down_revision = "20260708_0052_runtime_config"' in _read(
        "20260708_0053_v1_warehouse_schemas.py"
    )
    assert 'revision = "20260708_0053_v1_schemas"' in _read("20260708_0053_v1_warehouse_schemas.py")
    assert 'down_revision = "20260708_0053_v1_schemas"' in _read("20260708_0054_raw_ods_landing.py")
    assert 'down_revision = "20260708_0054_raw_ods"' in _read("20260708_0055_vault_pit_tables.py")
    assert 'down_revision = "20260708_0055_vault_pit"' in _read(
        "20260708_0056_kimball_mart_app_tables.py"
    )


def test_v1_warehouse_schemas_are_declared() -> None:
    """test_v1_warehouse_schemas_are_declared implementation.

    Returns:
        None: .
    """
    migration = _read("20260708_0053_v1_warehouse_schemas.py")

    for schema in (
        "raw_meta",
        "source_akshare",
        "source_filing",
        "source_news",
        "source_web",
        "source_doc",
        "ods",
        "vault",
        "mart_dw",
        "mart",
        "app",
        "agent",
        "tool",
        "prompt",
        "ops",
        "platform",
    ):
        assert f"CREATE SCHEMA IF NOT EXISTS {schema}" in migration


def test_raw_ods_tables_have_snapshot_lineage_and_available_at() -> None:
    """test_raw_ods_tables_have_snapshot_lineage_and_available_at implementation.

    Returns:
        None: .
    """
    migration = _read("20260708_0054_raw_ods_landing.py")

    for required in (
        "raw_data_snapshots",
        "raw_document_snapshots",
        "ods_daily_quote_raw",
        "raw_snapshot_id",
        "fetched_at",
        "available_at",
        "natural_key_hash",
        "revision_hash",
    ):
        assert required in migration


def test_vault_pit_tables_force_available_at() -> None:
    """test_vault_pit_tables_force_available_at implementation.

    Returns:
        None: .
    """
    migration = _read("20260708_0055_vault_pit_tables.py")

    for required in (
        "hub_security",
        "hub_company",
        "sat_daily_quote",
        "sat_financial_indicator",
        "pit_security_day",
        "pit_financial_statement",
        "pit_stock_pool_snapshot",
        "available_at",
        "published_at",
        "raw_snapshot_id",
    ):
        assert required in migration


def test_kimball_mart_app_tables_include_pit_safe_facts() -> None:
    """test_kimball_mart_app_tables_include_pit_safe_facts implementation.

    Returns:
        None: .
    """
    migration = _read("20260708_0056_kimball_mart_app_tables.py")

    for required in (
        "dim_stock",
        "daily_market_fact",
        "factor_fact",
        "factor_panel",
        "quant_candidate_mart",
        "stock_analysis_mart",
        "backtest_panel",
        "app.dashboard_items_v2",
        "available_at",
        "feature_snapshot_id",
        "universe_snapshot_id",
    ):
        assert required in migration
