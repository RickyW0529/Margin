"""Migration coverage for the v0.2 data warehouse schema."""

from __future__ import annotations

from sqlalchemy.engine import make_url

from scripts.verify_migrations import verify_clean_database


def test_data_warehouse_tables_exist(database_url: str) -> None:
    """Alembic head includes the production warehouse tables required by v0.2."""
    url = make_url(database_url)
    result = verify_clean_database(
        database_url,
        database_name=f"{url.database}_warehouse_migration",
        drop_existing=True,
    )

    assert {
        "provider_endpoints",
        "data_sync_runs",
        "standardized_indicator_facts",
        "canonical_indicator_values",
        "security_industry_memberships",
        "corporate_actions",
    } <= set(result.tables)
