"""Backtest and analytical script query factory.

All SQL used by ``scripts/backtest_three_quant_pools_db.py`` and related
analytical scripts is defined here as ``TextClause`` constants, keeping the
script bodies free of inline SQL.
"""

from __future__ import annotations

from sqlalchemy import TextClause, text

from margin.sql.raw_statements import SECURITY_NAMES_ACTIVE

COVERAGE_BY_ENDPOINT = text(
    """
    select endpoint_code, indicator_id, count(*) cnt,
           min(event_at)::date min_date, max(event_at)::date max_date
    from standardized_indicator_facts
    where endpoint_code in ('daily_bar','adj_factor','daily_basic','index_weight')
    group by endpoint_code, indicator_id
    order by endpoint_code, indicator_id
    """
)

COVERAGE_BY_INDEX_CODE = text(
    """
    select json_value->>'index_code' index_code,
           count(*) cnt,
           min(event_at)::date min_date,
           max(event_at)::date max_date
    from standardized_indicator_facts
    where indicator_id='index_weight'
      and json_value ? 'index_code'
    group by json_value->>'index_code'
    order by index_code
    """
)

MARKET_PANEL_FACTS = text(
    """
    select security_id, event_at::date trade_date, indicator_id,
           numeric_value::float value
    from standardized_indicator_facts
    where indicator_id = any(:indicators)
      and event_at::date between :start_date and :end_date
      and numeric_value is not null
    """
)

DAILY_BASIC_FACTS = text(
    """
    select security_id, event_at::date trade_date, indicator_id,
           numeric_value::float value
    from standardized_indicator_facts
    where endpoint_code='daily_basic'
      and indicator_id = any(:indicators)
      and event_at::date between :start_date and :end_date
      and numeric_value is not null
    """
)

INDEX_WEIGHT_MEMBERS = text(
    """
    select security_id, event_at::date trade_date,
           json_value->>'index_code' index_code
    from standardized_indicator_facts
    where indicator_id='index_weight'
      and json_value ? 'index_code'
      and event_at::date between :start_date and :end_date
      and json_value->>'index_code' = any(:index_codes)
    """
)

COMPANY_POOL_SNAPSHOTS = text(
    """
    select snapshot_id, business_at, known_at, member_count
    from company_pool_snapshots
    where pool_code in ('ALL_A', 'ALL_A_NON_ST')
    order by business_at, created_at
    """
)

COMPANY_POOL_MEMBERS = text(
    """
    select snapshot_id, security_id
    from company_pool_members
    where included = true
    """
)


def coverage_by_endpoint() -> TextClause:
    """Return endpoint/indicator coverage summary for the backtest window.

    Returns:
        TextClause: .
    """
    return COVERAGE_BY_ENDPOINT


def coverage_by_index_code() -> TextClause:
    """Return index_weight coverage grouped by index code.

    Returns:
        TextClause: .
    """
    return COVERAGE_BY_INDEX_CODE


def market_panel_facts() -> TextClause:
    """Return market bar facts (close, amount, adj_factor) for a date range.

    Returns:
        TextClause: .
    """
    return MARKET_PANEL_FACTS


def daily_basic_facts() -> TextClause:
    """Return daily_basic valuation facts for a date range.

    Returns:
        TextClause: .
    """
    return DAILY_BASIC_FACTS


def index_weight_members() -> TextClause:
    """Return index member security IDs from index_weight facts.

    Returns:
        TextClause: .
    """
    return INDEX_WEIGHT_MEMBERS


def company_pool_snapshots() -> TextClause:
    """Return all company pool snapshot headers.

    Returns:
        TextClause: .
    """
    return COMPANY_POOL_SNAPSHOTS


def company_pool_members() -> TextClause:
    """Return all included company pool members.

    Returns:
        TextClause: .
    """
    return COMPANY_POOL_MEMBERS


def security_names_active() -> TextClause:
    """Return active security IDs with names.

    Returns:
        TextClause: .
    """
    return SECURITY_NAMES_ACTIVE
