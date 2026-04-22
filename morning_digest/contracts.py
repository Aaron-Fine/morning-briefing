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
