"""Security Layer 3 — Output Validation.

Validates LLM stage output for schema correctness, URL integrity, tag validity,
and editorial anomalies. All checks are non-blocking: the pipeline never fails
due to validation — anomalies are logged and invalid content is stripped or
replaced with safe defaults.

Public API:
  validate_stage_output(output, source_data, stage_name) -> dict
  validate_urls(output_json, known_urls)                  -> dict
"""

import logging
import re
from typing import Any

from urllib.parse import urlparse

from utils.urls import canonicalize_url, collect_canonical_urls, collect_known_urls

log = logging.getLogger(__name__)

VALID_TAGS = {
    "war",
    "ai",
    "domestic",
    "defense",
    "space",
    "tech",
    "local",
    "science",
    "econ",
    "cyber",
    "energy",
    "biotech",
}
VALID_TAG_LABELS = {
    "war": "Conflict",
    "ai": "AI",
    "domestic": "Politics",
    "defense": "Defense",
    "space": "Space",
    "tech": "Technology",
    "local": "Local",
    "science": "Science",
    "econ": "Economy",
    "cyber": "Cyber",
    "energy": "Energy",
    "biotech": "Biotech",
}

# HTML tags allowed in deep dive body fields after sanitization
_ALLOWED_HTML_TAGS = {"p", "em", "strong", "a", "ul", "li", "ol", "br"}
_HTML_TAG_RE = re.compile(r"<(/?)(\w+)([^>]*)>", re.IGNORECASE)
_URL_RE = re.compile(r"https?://\S+")


def _extract_urls_from_value(value: Any) -> list[str]:
    """Recursively extract all URL strings from a nested dict/list structure."""
    urls = []
    if isinstance(value, str):
        urls.extend(_URL_RE.findall(value))
    elif isinstance(value, dict):
        for v in value.values():
            urls.extend(_extract_urls_from_value(v))
    elif isinstance(value, list):
        for item in value:
            urls.extend(_extract_urls_from_value(item))
    return urls


def _strip_disallowed_html(html: str) -> str:
    """Strip HTML tags not in _ALLOWED_HTML_TAGS, preserving their text content."""

    def replace_tag(m: re.Match) -> str:
        tag = m.group(2).lower()
        if tag in _ALLOWED_HTML_TAGS:
            return m.group(0)  # keep allowed tags
        return ""  # strip disallowed tags, keep text

    return _HTML_TAG_RE.sub(replace_tag, html)


def validate_urls(
    output_json: Any,
    known_urls: set[str],
    diagnostics: list[dict] | None = None,
    path: str = "",
    known_canonical_urls: set[str] | None = None,
) -> Any:
    """Strip URLs in output_json that are not in known_urls.

    Works recursively over dicts and lists. Returns cleaned structure.
    Logs a warning for each stripped URL.
    """
    if known_canonical_urls is None:
        known_canonical_urls = collect_canonical_urls(known_urls)

    if isinstance(output_json, dict):
        result = {}
        for k, v in output_json.items():
            if k == "url" and isinstance(v, str):
                canonical = canonicalize_url(v)
                if v and v not in known_urls and canonical not in known_canonical_urls:
                    known_domains = {
                        urlparse(url).netloc.lower()
                        for url in known_urls
                        if urlparse(url).netloc
                    }
                    netloc = urlparse(v).netloc.lower()
                    reason = (
                        "known_domain_unknown_path"
                        if netloc and netloc in known_domains
                        else "unknown_domain"
                    )
                    log.warning(
                        f"validate: stripped unsupported URL ({reason}): {v[:80]}"
                    )
                    if diagnostics is not None:
                        diagnostics.append(
                            {
                                "kind": "stripped_url",
                                "path": f"{path}.{k}" if path else k,
                                "url": v,
                                "reason": reason,
                                "canonical_url": canonical,
                            }
                        )
                    result[k] = ""
                else:
                    result[k] = v
            else:
                child_path = f"{path}.{k}" if path else k
                result[k] = validate_urls(
                    v,
                    known_urls,
                    diagnostics,
                    child_path,
                    known_canonical_urls,
                )
        return result
    elif isinstance(output_json, list):
        return [
            validate_urls(
                item,
                known_urls,
                diagnostics,
                f"{path}[{idx}]",
                known_canonical_urls,
            )
            for idx, item in enumerate(output_json)
        ]
    return output_json


