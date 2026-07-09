"""Raw SQL text clauses shared across health checks, migration tools, and scripts.

These are PostgreSQL-native statements that cannot be expressed as SQLAlchemy ORM
query builders (DDL, pg_catalog introspection, complex CTE repairs).
"""

from __future__ import annotations

from sqlalchemy import text

ALEMBIC_VERSION = text("SELECT version_num FROM alembic_version")

PGVECTOR_EXTENSION = text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")

NON_SYSTEM_TABLES = text(
    "SELECT schemaname, tablename FROM pg_tables "
    "WHERE schemaname NOT IN ('pg_catalog', 'information_schema') "
    "UNION ALL "
    "SELECT schemaname, matviewname AS tablename FROM pg_matviews "
    "WHERE schemaname NOT IN ('pg_catalog', 'information_schema')"
)

TERMINATE_DATABASE_CONNECTIONS = text(
    "SELECT pg_terminate_backend(pid) "
    "FROM pg_stat_activity "
    "WHERE datname = :database_name AND pid <> pg_backend_pid()"
)

OUTBOX_PENDING_COUNT = text(
    "SELECT count(*) FROM transactional_outbox WHERE state IN ('pending', 'failed_retryable')"
)

ACTIVE_PROVIDER_CONFIG_COUNT = text(
    "SELECT count(*) FROM provider_config_versions WHERE lifecycle = 'active'"
)

RETRYABLE_STEP_COUNT = text(
    "SELECT count(*) FROM orchestration_step_attempts "
    "WHERE state IN ('pending', 'failed_retryable', "
    "'waiting_rate_limit', 'waiting_budget')"
)

WAITING_BUDGET_COUNT = text(
    "SELECT count(*) FROM orchestration_step_attempts WHERE state = 'waiting_budget'"
)

WAITING_RATE_LIMIT_COUNT = text(
    "SELECT count(*) FROM orchestration_step_attempts WHERE state = 'waiting_rate_limit'"
)

FAILED_RETRYABLE_COUNT = text(
    "SELECT count(*) FROM orchestration_step_attempts WHERE state = 'failed_retryable'"
)

SECURITY_NAMES_ACTIVE = text("select security_id, name from securities where system_to is null")

INDEX_WEIGHT_MATCH = text(
    """
    with matched as (
        select f.fact_id,
               max(s.raw_payload->>'index_code') as index_code,
               count(distinct s.raw_payload->>'index_code') as index_count
        from standardized_indicator_facts f
        join source_tushare.ts_index_weight s
          on s.symbol = f.security_id
         and s.business_date = f.event_at::date
         and round(((s.raw_payload->>'weight')::numeric / 100.0), 10)
             = round(f.numeric_value, 10)
        where f.endpoint_code = 'index_weight'
          and f.indicator_id = 'index_weight'
          and (
              jsonb_typeof(f.json_value) is distinct from 'object'
              or not (f.json_value ? 'index_code')
          )
        group by f.fact_id
    ),
    safe_matches as (
        select fact_id, index_code
        from matched
        where index_count = 1 and index_code is not null
    )
    select
        (select count(*)
         from standardized_indicator_facts
         where endpoint_code = 'index_weight'
           and indicator_id = 'index_weight'
           and (
               jsonb_typeof(json_value) is distinct from 'object'
               or not (json_value ? 'index_code')
           )) as missing_count,
        (select count(*) from safe_matches) as safe_match_count,
        (select count(*) from matched where index_count > 1) as ambiguous_count
    """
)

INDEX_WEIGHT_UPDATE_FACTS = text(
    """
    with matched as (
        select f.fact_id,
               max(s.raw_payload->>'index_code') as index_code,
               count(distinct s.raw_payload->>'index_code') as index_count
        from standardized_indicator_facts f
        join source_tushare.ts_index_weight s
          on s.symbol = f.security_id
         and s.business_date = f.event_at::date
         and round(((s.raw_payload->>'weight')::numeric / 100.0), 10)
             = round(f.numeric_value, 10)
        where f.endpoint_code = 'index_weight'
          and f.indicator_id = 'index_weight'
          and (
              jsonb_typeof(f.json_value) is distinct from 'object'
              or not (f.json_value ? 'index_code')
          )
        group by f.fact_id
    ),
    safe_matches as (
        select fact_id, index_code
        from matched
        where index_count = 1 and index_code is not null
    )
    update standardized_indicator_facts f
    set json_value = (
            case
                when jsonb_typeof(f.json_value) = 'object'
                    then f.json_value
                else '{}'::jsonb
            end
        )
            || jsonb_build_object('index_code', safe_matches.index_code),
        lineage = coalesce(f.lineage, '{}'::jsonb)
            || jsonb_build_object(
                'metadata_repair',
                'index_weight_source_landing_v1'
            )
    from safe_matches
    where f.fact_id = safe_matches.fact_id
    """
)

INDEX_WEIGHT_UPDATE_CANONICAL = text(
    """
    update canonical_indicator_values c
    set json_value = f.json_value
    from standardized_indicator_facts f
    where c.selected_fact_id = f.fact_id
      and c.indicator_id = 'index_weight'
      and jsonb_typeof(f.json_value) = 'object'
      and f.json_value ? 'index_code'
      and (
          jsonb_typeof(c.json_value) is distinct from 'object'
          or not (c.json_value ? 'index_code')
      )
    """
)

INDEX_WEIGHT_VERIFY = text(
    """
    select json_value->>'index_code' as index_code,
           count(*) as cnt,
           min(event_at)::date as min_date,
           max(event_at)::date as max_date
    from standardized_indicator_facts
    where endpoint_code = 'index_weight'
      and indicator_id = 'index_weight'
      and json_value ? 'index_code'
    group by json_value->>'index_code'
    order by index_code
    """
)
