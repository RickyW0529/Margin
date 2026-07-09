"""Fine-grained Agent capability policy enums."""

from __future__ import annotations

from enum import StrEnum


class DataAccessPolicy(StrEnum):
    """Data scopes that an Agent may read.."""

    NO_DATA = "no_data"
    READ_CHAT_SUMMARY = "read_chat_summary"
    READ_DASHBOARD = "read_dashboard"
    READ_ANALYSIS_MART = "read_analysis_mart"
    READ_EVIDENCE = "read_evidence"
    READ_VECTOR_INDEX = "read_vector_index"
    READ_PROVIDER_STATUS = "read_provider_status"
    READ_RAW_FORBIDDEN = "read_raw_forbidden"


class ProductionWritePolicy(StrEnum):
    """Write scopes that an Agent may use.."""

    NONE = "none"
    WRITE_CONTEXT_ONLY = "write_context_only"
    WRITE_DASHBOARD_PROJECTION = "write_dashboard_projection"
    WRITE_ANALYSIS_MART = "write_analysis_mart"
    WRITE_PROVIDER_CONFIG = "write_provider_config"
    WRITE_SCHEDULE = "write_schedule"
    WRITE_BACKFILL_STATE = "write_backfill_state"


class ToolPolicy(StrEnum):
    """Tool execution scopes available to an Agent.."""

    NO_TOOLS = "no_tools"
    READ_ONLY_TOOLS = "read_only_tools"
    RETRIEVAL_TOOLS = "retrieval_tools"
    DATA_SYNC_TOOLS = "data_sync_tools"
    QUANT_TOOLS = "quant_tools"
    SANDBOX_TOOLS = "sandbox_tools"
