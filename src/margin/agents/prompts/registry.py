"""PromptBundle registry."""

from __future__ import annotations

from margin.agents.prompts.bundles import PromptBundle


class PromptRegistry:
    """PromptRegistry.."""

    def __init__(self) -> None:
        """Init .

        Returns:
            None: .
        """
        self._bundles: dict[str, PromptBundle] = {}
        self._active_by_type: dict[str, str] = {}

    def register_bundle(self, bundle: PromptBundle, *, active: bool = False) -> None:
        """Register bundle.

        Args:
            bundle: PromptBundle: .
            active: bool: .

        Returns:
            None: .
        """
        self._bundles[bundle.prompt_bundle_id] = bundle
        if active:
            self._active_by_type[bundle.target_agent_type] = bundle.prompt_bundle_id

    def get_active_bundle(self, target_agent_type: str) -> PromptBundle:
        """Get active bundle.

        Args:
            target_agent_type: str: .

        Returns:
            PromptBundle: .
        """
        try:
            bundle_id = self._active_by_type[target_agent_type]
            return self._bundles[bundle_id]
        except KeyError as exc:
            raise KeyError(f"active prompt bundle not found: {target_agent_type}") from exc
