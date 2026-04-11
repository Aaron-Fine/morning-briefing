#!/usr/bin/env python3
"""Three-way cross-domain model comparison test.

Runs the same fixture through Kimi K2.5, Qwen3.6 Plus, and Claude Sonnet 4,
then compares outputs on:
  - JSON structural validity
  - Tag normalization compliance
  - URL validation
  - Deep dive quality (HTML structure, paragraph count)
  - Worth reading selection
  - Cross-domain connection discovery
  - Bias indicators (framing of contested narratives, source attribution patterns)

Usage:
    python tests/test_cross_domain_models.py              # run all three
    python tests/test_cross_domain_models.py --model kimi # run one
    python tests/test_cross_domain_models.py --dry-run    # print prompts only
"""

import json
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from stages.cross_domain import run as cross_domain_run

# Note: _SYSTEM_PROMPT, _build_input (from stages.cross_domain) and call_llm
# (from llm) are available for interactive debugging but not used in the
# automated comparison report

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Model configurations to test
# ---------------------------------------------------------------------------

MODELS = {
    "kimi": {
        "label": "Kimi K2.5 (Fireworks)",
        "config": {
            "provider": "fireworks",
            "model": "accounts/fireworks/models/kimi-k2p5",
            "max_tokens": 16000,
            "temperature": 0.3,
        },
    },
    "qwen36plus": {
        "label": "Qwen3.6 Plus (Fireworks)",
        "config": {
            "provider": "fireworks",
            "model": "accounts/fireworks/models/qwen3p6-plus",
            "max_tokens": 16000,
            "temperature": 0.3,
        },
    },
    "claude": {
        "label": "Claude Sonnet 4 (Anthropic)",
        "config": {
            "provider": "anthropic",
            "model": "claude-sonnet-4-6",
            "max_tokens": 16000,
            "temperature": 0.3,
        },
    },
    "claude_opus": {
        "label": "Claude Opus 4 (Anthropic)",
        "config": {
            "provider": "anthropic",
            "model": "claude-opus-4-0",
            "max_tokens": 16000,
            "temperature": 0.3,
        },
    },
    "claude_opus46": {
        "label": "Claude Opus 4.6 (Anthropic)",
        "config": {
            "provider": "anthropic",
            "model": "claude-opus-4-6",
            "max_tokens": 16000,
            "temperature": 0.3,
        },
    },
}

# ---------------------------------------------------------------------------
# Bias-revealing test scenarios embedded in the fixture
# ---------------------------------------------------------------------------

# These are the specific things we'll check in each model's output to detect
# systematic bias or framing preferences.

BIAS_CHECKS = {
    "china_taiwan_framing": {
        "description": "How does the model frame China-Taiwan military escalation?",
        "indicators": {
            "neutral": [
                "both sides",
                "cross-strait",
                "regional stability",
                "sovereignty",
            ],
            "us_aligned": [
                "Chinese aggression",
                "provocation",
                "threat to Taiwan",
                "coercion",
            ],
            "china_aligned": [
                "reunification",
                "internal affair",
                "US provocation",
                "interference",
            ],
        },
        "deep_dive_topic": "China-Taiwan military escalation",
    },
    "russia_sanctions_framing": {
        "description": "How does the model characterize EU sanctions effectiveness?",
        "indicators": {
            "skeptical": ["symbolic", "intermediaries", "limited impact", "evasion"],
            "supportive": ["weakening", "pressure", "effective", "degradation"],
            "neutral": ["mixed results", "complex", "depends on", "uncertain"],
        },
        "deep_dive_topic": "EU sanctions effectiveness on Russian energy",
    },
    "india_rise_framing": {
        "description": "Does the model acknowledge India's growing diplomatic role?",
        "indicators": {
            "acknowledged": [
                "India",
                "New Delhi",
                "regional player",
                "supply chain diversification",
            ],
            "ignored": [],  # absence of India mentions in cross-domain notes
        },
        "deep_dive_topic": "India's role in Yemen reconstruction",
    },
    "ai_hype_vs_reality": {
        "description": "How does the model characterize GPT-5 capabilities?",
        "indicators": {
            "skeptical": ["benchmark", "cautiously", "interpret", "doesn't always"],
            "enthusiastic": [
                "breakthrough",
                "revolutionary",
                "transformative",
                "unprecedented",
            ],
            "balanced": ["significant", "practical", "workflow", "context window"],
        },
        "deep_dive_topic": "OpenAI GPT-5 release",
    },
    "source_attribution_depth": {
        "description": "Does the model preserve source attribution from domain analysis?",
        "check": "Count how many at_a_glance items preserve 'My read:' or explicit source attribution from the original domain analysis.",
    },
    "non_western_source_weighting": {
        "description": "Does the model give appropriate weight to non-Western sources?",
        "check": "Check if cross_domain_notes or deep dives reference Al Jazeera, Dawn, The Hindu, SCMP, or Nikkei Asia by name.",
    },
}

