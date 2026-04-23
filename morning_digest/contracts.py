"""Schema contract helpers for pipeline stage artifacts.

These helpers intentionally return plain JSON-compatible dicts so persisted
artifacts and downstream stages keep their current shape. The contract layer
normalizes common LLM shape drift and reports contract issues close to the
stage boundary that produced them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ContractIssue:
    """A non-fatal schema issue discovered during contract normalization."""

    path: str
    message: str

    def to_dict(self) -> dict:
        return {"path": self.path, "message": self.message}


def _to_str(value: Any, *, default: str = "") -> str:
    if value is None:
        return default
    return str(value)


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return bool(value)


def _to_str_list(value: Any, path: str, issues: list[ContractIssue]) -> list[str]:
    if not isinstance(value, list):
        issues.append(ContractIssue(path, "value is not a list"))
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _extra_fields(raw: dict, known: set[str]) -> dict:
    return {key: value for key, value in raw.items() if key not in known}


@dataclass
class SourceLink:
    """A source link referenced by a domain item."""

    url: str = ""
    label: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_raw(
        cls, raw: Any, path: str, issues: list[ContractIssue]
    ) -> "SourceLink | None":
        if not isinstance(raw, dict):
            issues.append(ContractIssue(path, "link entry is not an object"))
            return None
        return cls(
            url=_to_str(raw.get("url")),
            label=_to_str(raw.get("label")),
            extra=_extra_fields(raw, {"url", "label"}),
        )

    def to_dict(self) -> dict:
        return {**self.extra, "url": self.url, "label": self.label}


@dataclass
class ConnectionHook:
    """A reusable cross-domain connection hint from a domain item."""

    entity: str = ""
    region: str = ""
    theme: str = ""
    policy: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_raw(
        cls, raw: Any, path: str, issues: list[ContractIssue]
    ) -> "ConnectionHook | None":
        if not isinstance(raw, dict):
            issues.append(ContractIssue(path, "connection_hook entry is not an object"))
            return None
        return cls(
            entity=_to_str(raw.get("entity")),
            region=_to_str(raw.get("region")),
            theme=_to_str(raw.get("theme")),
            policy=_to_str(raw.get("policy")),
            extra=_extra_fields(raw, {"entity", "region", "theme", "policy"}),
        )

    def to_dict(self) -> dict:
        return {
            **self.extra,
            "entity": self.entity,
            "region": self.region,
            "theme": self.theme,
            "policy": self.policy,
        }


@dataclass
class DomainItem:
    """Normalized item emitted by a specialist analysis desk."""

    item_id: str = ""
    tag: str = ""
    tag_label: str = ""
    headline: str = ""
    facts: str = ""
    analysis: str = ""
    source_depth: str = ""
    connection_hooks: list[ConnectionHook] = field(default_factory=list)
    links: list[SourceLink] = field(default_factory=list)
    deep_dive_candidate: bool = False
    deep_dive_rationale: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_raw(
        cls, raw: Any, path: str, issues: list[ContractIssue]
    ) -> "DomainItem | None":
        if not isinstance(raw, dict):
            issues.append(ContractIssue(path, "domain item is not an object"))
            return None

        links_raw = raw.get("links", [])
        if not isinstance(links_raw, list):
            issues.append(ContractIssue(f"{path}.links", "links is not a list"))
            links_raw = []

        hooks_raw = raw.get("connection_hooks", [])
        if not isinstance(hooks_raw, list):
            issues.append(
                ContractIssue(
                    f"{path}.connection_hooks", "connection_hooks is not a list"
                )
            )
            hooks_raw = []

        rationale = raw.get("deep_dive_rationale")
        known = {
            "item_id",
            "tag",
            "tag_label",
            "headline",
            "facts",
            "analysis",
            "source_depth",
            "connection_hooks",
            "links",
            "deep_dive_candidate",
            "deep_dive_rationale",
        }
        return cls(
            item_id=_to_str(raw.get("item_id")),
            tag=_to_str(raw.get("tag")),
            tag_label=_to_str(raw.get("tag_label")),
            headline=_to_str(raw.get("headline")),
            facts=_to_str(raw.get("facts")),
            analysis=_to_str(raw.get("analysis")),
            source_depth=_to_str(raw.get("source_depth")),
            connection_hooks=[
                hook
                for idx, hook_raw in enumerate(hooks_raw)
                if (
                    hook := ConnectionHook.from_raw(
                        hook_raw, f"{path}.connection_hooks[{idx}]", issues
                    )
                )
                is not None
            ],
            links=[
                link
                for idx, link_raw in enumerate(links_raw)
                if (link := SourceLink.from_raw(link_raw, f"{path}.links[{idx}]", issues))
                is not None
            ],
            deep_dive_candidate=_to_bool(raw.get("deep_dive_candidate", False)),
            deep_dive_rationale=None if rationale is None else _to_str(rationale),
            extra=_extra_fields(raw, known),
        )

    def to_dict(self) -> dict:
        return {
            **self.extra,
            "item_id": self.item_id,
            "tag": self.tag,
            "tag_label": self.tag_label,
            "headline": self.headline,
            "facts": self.facts,
            "analysis": self.analysis,
            "source_depth": self.source_depth,
            "connection_hooks": [hook.to_dict() for hook in self.connection_hooks],
            "links": [link.to_dict() for link in self.links],
            "deep_dive_candidate": self.deep_dive_candidate,
            "deep_dive_rationale": self.deep_dive_rationale,
        }


@dataclass
class DomainResult:
    """Normalized output from one analysis desk."""

    items: list[DomainItem] = field(default_factory=list)
    market_context: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_raw(
        cls,
        raw: Any,
        *,
        domain_key: str,
        path: str,
        issues: list[ContractIssue],
    ) -> "DomainResult":
        if isinstance(raw, list):
            raw = {"items": raw}
        if not isinstance(raw, dict):
            issues.append(ContractIssue(path, "domain result is not an object"))
            raw = {}

        items_raw = raw.get("items", [])
        if not isinstance(items_raw, list):
            issues.append(ContractIssue(f"{path}.items", "items is not a list"))
            items_raw = []

        known = {"items", "market_context"}
        market_context = None
        if domain_key == "econ":
            market_context = _to_str(raw.get("market_context"))

        return cls(
            items=[
                item
                for idx, item_raw in enumerate(items_raw)
                if (
                    item := DomainItem.from_raw(
                        item_raw, f"{path}.items[{idx}]", issues
                    )
                )
                is not None
            ],
            market_context=market_context,
            extra=_extra_fields(raw, known),
        )

    def to_dict(self) -> dict:
        result = {**self.extra, "items": [item.to_dict() for item in self.items]}
        if self.market_context is not None:
            result["market_context"] = self.market_context
        return result


def normalize_domain_result(raw: Any, domain_key: str) -> tuple[dict, list[dict]]:
    """Normalize one analysis desk result and return `(result, issues)`."""
    issues: list[ContractIssue] = []
    result = DomainResult.from_raw(
        raw,
        domain_key=domain_key,
        path=f"domain_analysis.{domain_key}",
        issues=issues,
    )
    return result.to_dict(), [issue.to_dict() for issue in issues]


def normalize_domain_analysis(raw: Any) -> tuple[dict, list[dict]]:
    """Normalize a full `domain_analysis` artifact."""
    issues: list[ContractIssue] = []
    if not isinstance(raw, dict):
        issues.append(ContractIssue("domain_analysis", "artifact is not an object"))
        return {}, [issue.to_dict() for issue in issues]

    normalized: dict[str, dict] = {}
    for domain_key, domain_result in raw.items():
        result = DomainResult.from_raw(
            domain_result,
            domain_key=domain_key,
            path=f"domain_analysis.{domain_key}",
            issues=issues,
        )
        normalized[domain_key] = result.to_dict()

    return normalized, [issue.to_dict() for issue in issues]


def _known_item_ids(domain_analysis: dict) -> set[str]:
    ids: set[str] = set()
    for domain_result in domain_analysis.values():
        if not isinstance(domain_result, dict):
            continue
        for item in domain_result.get("items", []):
            if not isinstance(item, dict):
                continue
            item_id = str(item.get("item_id", "")).strip()
            if item_id:
                ids.add(item_id)
    return ids


def normalize_seam_candidates_artifact(
    raw: Any, domain_analysis: dict | None = None
) -> tuple[dict, list[dict]]:
    """Normalize the broad seam candidate artifact."""
    issues: list[ContractIssue] = []
    if not isinstance(raw, dict):
        issues.append(ContractIssue("seam_candidates", "artifact is not an object"))
        raw = {}

    ids = _known_item_ids(domain_analysis or {})
    candidates_raw = raw.get("candidates", [])
    if not isinstance(candidates_raw, list):
        issues.append(
            ContractIssue("seam_candidates.candidates", "candidates is not a list")
        )
        candidates_raw = []

    candidates = []
    for idx, item in enumerate(candidates_raw):
        path = f"seam_candidates.candidates[{idx}]"
        if not isinstance(item, dict):
            issues.append(ContractIssue(path, "candidate is not an object"))
            continue
        item_id = str(item.get("item_id", "")).strip()
        if ids and item_id and item_id not in ids:
            issues.append(ContractIssue(f"{path}.item_id", "item_id is unknown"))
            continue
        evidence_raw = item.get("possible_evidence", [])
        if not isinstance(evidence_raw, list):
            issues.append(
                ContractIssue(
                    f"{path}.possible_evidence",
                    "possible_evidence is not a list",
                )
            )
            evidence_raw = []
        evidence = []
        for evidence_idx, entry in enumerate(evidence_raw):
            if not isinstance(entry, dict):
                issues.append(
                    ContractIssue(
                        f"{path}.possible_evidence[{evidence_idx}]",
                        "evidence entry is not an object",
                    )
                )
                continue
            evidence.append(
                {
                    "source": _to_str(entry.get("source")),
                    "excerpt": _to_str(entry.get("excerpt")),
                    "framing": _to_str(entry.get("framing")),
                }
            )
        candidates.append(
            {
                **_extra_fields(
                    item,
                    {
                        "item_id",
                        "seam_type",
                        "candidate_one_line",
                        "why_it_might_matter",
                        "possible_evidence",
                        "drop_if_weak_reason",
                    },
                ),
                "item_id": item_id,
                "seam_type": _to_str(item.get("seam_type")),
                "candidate_one_line": _to_str(item.get("candidate_one_line")),
                "why_it_might_matter": _to_str(item.get("why_it_might_matter")),
                "possible_evidence": evidence,
                "drop_if_weak_reason": _to_str(item.get("drop_if_weak_reason")),
            }
        )

    cross_raw = raw.get("cross_domain_candidates", [])
    if not isinstance(cross_raw, list):
        issues.append(
            ContractIssue(
                "seam_candidates.cross_domain_candidates",
                "cross_domain_candidates is not a list",
            )
        )
        cross_raw = []

    cross_domain_candidates = []
    for idx, item in enumerate(cross_raw):
        path = f"seam_candidates.cross_domain_candidates[{idx}]"
        if not isinstance(item, dict):
            issues.append(ContractIssue(path, "cross-domain candidate is not an object"))
            continue
        linked_raw = item.get("linked_item_ids", [])
        if not isinstance(linked_raw, list):
            issues.append(
                ContractIssue(
                    f"{path}.linked_item_ids",
                    "linked_item_ids is not a list",
                )
            )
            linked_raw = []
        linked_ids = [
            str(item_id).strip() for item_id in linked_raw if str(item_id).strip()
        ]
        if ids:
            unknown = [item_id for item_id in linked_ids if item_id not in ids]
            for item_id in unknown:
                issues.append(
                    ContractIssue(
                        f"{path}.linked_item_ids",
                        f"unknown item_id: {item_id}",
                    )
                )
            linked_ids = [item_id for item_id in linked_ids if item_id in ids]
        cross_domain_candidates.append(
            {
                **_extra_fields(
                    item,
                    {"candidate_one_line", "linked_item_ids", "why_it_might_matter"},
                ),
                "candidate_one_line": _to_str(item.get("candidate_one_line")),
                "linked_item_ids": linked_ids,
                "why_it_might_matter": _to_str(item.get("why_it_might_matter")),
            }
        )

    normalized = {
        "schema_version": 1,
        "candidates": candidates,
        "cross_domain_candidates": cross_domain_candidates,
    }
    return normalized, [issue.to_dict() for issue in issues]


def normalize_seam_annotations_artifact(
    raw: Any, domain_analysis: dict | None = None
) -> tuple[dict, list[dict]]:
    """Normalize the per-item seam annotation artifact."""
    issues: list[ContractIssue] = []
    if not isinstance(raw, dict):
        issues.append(ContractIssue("seam_annotations", "artifact is not an object"))
        raw = {}

    ids = _known_item_ids(domain_analysis or {})
    per_item_raw = raw.get("per_item", [])
    if not isinstance(per_item_raw, list):
        issues.append(
            ContractIssue("seam_annotations.per_item", "per_item is not a list")
        )
        per_item_raw = []

    per_item = []
    for idx, item in enumerate(per_item_raw):
        path = f"seam_annotations.per_item[{idx}]"
        if not isinstance(item, dict):
            issues.append(ContractIssue(path, "annotation is not an object"))
            continue
        item_id = str(item.get("item_id", "")).strip()
        if ids and item_id and item_id not in ids:
            issues.append(ContractIssue(f"{path}.item_id", "item_id is unknown"))
            continue
        evidence_raw = item.get("evidence", [])
        if not isinstance(evidence_raw, list):
            issues.append(ContractIssue(f"{path}.evidence", "evidence is not a list"))
            evidence_raw = []
        links_raw = item.get("links", [])
        if not isinstance(links_raw, list):
            issues.append(ContractIssue(f"{path}.links", "links is not a list"))
            links_raw = []
        links = [
            link.to_dict()
            for link_idx, link_raw in enumerate(links_raw)
            if (
                link := SourceLink.from_raw(
                    link_raw, f"{path}.links[{link_idx}]", issues
                )
            )
            is not None
        ]
        evidence = []
        for evidence_idx, entry in enumerate(evidence_raw):
            if not isinstance(entry, dict):
                issues.append(
                    ContractIssue(
                        f"{path}.evidence[{evidence_idx}]",
                        "evidence entry is not an object",
                    )
                )
                continue
            evidence.append(
                {
                    "source": _to_str(entry.get("source")),
                    "excerpt": _to_str(entry.get("excerpt")),
                    "framing": _to_str(entry.get("framing")),
                }
            )
        per_item.append(
            {
                **_extra_fields(
                    item,
                    {
                        "item_id",
                        "seam_type",
                        "one_line",
                        "links",
                        "evidence",
                        "confidence",
                    },
                ),
                "item_id": item_id,
                "seam_type": _to_str(item.get("seam_type")),
                "one_line": _to_str(item.get("one_line")),
                "links": links,
                "evidence": evidence,
                "confidence": _to_str(item.get("confidence"), default="medium"),
            }
        )

    cross_raw = raw.get("cross_domain", [])
    if not isinstance(cross_raw, list):
        issues.append(
            ContractIssue(
                "seam_annotations.cross_domain", "cross_domain is not a list"
            )
        )
        cross_raw = []

    cross_domain = []
    for idx, item in enumerate(cross_raw):
        path = f"seam_annotations.cross_domain[{idx}]"
        if not isinstance(item, dict):
            issues.append(ContractIssue(path, "cross-domain annotation is not an object"))
            continue
        linked_raw = item.get("linked_item_ids", [])
        if not isinstance(linked_raw, list):
            issues.append(
                ContractIssue(
                    f"{path}.linked_item_ids",
                    "linked_item_ids is not a list",
                )
            )
            linked_raw = []
        linked_ids = [
            str(item_id).strip() for item_id in linked_raw if str(item_id).strip()
        ]
        if ids:
            unknown = [item_id for item_id in linked_ids if item_id not in ids]
            for item_id in unknown:
                issues.append(
                    ContractIssue(
                        f"{path}.linked_item_ids",
                        f"unknown item_id: {item_id}",
                    )
                )
            linked_ids = [item_id for item_id in linked_ids if item_id in ids]
        cross_domain.append(
            {
                **_extra_fields(item, {"seam_type", "one_line", "linked_item_ids"}),
                "seam_type": _to_str(item.get("seam_type")),
                "one_line": _to_str(item.get("one_line")),
                "linked_item_ids": linked_ids,
            }
        )

    return {"per_item": per_item, "cross_domain": cross_domain}, [
        issue.to_dict() for issue in issues
    ]


def _normalize_plan_entries(
    raw: Any,
    path: str,
    issues: list[ContractIssue],
    *,
    limit: int | None = None,
) -> list[dict]:
    if not isinstance(raw, list):
        issues.append(ContractIssue(path, "value is not a list"))
        return []

    entries = []
    for idx, item in enumerate(raw):
        item_path = f"{path}[{idx}]"
        if not isinstance(item, dict):
            issues.append(ContractIssue(item_path, "plan entry is not an object"))
            continue
        entries.append(dict(item))
        if limit is not None and len(entries) >= limit:
            break
    return entries


def normalize_cross_domain_plan_artifact(
    raw: Any,
    *,
    deep_dive_count: int = 2,
    worth_reading_count: int = 3,
    connection_count: int = 3,
) -> tuple[dict, list[dict]]:
    """Normalize a persisted or freshly generated cross-domain plan artifact."""
    issues: list[ContractIssue] = []
    if not isinstance(raw, dict):
        issues.append(ContractIssue("cross_domain_plan", "artifact is not an object"))
        raw = {}

    planning_scope = raw.get("planning_scope")
    if not isinstance(planning_scope, dict):
        if planning_scope is not None:
            issues.append(
                ContractIssue(
                    "cross_domain_plan.planning_scope",
                    "planning_scope is not an object",
                )
            )
        planning_scope = {
            "deep_dive_count": deep_dive_count,
            "worth_reading_count": worth_reading_count,
            "connection_count": connection_count,
        }

    known = {
        "schema_version",
        "cross_domain_connections",
        "deep_dives",
        "worth_reading",
        "rejected_alternatives",
        "planning_scope",
    }
    normalized = {
        **_extra_fields(raw, known),
        "schema_version": 1,
        "cross_domain_connections": _normalize_plan_entries(
            raw.get("cross_domain_connections", []),
            "cross_domain_plan.cross_domain_connections",
            issues,
            limit=connection_count,
        ),
        "deep_dives": _normalize_plan_entries(
            raw.get("deep_dives", []),
            "cross_domain_plan.deep_dives",
            issues,
            limit=deep_dive_count,
        ),
        "worth_reading": _normalize_plan_entries(
            raw.get("worth_reading", []),
            "cross_domain_plan.worth_reading",
            issues,
            limit=worth_reading_count,
        ),
        "rejected_alternatives": _normalize_plan_entries(
            raw.get("rejected_alternatives", []),
            "cross_domain_plan.rejected_alternatives",
            issues,
        ),
        "planning_scope": planning_scope,
    }
    return normalized, [issue.to_dict() for issue in issues]


def _normalize_links(raw: Any, path: str, issues: list[ContractIssue]) -> list[dict]:
    if not isinstance(raw, list):
        issues.append(ContractIssue(path, "links is not a list"))
        return []
    links = []
    for idx, link_raw in enumerate(raw):
        link = SourceLink.from_raw(link_raw, f"{path}[{idx}]", issues)
        if link is not None:
            links.append(link.to_dict())
    return links


def _normalize_at_a_glance_entries(
    raw: Any, path: str, issues: list[ContractIssue]
) -> list[dict]:
    if not isinstance(raw, list):
        issues.append(ContractIssue(path, "at_a_glance is not a list"))
        return []

    entries = []
    for idx, item in enumerate(raw):
        item_path = f"{path}[{idx}]"
        if not isinstance(item, dict):
            issues.append(ContractIssue(item_path, "at_a_glance entry is not an object"))
            continue
        hooks_raw = item.get("connection_hooks", [])
        if not isinstance(hooks_raw, list):
            issues.append(
                ContractIssue(
                    f"{item_path}.connection_hooks", "connection_hooks is not a list"
                )
            )
            hooks_raw = []
        hooks = []
        for hook_idx, hook_raw in enumerate(hooks_raw):
            hook = ConnectionHook.from_raw(
                hook_raw, f"{item_path}.connection_hooks[{hook_idx}]", issues
            )
            if hook is not None:
                hooks.append(hook.to_dict())

        known = {
            "item_id",
            "tag",
            "tag_label",
            "headline",
            "context",
            "facts",
            "analysis",
            "source_depth",
            "cross_domain_note",
            "connection_hooks",
            "links",
        }
        entries.append(
            {
                **_extra_fields(item, known),
                "item_id": _to_str(item.get("item_id")),
                "tag": _to_str(item.get("tag")),
                "tag_label": _to_str(item.get("tag_label")),
                "headline": _to_str(item.get("headline")),
                "context": _to_str(item.get("context")),
                "facts": _to_str(item.get("facts")),
                "analysis": _to_str(item.get("analysis")),
                "source_depth": _to_str(item.get("source_depth")),
                "cross_domain_note": _to_str(item.get("cross_domain_note")),
                "connection_hooks": hooks,
                "links": _normalize_links(
                    item.get("links", []), f"{item_path}.links", issues
                ),
            }
        )
    return entries


def _normalize_deep_dive_entries(
    raw: Any, path: str, issues: list[ContractIssue]
) -> list[dict]:
    if not isinstance(raw, list):
        issues.append(ContractIssue(path, "deep_dives is not a list"))
        return []

    entries = []
    for idx, dive in enumerate(raw):
        dive_path = f"{path}[{idx}]"
        if not isinstance(dive, dict):
            issues.append(ContractIssue(dive_path, "deep dive entry is not an object"))
            continue
        known = {
            "headline",
            "body",
            "why_it_matters",
            "further_reading",
            "source_depth",
            "domains_bridged",
        }
        entries.append(
            {
                **_extra_fields(dive, known),
                "headline": _to_str(dive.get("headline")),
                "body": _to_str(dive.get("body")),
                "why_it_matters": _to_str(dive.get("why_it_matters")),
                "further_reading": _normalize_links(
                    dive.get("further_reading", []),
                    f"{dive_path}.further_reading",
                    issues,
                ),
                "source_depth": _to_str(dive.get("source_depth")),
                "domains_bridged": _to_str_list(
                    dive.get("domains_bridged", []),
                    f"{dive_path}.domains_bridged",
                    issues,
                ),
            }
        )
    return entries


def _normalize_cross_domain_connection_entries(
    raw: Any, path: str, issues: list[ContractIssue]
) -> list[dict]:
    if not isinstance(raw, list):
        issues.append(ContractIssue(path, "cross_domain_connections is not a list"))
        return []

    entries = []
    for idx, item in enumerate(raw):
        item_path = f"{path}[{idx}]"
        if not isinstance(item, dict):
            issues.append(
                ContractIssue(item_path, "cross-domain connection is not an object")
            )
            continue
        known = {"title", "summary", "domains", "entities", "why_it_matters"}
        entries.append(
            {
                **_extra_fields(item, known),
                "title": _to_str(item.get("title")),
                "summary": _to_str(item.get("summary")),
                "domains": _to_str_list(
                    item.get("domains", []), f"{item_path}.domains", issues
                ),
                "entities": _to_str_list(
                    item.get("entities", []), f"{item_path}.entities", issues
                ),
                "why_it_matters": _to_str(item.get("why_it_matters")),
            }
        )
    return entries


def _normalize_worth_reading_entries(
    raw: Any, path: str, issues: list[ContractIssue]
) -> list[dict]:
    if not isinstance(raw, list):
        issues.append(ContractIssue(path, "worth_reading is not a list"))
        return []

    entries = []
    for idx, item in enumerate(raw):
        item_path = f"{path}[{idx}]"
        if not isinstance(item, dict):
            issues.append(ContractIssue(item_path, "worth_reading entry is not an object"))
            continue
        known = {"title", "url", "source", "description", "read_time"}
        entries.append(
            {
                **_extra_fields(item, known),
                "title": _to_str(item.get("title")),
                "url": _to_str(item.get("url")),
                "source": _to_str(item.get("source")),
                "description": _to_str(item.get("description")),
                "read_time": _to_str(item.get("read_time")),
            }
        )
    return entries


def normalize_cross_domain_output_artifact(raw: Any) -> tuple[dict, list[dict]]:
    """Normalize a cross-domain execute output before downstream validation."""
    issues: list[ContractIssue] = []
    if not isinstance(raw, dict):
        issues.append(ContractIssue("cross_domain_output", "artifact is not an object"))
        raw = {}

    known = {
        "at_a_glance",
        "deep_dives",
        "cross_domain_connections",
        "market_context",
        "worth_reading",
    }
    normalized = {
        **_extra_fields(raw, known),
        "at_a_glance": _normalize_at_a_glance_entries(
            raw.get("at_a_glance", []), "cross_domain_output.at_a_glance", issues
        ),
        "deep_dives": _normalize_deep_dive_entries(
            raw.get("deep_dives", []), "cross_domain_output.deep_dives", issues
        ),
        "cross_domain_connections": _normalize_cross_domain_connection_entries(
            raw.get("cross_domain_connections", []),
            "cross_domain_output.cross_domain_connections",
            issues,
        ),
        "worth_reading": _normalize_worth_reading_entries(
            raw.get("worth_reading", []), "cross_domain_output.worth_reading", issues
        ),
    }
    if "market_context" in raw:
        normalized["market_context"] = _to_str(raw.get("market_context"))
    return normalized, [issue.to_dict() for issue in issues]
