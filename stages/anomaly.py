"""Stage: anomaly — Post-assembly behavioral anomaly detection (Security Layer 5).

Five deterministic checks to catch digest quality issues:
  1. Category skew: primary tags missing from at_a_glance
  2. Source absence: categories with raw items but zero domain analysis coverage
  3. Unusual deep dive topics: tertiary-tag dives when primary-tag candidates existed
  4. Digest length anomaly: today vs. 7-day rolling average
  5. Repeated phrases: 10+ word sequences appearing in multiple sections

Non-blocking — logs warnings, never fails the pipeline.
"""

import json
import logging
import re
from pathlib import Path

log = logging.getLogger(__name__)

_ROOT = Path(__file__).parent.parent
_ARTIFACTS_BASE = _ROOT / "output" / "artifacts"

_PRIMARY_TAGS = {"war", "ai", "defense"}
_TERTIARY_TAGS = {"local", "science", "tech"}

# Domain names produced by cross_domain that map to primary interests
_PRIMARY_DOMAINS = {"geopolitics", "defense_space", "ai_tech"}

# Keywords used to infer whether a deep dive headline covers a primary topic
# when tag / domains_bridged are absent (Phase 1 fallback)
_PRIMARY_HEADLINE_KEYWORDS = {
    "war", "iran", "israel", "ukraine", "russia", "conflict", "combat",
    "attack", "military", "missile", "defense", "pentagon", "nato", "hormuz",
    "ai", "artificial intelligence", "llm", "openai", "anthropic",
    "space", "satellite", "launch", "cislunar", "orbit",
}


def _check_category_skew(at_a_glance: list) -> list:
    """Warn if any primary tag has zero items when total > 5."""
    anomalies = []
    if len(at_a_glance) <= 5:
        return anomalies
    present_tags = {item.get("tag", "") for item in at_a_glance}
    for tag in _PRIMARY_TAGS:
        if tag not in present_tags:
            anomalies.append({
                "check": "category_skew",
                "severity": "warning",
                "detail": f"Primary tag '{tag}' has 0 items in at_a_glance ({len(at_a_glance)} total items)",
            })
    return anomalies


def _check_source_absence(raw_sources: dict, domain_analysis: dict) -> list:
    """Warn if a category with 3+ raw items produced 0 domain analysis items."""
    anomalies = []

    # Count raw items per category
    raw_by_category: dict[str, int] = {}
    for item in raw_sources.get("rss", []):
        cat = item.get("category", "")
        if cat:
            raw_by_category[cat] = raw_by_category.get(cat, 0) + 1

    # Collect categories referenced in domain analysis
    covered_sources: set[str] = set()
    for domain_result in domain_analysis.values():
        if not isinstance(domain_result, dict):
            continue
        for item in domain_result.get("items", []):
            for link in item.get("links", []):
                url = link.get("url", "")
                if url:
                    covered_sources.add(url)

    # Find raw URLs by category to check coverage
    raw_urls_by_category: dict[str, set] = {}
    for item in raw_sources.get("rss", []):
        cat = item.get("category", "")
        url = item.get("url", "")
        if cat and url:
            raw_urls_by_category.setdefault(cat, set()).add(url)

    for cat, count in raw_by_category.items():
        if count < 3:
            continue
        cat_urls = raw_urls_by_category.get(cat, set())
        if not cat_urls & covered_sources:
            anomalies.append({
                "check": "source_absence",
                "severity": "warning",
                "detail": f"Category '{cat}' had {count} raw items but contributed 0 items to domain analysis",
            })

    return anomalies


def _dive_is_primary(dive: dict) -> bool:
    """Return True if a deep dive covers a primary topic (war, defense, AI, space).

    Checks in priority order:
    1. domains_bridged list (Phase 3 cross_domain output)
    2. tag field (Phase 1 domain_item_to_deep_dive output)
    3. Keyword scan of headline (fallback)
    """
    domains = set(dive.get("domains_bridged") or [])
    if domains & _PRIMARY_DOMAINS:
        return True
    tag = dive.get("tag", "") or ""
    if tag in _PRIMARY_TAGS:
        return True
    hl = dive.get("headline", "").lower()
    return any(kw in hl for kw in _PRIMARY_HEADLINE_KEYWORDS)


def _check_unusual_deep_dives(deep_dives: list, domain_analysis: dict) -> list:
    """Warn if deep dives don't cover any primary topic while primary candidates existed."""
    anomalies = []

    # Collect primary-tag deep_dive_candidates from domain analysis
    primary_candidates = []
    for domain_result in domain_analysis.values():
        if not isinstance(domain_result, dict):
            continue
        for item in domain_result.get("items", []):
            if item.get("deep_dive_candidate") and item.get("tag", "") in _PRIMARY_TAGS:
                primary_candidates.append(item.get("headline", "?"))

    if not primary_candidates:
        return anomalies

    for dive in deep_dives:
        if not _dive_is_primary(dive):
            anomalies.append({
                "check": "unusual_deep_dive",
                "severity": "warning",
                "detail": (
                    f"Deep dive '{dive.get('headline', '?')}' doesn't cover a primary topic "
                    f"while primary-tag candidates were available: {primary_candidates[:3]}"
                ),
            })

    return anomalies