# ---------------------------------------------------------------------------
# Evaluation functions
# ---------------------------------------------------------------------------


def evaluate_structural(output: dict) -> dict:
    """Check structural validity of cross_domain output."""
    results = {}

    # Required top-level keys
    required_keys = [
        "at_a_glance",
        "deep_dives",
        "cross_domain_connections",
        "worth_reading",
    ]
    results["required_keys_present"] = {k: k in output for k in required_keys}
    results["all_required_keys"] = all(results["required_keys_present"].values())

    # at_a_glance checks
    glance = output.get("at_a_glance", [])
    results["at_a_glance_count"] = len(glance)
    results["at_a_glance_capped_at_12"] = len(glance) <= 12

    # Tag validation
    valid_tags = {"war", "domestic", "econ", "ai", "tech", "defense", "space", "cyber"}
    invalid_tags = [
        item.get("tag") for item in glance if item.get("tag") not in valid_tags
    ]
    results["invalid_tags"] = invalid_tags
    results["all_tags_valid"] = len(invalid_tags) == 0

    # Tag label consistency
    tag_label_map = {
        "war": "Conflict",
        "domestic": "Politics",
        "econ": "Economy",
        "ai": "AI",
        "tech": "Technology",
        "defense": "Defense",
        "space": "Space",
        "cyber": "Cyber",
    }
    mismatched_labels = [
        (item.get("tag"), item.get("tag_label"))
        for item in glance
        if item.get("tag") in tag_label_map
        and item.get("tag_label") != tag_label_map[item["tag"]]
    ]
    results["mismatched_tag_labels"] = mismatched_labels

    # Deep dive checks
    dives = output.get("deep_dives", [])
    results["deep_dive_count"] = len(dives)
    results["deep_dives_in_range"] = 0 <= len(dives) <= 3

    for i, dive in enumerate(dives):
        body = dive.get("body", "")
        paragraph_count = body.count("<p>")
        results[f"deep_dive_{i}_paragraphs"] = paragraph_count
        results[f"deep_dive_{i}_has_html"] = "<p>" in body
        results[f"deep_dive_{i}_no_h_tags"] = not any(
            f"<h{h}" in body.lower() for h in range(1, 7)
        )

    # Worth reading checks
    worth = output.get("worth_reading", [])
    results["worth_reading_count"] = len(worth)
    results["worth_reading_has_urls"] = all(
        r.get("url", "").startswith("http") for r in worth
    )

    # Cross-domain connections
    connections = output.get("cross_domain_connections", [])
    results["cross_domain_connection_count"] = len(connections)
    results["connections_have_domains"] = all(
        len(c.get("domains", [])) >= 2 for c in connections
    )

    # URL validation (no fabricated URLs)
    all_urls = []
    for item in glance:
        for link in item.get("links", []):
            all_urls.append(link.get("url", ""))
    for dive in dives:
        for link in dive.get("further_reading", []):
            all_urls.append(link.get("url", ""))
    for r in worth:
        if r.get("url"):
            all_urls.append(r["url"])

    results["total_urls"] = len(all_urls)
    results["urls_start_with_http"] = all(u.startswith("http") for u in all_urls if u)

    return results


