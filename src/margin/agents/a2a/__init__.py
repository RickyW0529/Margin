"""Official A2A 1.0 types and Margin's replaceable in-process transport."""

from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    AgentSkill,
    Artifact,
    Message,
    Part,
    Role,
    SendMessageRequest,
    SendMessageResponse,
    Task,
    TaskState,
    TaskStatus,
    VersionNotSupportedError,
)

from margin.agents.a2a.client import SyncA2AClient
from margin.agents.a2a.contracts import A2ATransport, AgentCall, AgentHandler, AgentResult
from margin.agents.a2a.data import (
    LOSSLESS_JSON_EXTENSION_URI,
    DataPart,
    make_data_artifact,
    make_data_part,
    read_data_part,
    read_message_data,
)
from margin.agents.a2a.errors import (
    AgentExecutionError,
    DuplicateAgentError,
    DuplicateTaskError,
    UnknownAgentError,
)
from margin.agents.a2a.transport import IN_PROCESS_BINDING, InProcessA2ATransport

__all__ = [
    "A2ATransport",
    "AgentCall",
    "AgentCapabilities",
    "AgentCard",
    "AgentExecutionError",
    "AgentHandler",
    "AgentInterface",
    "AgentResult",
    "AgentSkill",
    "Artifact",
    "DataPart",
    "DuplicateAgentError",
    "DuplicateTaskError",
    "IN_PROCESS_BINDING",
    "InProcessA2ATransport",
    "LOSSLESS_JSON_EXTENSION_URI",
    "Message",
    "Part",
    "Role",
    "SendMessageRequest",
    "SendMessageResponse",
    "SyncA2AClient",
    "Task",
    "TaskState",
    "TaskStatus",
    "UnknownAgentError",
    "VersionNotSupportedError",
    "make_data_part",
    "make_data_artifact",
    "read_data_part",
    "read_message_data",
]
