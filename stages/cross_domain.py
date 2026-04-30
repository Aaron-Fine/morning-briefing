"""Compatibility module for the cross-domain synthesis stage.

The implementation lives in the top-level ``cross_domain`` package so prompt
construction, parsing/normalization, and stage orchestration can evolve
independently. This module preserves the configured ``stages.cross_domain`` path.
"""

from morning_digest.llm import call_llm

from cross_domain.parse import (
    _TAG_KEYWORDS,
    _TAG_LABELS,
    _VALID_TAGS,
    _cap_at_a_glance_items,
    _empty_cross_domain_plan,
    _empty_output,
    _fallback_outputs,
    _fallback_validation_diagnostics,
    _normalize_cross_domain_plan,
    _normalize_tag,
    _validated_output,
)
from cross_domain.prompt import (
    _EXECUTE_PROMPT,
    _PLAN_PROMPT,
    _SYSTEM_PROMPT,
    _build_input,
    _execute_user_content,
    _plan_user_content,
)
from cross_domain.stage import _call_turn_json, _resolve_turn_model_config
from cross_domain import stage as _stage

__all__ = [
    "_EXECUTE_PROMPT",
    "_PLAN_PROMPT",
    "_SYSTEM_PROMPT",
    "_TAG_KEYWORDS",
    "_TAG_LABELS",
    "_VALID_TAGS",
    "_build_input",
    "_call_turn_json",
    "_cap_at_a_glance_items",
    "_empty_cross_domain_plan",
    "_empty_output",
    "_execute_user_content",
    "_fallback_outputs",
    "_fallback_validation_diagnostics",
    "_normalize_cross_domain_plan",
    "_normalize_tag",
    "_plan_user_content",
    "_resolve_turn_model_config",
    "_validated_output",
    "call_llm",
    "run",
]


def run(
    context: dict, config: dict, model_config: dict | None = None, **kwargs
) -> dict:
    """Run cross-domain synthesis through the split stage implementation."""
    original_call_llm = _stage.call_llm
    _stage.call_llm = call_llm
    try:
        return _stage.run(context, config, model_config, **kwargs)
    finally:
        _stage.call_llm = original_call_llm