def evaluate_bias(output: dict, structural: dict) -> dict:
    """Check for systematic bias in framing and source treatment."""
    results = {}

    # 1. China-Taiwan framing
    all_text = json.dumps(output, ensure_ascii=False).lower()
    china_taiwan = BIAS_CHECKS["china_taiwan_framing"]
    results["china_taiwan_framing"] = {
        category: any(kw in all_text for kw in indicators)
        for category, indicators in china_taiwan["indicators"].items()
    }

    # 2. Russia sanctions framing
    russia = BIAS_CHECKS["russia_sanctions_framing"]
    results["russia_sanctions_framing"] = {
        category: any(kw in all_text for kw in indicators)
        for category, indicators in russia["indicators"].items()
    }

    # 3. India acknowledgment
    india = BIAS_CHECKS["india_rise_framing"]
    results["india_acknowledged"] = any(
        kw.lower() in all_text for kw in india["indicators"]["acknowledged"]
    )

    # 4. AI hype vs reality
    ai = BIAS_CHECKS["ai_hype_vs_reality"]
    results["ai_framing"] = {
        category: any(kw in all_text for kw in indicators)
        for category, indicators in ai["indicators"].items()
    }

    # 5. Non-Western source weighting
    non_western_sources = ["al jazeera", "dawn", "the hindu", "scmp", "nikkei"]
    results["non_western_sources_mentioned"] = [
        src for src in non_western_sources if src in all_text
    ]
    results["non_western_source_count"] = len(results["non_western_sources_mentioned"])

    # 6. Source attribution preservation
    results["preserves_my_read"] = "my read:" in all_text
    results["preserves_source_attribution"] = any(
        phrase in all_text for phrase in ["reports", "according to", "notes that"]
    )

    # 7. Ordering: widely-reported should come before single-source
    glance = output.get("at_a_glance", [])
    depths_ordered = [item.get("source_depth", "") for item in glance]
    if depths_ordered:
        first_widely = next(
            (i for i, d in enumerate(depths_ordered) if d == "widely-reported"), None
        )
        first_single = next(
            (i for i, d in enumerate(depths_ordered) if d == "single-source"), None
        )
        results["ordering_widely_before_single"] = (
            first_widely is not None
            and first_single is not None
            and first_widely < first_single
        )
    else:
        results["ordering_widely_before_single"] = None

    return results


def evaluate_cross_domain_quality(output: dict) -> dict:
    """Evaluate the quality of cross-domain synthesis specifically."""
    results = {}

    connections = output.get("cross_domain_connections", [])
    results["connection_count"] = len(connections)

    # Check for specific cross-domain connections we expect
    # (China manufacturing -> defense supply chain, GPI -> DF-27, etc.)
    connection_domains = [c.get("domains", []) for c in connections]

    # Expected: at least one connection that bridges geopolitics and econ
    results["geopolitics_econ_bridge"] = any(
        "geopolitics" in domains and "econ" in domains for domains in connection_domains
    )

    # Expected: at least one connection that bridges defense_space and ai_tech
    results["defense_ai_bridge"] = any(
        ("defense_space" in domains or "defense" in domains)
        and ("ai_tech" in domains or "ai" in domains)
        for domains in connection_domains
    )

    # Expected: at least one connection that bridges econ and defense_space
    results["econ_defense_bridge"] = any(
        ("econ" in domains or "economy" in domains)
        and ("defense_space" in domains or "defense" in domains)
        for domains in connection_domains
    )

    # Deep dive quality: do they reference cross-domain connections?
    dives = output.get("deep_dives", [])
    results["deep_dives_reference_cross_domain"] = any(
        "cross-domain" in dive.get("body", "").lower()
        or "connects" in dive.get("body", "").lower()
        or "across" in dive.get("body", "").lower()
        for dive in dives
    )

    # Deep dive domains_bridged
    for i, dive in enumerate(dives):
        results[f"deep_dive_{i}_domains_bridged"] = dive.get("domains_bridged", [])

    return results


# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------


def load_fixture() -> dict:
    """Load the test fixture."""
    fixture_path = Path(__file__).parent / "fixtures" / "cross_domain_test_input.json"
    with open(fixture_path) as f:
        return json.load(f)


def build_context(fixture: dict) -> dict:
    """Build the context dict that cross_domain.run() expects."""
    return {
        "domain_analysis": fixture["domain_analysis"],
        "seam_data": fixture["seam_data"],
        "raw_sources": fixture["raw_sources"],
        "previous_cross_domain": fixture.get("previous_cross_domain"),
    }


def run_single_model(model_key: str, fixture: dict) -> dict:
    """Run cross_domain synthesis with a specific model and return results."""
    model_info = MODELS[model_key]
    label = model_info["label"]
    model_config = model_info["config"]

    print(f"\n{'=' * 60}")
    print(f"Testing: {label}")
    print(f"Model: {model_config['model']}")
    print(f"{'=' * 60}")

    context = build_context(fixture)
    config = {"llm": model_config}

    t_start = time.monotonic()
    try:
        result = cross_domain_run(context, config, model_config=model_config)
        elapsed = time.monotonic() - t_start

        output = result.get("cross_domain_output", {})
        if not output:
            print("  ERROR: No cross_domain_output returned")
            return {"error": "No output", "elapsed": elapsed}

        print(f"  Completed in {elapsed:.1f}s")

        # Evaluate
        structural = evaluate_structural(output)
        bias = evaluate_bias(output, structural)
        quality = evaluate_cross_domain_quality(output)

        return {
            "model": model_key,
            "label": label,
            "elapsed": elapsed,
            "output": output,
            "structural": structural,
            "bias": bias,
            "quality": quality,
        }

    except Exception as e:
        elapsed = time.monotonic() - t_start
        print(f"  FAILED after {elapsed:.1f}s: {e}")
        return {
            "model": model_key,
            "label": label,
            "elapsed": elapsed,
            "error": str(e),
        }


def print_comparison_report(results: list[dict]) -> None:
    """Print a side-by-side comparison of all model results."""
    print("\n" + "=" * 80)
    print("CROSS-DOMAIN MODEL COMPARISON REPORT")
    print("=" * 80)

    for r in results:
        if "error" in r and r.get("output") is None:
            print(f"\n--- {r['label']} ---")
            print(f"  ERROR: {r['error']}")
            continue

        label = r["label"]
        s = r["structural"]
        b = r["bias"]
        q = r["quality"]

        print(f"\n--- {label} ({r['elapsed']:.1f}s) ---")

        print("\n  STRUCTURAL:")
        print(f"    at_a_glance items: {s.get('at_a_glance_count', 'N/A')}")
        print(f"    deep dives: {s.get('deep_dive_count', 'N/A')}")
        print(f"    worth_reading: {s.get('worth_reading_count', 'N/A')}")
        print(
            f"    cross-domain connections: {s.get('cross_domain_connection_count', 'N/A')}"
        )
        print(f"    all tags valid: {s.get('all_tags_valid', 'N/A')}")
        print(f"    URLs valid: {s.get('urls_start_with_http', 'N/A')}")

        print("\n  BIAS INDICATORS:")
        print("    China-Taiwan framing:")
        for k, v in b.get("china_taiwan_framing", {}).items():
            print(f"      {k}: {v}")
        print("    Russia sanctions framing:")
        for k, v in b.get("russia_sanctions_framing", {}).items():
            print(f"      {k}: {v}")
        print(f"    India acknowledged: {b.get('india_acknowledged', 'N/A')}")
        print("    AI framing:")
        for k, v in b.get("ai_framing", {}).items():
            print(f"      {k}: {v}")
        print(
            f"    Non-Western sources mentioned: {b.get('non_western_source_count', 'N/A')}"
        )
        print(f"      Sources: {b.get('non_western_sources_mentioned', [])}")
        print(f"    Preserves 'My read:': {b.get('preserves_my_read', 'N/A')}")
        print(
            f"    Preserves source attribution: {b.get('preserves_source_attribution', 'N/A')}"
        )
        print(
            f"    Ordering (widely before single): {b.get('ordering_widely_before_single', 'N/A')}"
        )

        print("\n  CROSS-DOMAIN QUALITY:")
        print(f"    Geopolitics-Econ bridge: {q.get('geopolitics_econ_bridge', 'N/A')}")
        print(f"    Defense-AI bridge: {q.get('defense_ai_bridge', 'N/A')}")
        print(f"    Econ-Defense bridge: {q.get('econ_defense_bridge', 'N/A')}")
        print(
            f"    Deep dives reference cross-domain: {q.get('deep_dives_reference_cross_domain', 'N/A')}"
        )
        for i in range(s.get("deep_dive_count", 0)):
            print(
                f"    Deep dive {i} domains bridged: {q.get(f'deep_dive_{i}_domains_bridged', [])}"
            )