def _drop_empty_url_links(links: list) -> list:
    return [
        link
        for link in links
        if isinstance(link, dict) and str(link.get("url", "")).strip()
    ]


def _validate_at_a_glance(
    items: list,
    known_urls: set[str],
    source_data: dict,
    diagnostics: list[dict] | None = None,
) -> list:
    """Validate and clean at_a_glance items."""
    if not isinstance(items, list):
        log.warning("validate: at_a_glance is not a list, resetting to []")
        return []

    # Source distribution check
    source_counts: dict[str, int] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        for link in item.get("links") or []:
            label = link.get("label", "")
            # Extract outlet name (format: "Source: Title" or just label)
            source = label.split(":")[0].strip() if ":" in label else label
            source_counts[source] = source_counts.get(source, 0) + 1

    total = len(items)
    for source, count in source_counts.items():
        if total > 0 and count / total > 0.4:
            detail = (
                f"'{source}' accounts for {count}/{total} items "
                f"({count / total:.0%})"
            )
            log.warning(
                f"validate: source distribution anomaly — {detail}. "
                "Possible editorial manipulation."
            )
            if diagnostics is not None:
                diagnostics.append(
                    {
                        "kind": "source_distribution_anomaly",
                        "source": source,
                        "count": count,
                        "total": total,
                        "rate": count / total,
                        "detail": detail,
                    }
                )

    # Collect source titles for verbatim echo detection
    source_titles = {
        item.get("title", "").lower() for item in source_data.get("rss", [])
    }
    source_titles.update(
        item.get("title", "").lower() for item in source_data.get("local_news", [])
    )

    cleaned = []
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            log.warning(f"validate: at_a_glance[{i}] is not a dict, skipping")
            continue

        # Required fields with safe defaults
        tag = item.get("tag", "")
        if tag not in VALID_TAGS:
            log.warning(f"validate: unknown tag '{tag}' → 'domestic'")
            tag = "domestic"

        headline = str(item.get("headline", "")).strip()

        # Verbatim echo detection
        if headline.lower() in source_titles:
            log.info(f"validate: verbatim echo detected in headline: {headline[:60]!r}")

        # Schema-preserving: copy all fields, then overwrite validated ones
        entry = dict(item)
        entry["tag"] = tag
        entry["tag_label"] = item.get("tag_label") or VALID_TAG_LABELS.get(tag, tag.capitalize())
        entry["headline"] = headline
        entry["context"] = str(item.get("context", ""))
        entry["links"] = _drop_empty_url_links(
            validate_urls(
                item.get("links") or [],
                known_urls,
                diagnostics,
                f"at_a_glance[{i}].links",
            )
        )
        cleaned.append(entry)

    return cleaned


def _validate_deep_dives(
    dives: list,
    known_urls: set[str],
    diagnostics: list[dict] | None = None,
) -> list:
    """Validate and clean deep_dives items. Sanitizes HTML in body field."""
    if not isinstance(dives, list):
        return []
    cleaned = []
    for i, dive in enumerate(dives):
        if not isinstance(dive, dict):
            log.warning(f"validate: deep_dives[{i}] is not a dict, skipping")
            continue
        body = str(dive.get("body", ""))
        body_clean = _strip_disallowed_html(body)
        if body_clean != body:
            log.info(
                f"validate: stripped disallowed HTML tags from deep dive body (dive {i})"
            )
        # Schema-preserving: copy all fields, then overwrite validated ones
        entry = dict(dive)
        entry["headline"] = str(dive.get("headline", ""))
        entry["body"] = body_clean
        entry["why_it_matters"] = str(dive.get("why_it_matters", ""))
        entry["further_reading"] = _drop_empty_url_links(
            validate_urls(
                dive.get("further_reading", []),
                known_urls,
                diagnostics,
                f"deep_dives[{i}].further_reading",
            )
        )
        cleaned.append(entry)
    return cleaned