def _check_digest_length(total_items: int) -> list:
    """Warn if today's item count is >2x or <0.5x the 7-day rolling average."""
    anomalies = []

    prior_counts = []
    if _ARTIFACTS_BASE.exists():
        dirs = sorted(
            [d for d in _ARTIFACTS_BASE.iterdir() if d.is_dir() and len(d.name) == 10],
            reverse=True,
        )
        for d in dirs[:7]:
            digest_path = d / "digest_json.json"
            if not digest_path.exists():
                continue
            try:
                data = json.loads(digest_path.read_text(encoding="utf-8"))
                glance = data.get("at_a_glance", [])
                dives = data.get("deep_dives", [])
                prior_counts.append(len(glance) + len(dives))
            except Exception:
                continue

    if len(prior_counts) < 3:
        return anomalies

    avg = sum(prior_counts) / len(prior_counts)
    if avg == 0:
        return anomalies

    ratio = total_items / avg
    if ratio > 2.0:
        anomalies.append({
            "check": "digest_length_anomaly",
            "severity": "warning",
            "detail": (
                f"Today's digest has {total_items} items — "
                f"{ratio:.1f}x the {len(prior_counts)}-day average ({avg:.1f})"
            ),
        })
    elif ratio < 0.5:
        anomalies.append({
            "check": "digest_length_anomaly",
            "severity": "warning",
            "detail": (
                f"Today's digest has {total_items} items — "
                f"only {ratio:.1%} of the {len(prior_counts)}-day average ({avg:.1f})"
            ),
        })

    return anomalies


def _check_repeated_phrases(cross_domain_output: dict, seam_data: dict) -> list:
    """Find 10+ word sequences that appear in more than one digest section."""
    anomalies = []

    # Collect all text per section
    sections: dict[str, str] = {}

    glance_texts = []
    for item in cross_domain_output.get("at_a_glance", []):
        # at_a_glance items use "context" (combined facts+analysis) not "facts"/"analysis"
        parts = [item.get("headline", ""), item.get("context", ""), item.get("cross_domain_note", "")]
        glance_texts.append(" ".join(p for p in parts if p))
    if glance_texts:
        sections["at_a_glance"] = " ".join(glance_texts)

    dive_texts = []
    for dive in cross_domain_output.get("deep_dives", []):
        body = re.sub(r"<[^>]+>", " ", dive.get("body", ""))
        dive_texts.append(f"{dive.get('headline', '')} {body}")
    if dive_texts:
        sections["deep_dives"] = " ".join(dive_texts)

    cn_texts = []
    for cn in seam_data.get("contested_narratives", []):
        cn_texts.append(f"{cn.get('topic', '')} {cn.get('description', '')}")
    if cn_texts:
        sections["contested_narratives"] = " ".join(cn_texts)

    if len(sections) < 2:
        return anomalies

    # Build word-list per section
    section_words: dict[str, list[str]] = {}
    for sec, text in sections.items():
        words = re.sub(r"[^\w\s]", "", text.lower()).split()
        section_words[sec] = words

    # Sliding window: find 10-word sequences common to any two sections
    window = 10
    section_names = list(section_words.keys())
    found: set[str] = set()

    for i, sec_a in enumerate(section_names):
        words_a = section_words[sec_a]
        if len(words_a) < window:
            continue
        ngrams_a = {
            " ".join(words_a[j:j + window])
            for j in range(len(words_a) - window + 1)
        }
        for sec_b in section_names[i + 1:]:
            words_b = section_words[sec_b]
            if len(words_b) < window:
                continue
            ngrams_b = {
                " ".join(words_b[k:k + window])
                for k in range(len(words_b) - window + 1)
            }
            repeated = ngrams_a & ngrams_b
            for phrase in repeated:
                if phrase not in found:
                    found.add(phrase)
                    anomalies.append({
                        "check": "repeated_phrase",
                        "severity": "warning",
                        "detail": f"10-word phrase appears in both '{sec_a}' and '{sec_b}': \"{phrase}\"",
                    })

    return anomalies


def run(context: dict, config: dict, model_config=None, **kwargs) -> dict:
    """Post-assembly behavioral anomaly detection. Non-blocking — logs warnings, never fails."""
    cross_domain_output = context.get("cross_domain_output", {})
    domain_analysis = context.get("domain_analysis", {})
    raw_sources = context.get("raw_sources", {})
    seam_data = context.get("seam_data", {})

    at_a_glance = cross_domain_output.get("at_a_glance", [])
    deep_dives = cross_domain_output.get("deep_dives", [])
    total_items = len(at_a_glance) + len(deep_dives)

    all_anomalies = []

    try:
        all_anomalies.extend(_check_category_skew(at_a_glance))
    except Exception as e:
        log.warning(f"anomaly: check_category_skew failed: {e}")

    try:
        all_anomalies.extend(_check_source_absence(raw_sources, domain_analysis))
    except Exception as e:
        log.warning(f"anomaly: check_source_absence failed: {e}")

    try:
        all_anomalies.extend(_check_unusual_deep_dives(deep_dives, domain_analysis))
    except Exception as e:
        log.warning(f"anomaly: check_unusual_deep_dives failed: {e}")

    try:
        all_anomalies.extend(_check_digest_length(total_items))
    except Exception as e:
        log.warning(f"anomaly: check_digest_length failed: {e}")

    try:
        all_anomalies.extend(_check_repeated_phrases(cross_domain_output, seam_data))
    except Exception as e:
        log.warning(f"anomaly: check_repeated_phrases failed: {e}")

    report = {
        "anomalies": all_anomalies,
        "checks_run": 5,
        "anomaly_count": len(all_anomalies),
    }

    if all_anomalies:
        for a in all_anomalies:
            log.warning(f"anomaly [{a['check']}]: {a['detail']}")
    else:
        log.info("anomaly: all 5 checks passed — no anomalies detected")

    return {"anomaly_report": report}
