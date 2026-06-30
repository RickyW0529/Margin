"""Tests for built-in strategy templates.

This module validates that built-in strategy templates contain expected
configuration and that the template listing API returns the correct entries.
"""

from __future__ import annotations

from margin.strategy.templates import BUILTIN_TEMPLATES, list_templates


def test_value_quality_template_has_universe():
    """Verify the value_quality template includes a default universe member.

    Returns:
        None.
    """
    template = BUILTIN_TEMPLATES["value_quality"]
    assert "000001.SZ" in template.config.universe


def test_custom_template_is_minimal():
    """Verify the custom template has a minimal but valid horizon configuration.

    Returns:
        None.
    """
    template = BUILTIN_TEMPLATES["custom"]
    assert template.config.horizon >= 1


def test_list_templates_returns_six_entries():
    """Verify list_templates returns six entries including value_quality and custom.

    Returns:
        None.
    """
    metas = list_templates()
    assert len(metas) == 6
    ids = {m.template_id for m in metas}
    assert "value_quality" in ids
    assert "custom" in ids