def _validate_seam_items(
    items: list,
    known_urls: set[str],
    item_type: str,
    diagnostics: list[dict] | None = None,
) -> list:
    """Validate contested_narratives or coverage_gaps items."""
    if not isinstance(items, list):
        return []
    cleaned = []
    for item in items:
        if not isinstance(item, dict):
            continue
        entry = {
            "topic": str(item.get("topic", "")),
            "description": str(item.get("description", "")),
            "links": _drop_empty_url_links(
                validate_urls(
                    item.get("links", []),
                    known_urls,
                    diagnostics,
                    f"{item_type}.links",
                )
            ),
        }
        if item_type == "contested":
            entry["sources_a"] = str(item.get("sources_a", ""))
            entry["sources_b"] = str(item.get("sources_b", ""))
        else:
            entry["present_in"] = str(item.get("present_in", ""))
            entry["absent_from"] = str(item.get("absent_from", ""))
        cleaned.append(entry)
    return cleaned


def validate_stage_output(
    output: dict,
    source_data: dict,
    stage_name: str,
    *,
    collect_diagnostics: bool = False,
    domain_analysis: dict | None = None,
) -> dict:
    """Validate and clean LLM stage output.

    Args:
        output:      Raw dict from LLM (already JSON-parsed).
        source_data: raw_sources dict, used for URL validation and source title lookup.
        stage_name:  Name of the stage (for log messages).

    Returns:
        Cleaned dict with invalid content stripped/replaced by safe defaults.
        Never raises.
    """
    if not isinstance(output, dict):
        log.error(
            f"validate [{stage_name}]: output is not a dict ({type(output).__name__}), returning empty"
        )
        return {}

    known_urls = collect_known_urls(source_data, domain_analysis)
    result = dict(output)
    diagnostics: list[dict] = []

    # --- At a Glance ---
    if "at_a_glance" in result:
        items = _validate_at_a_glance(
            result["at_a_glance"],
            known_urls,
            source_data,
            diagnostics if collect_diagnostics else None,
        )
        # Sanity-check bounds — LLM output outside this range is suspicious
        # regardless of the configured target. Not enforced, only logged.
        min_items = 3
        max_items = 20
        if len(items) < min_items:
            log.warning(
                f"validate [{stage_name}]: only {len(items)} at_a_glance items (min {min_items})"
            )
        elif len(items) > max_items:
            log.warning(
                f"validate [{stage_name}]: {len(items)} at_a_glance items exceeds max {max_items}"
            )
        result["at_a_glance"] = items

    # --- Deep Dives ---
    if "deep_dives" in result:
        dives = _validate_deep_dives(
            result["deep_dives"],
            known_urls,
            diagnostics if collect_diagnostics else None,
        )
        if not dives:
            log.warning(f"validate [{stage_name}]: no valid deep dives in output")
        result["deep_dives"] = dives

    # --- Seams ---
    if "contested_narratives" in result:
        result["contested_narratives"] = _validate_seam_items(
            result["contested_narratives"],
            known_urls,
            "contested",
            diagnostics if collect_diagnostics else None,
        )
    if "coverage_gaps" in result:
        result["coverage_gaps"] = _validate_seam_items(
            result["coverage_gaps"],
            known_urls,
            "gap",
            diagnostics if collect_diagnostics else None,
        )

    # --- Local Items ---
    if "local_items" in result:
        items = result["local_items"]
        if not isinstance(items, list):
            result["local_items"] = []
        else:
            result["local_items"] = validate_urls(
                items,
                known_urls,
                diagnostics if collect_diagnostics else None,
                "local_items",
            )

    # --- URL validation on any remaining fields ---
    for field in (
        "week_ahead",
        "worth_reading",
        "market_context",
        "spiritual_reflection",
    ):
        if field in result:
            result[field] = validate_urls(
                result[field],
                known_urls,
                diagnostics if collect_diagnostics else None,
                field,
            )

    if collect_diagnostics:
        result["_validation_diagnostics"] = {
            "stage": stage_name,
            "issue_count": len(diagnostics),
            "issues": diagnostics,
        }
    return result
