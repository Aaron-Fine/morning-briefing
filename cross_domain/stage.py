"""Stage orchestration for cross-domain synthesis."""

import logging

from morning_digest.llm import call_llm
from morning_digest.validate import validate_stage_output

from cross_domain.parse import (
    _fallback_outputs,
    _normalize_cross_domain_plan,
    _validated_output,
)
from cross_domain.prompt import (
    _execute_user_content,
    _plan_user_content,
    execute_prompt,
    plan_prompt,
)

log = logging.getLogger(__name__)


def _resolve_turn_model_config(
    base_model_config: dict | None, stage_cfg: dict | None, turn_name: str
) -> dict | None:
    if not base_model_config:
        return None

    turn_overrides = (stage_cfg or {}).get("turns", {}).get(turn_name, {})
    return {**base_model_config, **turn_overrides}


def _call_turn_json(
    prompt: str,
    user_content: str,
    model_config: dict | None,
    turn_name: str,
) -> dict:
    try:
        return call_llm(
            prompt,
            user_content,
            model_config,
            max_retries=2,
            json_mode=True,
            stream=True,
        )
    except Exception as exc:
        log.warning(
            f"cross_domain: {turn_name} turn failed with streaming, retrying once: {exc}"
        )
        return call_llm(
            prompt,
            user_content,
            model_config,
            max_retries=2,
            json_mode=True,
            stream=False,
        )


def run(
    context: dict, config: dict, model_config: dict | None = None, **kwargs
) -> dict:
    """Run cross-domain synthesis and return the editorial product."""
    domain_analysis = context.get("domain_analysis", {})
    seam_data = context.get("seam_data", {})
    raw_sources = context.get("raw_sources", {})

    effective_config = model_config or config.get("llm", {})
    stage_cfg = kwargs.get("stage_cfg") or {}
    plan_config = _resolve_turn_model_config(effective_config, stage_cfg, "plan")
    execute_config = _resolve_turn_model_config(effective_config, stage_cfg, "execute")

    digest_cfg = config.get("digest", {})
    deep_dive_count = digest_cfg.get("deep_dives", {}).get("count", 2)
    worth_reading_count = digest_cfg.get("worth_reading", {}).get("count", 3)
    connection_count = 3

    has_items = any(
        isinstance(v, dict) and v.get("items") for v in domain_analysis.values()
    )
    if not has_items:
        log.warning("cross_domain: no domain analysis items — returning passthrough")
        return _fallback_outputs(domain_analysis, reason="no_domain_analysis_items")

    cross_domain_plan = context.get("cross_domain_plan")
    try:
        if context.get("cross_domain_from_plan") and isinstance(cross_domain_plan, dict):
            log.info("Stage: cross_domain — reusing same-day cross_domain_plan")
        else:
            log.info("Stage: cross_domain — running Turn 1 planning...")
            cross_domain_plan = _call_turn_json(
                plan_prompt(deep_dive_count, worth_reading_count, connection_count),
                _plan_user_content(
                    domain_analysis,
                    seam_data,
                    raw_sources,
                    context.get("previous_cross_domain"),
                ),
                plan_config,
                "plan",
            )
            cross_domain_plan = _normalize_cross_domain_plan(
                cross_domain_plan,
                deep_dive_count=deep_dive_count,
                worth_reading_count=worth_reading_count,
                connection_count=connection_count,
            )

        log.info("Stage: cross_domain — running Turn 2 execution...")
        result = _call_turn_json(
            execute_prompt(deep_dive_count, worth_reading_count),
            _execute_user_content(
                domain_analysis,
                seam_data,
                raw_sources,
                cross_domain_plan,
                context.get("previous_cross_domain"),
            ),
            execute_config,
            "execute",
        )
    except Exception as e:
        log.error(f"cross_domain: LLM call failed: {e}")
        return _fallback_outputs(
            domain_analysis,
            cross_domain_plan if isinstance(cross_domain_plan, dict) else None,
            reason="llm_call_failed",
            message=str(e),
        )

    if not isinstance(result, dict):
        log.warning("cross_domain: LLM returned non-dict, falling back to passthrough")
        return _fallback_outputs(
            domain_analysis,
            cross_domain_plan,
            reason="non_dict_llm_output",
        )

    result = _validated_output(result, domain_analysis, raw_sources, config)
    result = validate_stage_output(
        result,
        raw_sources,
        "cross_domain",
        collect_diagnostics=True,
        domain_analysis=domain_analysis,
    )
    validation_diagnostics = result.pop(
        "_validation_diagnostics",
        {"stage": "cross_domain", "issue_count": 0, "issues": []},
    )

    n_glance = len(result["at_a_glance"])
    n_dives = len(result["deep_dives"])
    n_connections = len(result["cross_domain_connections"])
    log.info(
        f"  cross_domain: {n_glance} at-a-glance, {n_dives} deep dives, "
        f"{n_connections} cross-domain connections"
    )

    return {
        "cross_domain_plan": cross_domain_plan,
        "cross_domain_output": result,
        "validation_diagnostics": validation_diagnostics,
    }