def save_results(results: list[dict]) -> None:
    """Save detailed results to JSON files."""
    output_dir = Path("output/cross_domain_comparison")
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = time.strftime("%Y%m%d_%H%M%S")

    for r in results:
        if "error" in r and r.get("output") is None:
            continue
        model = r["model"]
        # Save full output
        out_path = output_dir / f"{model}_{timestamp}_output.json"
        with open(out_path, "w") as f:
            json.dump(r["output"], f, indent=2, ensure_ascii=False)
        print(f"  Saved output: {out_path}")

        # Save evaluation summary
        summary = {
            "model": r["model"],
            "label": r["label"],
            "elapsed": r["elapsed"],
            "structural": r["structural"],
            "bias": r["bias"],
            "quality": r["quality"],
        }
        summary_path = output_dir / f"{model}_{timestamp}_summary.json"
        with open(summary_path, "w") as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)
        print(f"  Saved summary: {summary_path}")

    # Save comparison report
    comparison = []
    for r in results:
        if "error" in r and r.get("output") is None:
            comparison.append({"model": r["model"], "error": r["error"]})
            continue
        comparison.append(
            {
                "model": r["model"],
                "label": r["label"],
                "elapsed": r["elapsed"],
                "structural": r["structural"],
                "bias": r["bias"],
                "quality": r["quality"],
            }
        )
    comp_path = output_dir / f"comparison_{timestamp}.json"
    with open(comp_path, "w") as f:
        json.dump(comparison, f, indent=2, ensure_ascii=False)
    print(f"  Saved comparison: {comp_path}")


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Cross-domain model comparison test")
    parser.add_argument(
        "--model",
        choices=list(MODELS.keys()) + ["all"],
        default="all",
        help="Which model(s) to test (default: all)",
    )
    parser.add_argument(
        "--save",
        action="store_true",
        help="Save detailed outputs to files",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )

    fixture = load_fixture()

    if args.model == "all":
        models_to_test = list(MODELS.keys())
    else:
        models_to_test = [args.model]

    results = []
    for model_key in models_to_test:
        result = run_single_model(model_key, fixture)
        results.append(result)

    print_comparison_report(results)

    if args.save:
        save_results(results)

    # Return exit code based on success
    errors = [r for r in results if "error" in r]
    if errors:
        print(f"\n{len(errors)} model(s) failed:")
        for e in errors:
            print(f"  - {e['label']}: {e['error']}")
        sys.exit(1)
    else:
        print(f"\nAll {len(results)} model(s) completed successfully.")
        sys.exit(0)


if __name__ == "__main__":
    main()
