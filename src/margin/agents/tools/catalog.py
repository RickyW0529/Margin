"""In-memory ToolCatalog for v1 tools."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from margin.agents.tools.specs import ToolCallRequest, ToolSpec

ToolHandler = Callable[[ToolCallRequest], dict[str, Any]]


@dataclass(frozen=True)
class RegisteredTool:
    """RegisteredTool.."""

    spec: ToolSpec
    handler: ToolHandler


class ToolCatalog:
    """ToolCatalog.."""

    def __init__(self) -> None:
        """Init .

        Returns:
            None: .
        """
        self._tools: dict[tuple[str, str], RegisteredTool] = {}

    def register(self, spec: ToolSpec, handler: ToolHandler) -> None:
        """Register.

        Args:
            spec: ToolSpec: .
            handler: ToolHandler: .

        Returns:
            None: .
        """
        self._tools[(spec.tool_name, spec.tool_version)] = RegisteredTool(
            spec=spec,
            handler=handler,
        )

    def get(self, tool_name: str, tool_version: str) -> RegisteredTool | None:
        """Get.

        Args:
            tool_name: str: .
            tool_version: str: .

        Returns:
            RegisteredTool | None: .
        """
        return self._tools.get((tool_name, tool_version))
