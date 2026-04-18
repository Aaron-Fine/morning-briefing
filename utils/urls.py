"""Shared URL utilities for the Morning Digest pipeline."""

from urllib.parse import urlparse


def collect_known_urls(
    raw_sources: dict, domain_analysis: dict | None = None
) -> set[str]:
    """Build the set of known-good URLs from raw source data and optionally domain analysis.

    Args:
        raw_sources: Dict containing rss, local_news, and analysis_transcripts lists.
        domain_analysis: Optional dict of domain analysis results. If provided, URLs
            from domain analysis item links are also included.

    Returns:
        Set of known-good URL strings.
    """
    known: set[str] = set()
    for item in raw_sources.get("rss", []):
        if item.get("url"):
            known.add(item["url"])
    for item in raw_sources.get("local_news", []):
        if item.get("url"):
            known.add(item["url"])
    for t in raw_sources.get("analysis_transcripts", []):
        if t.get("url"):
            known.add(t["url"])

    if domain_analysis:
        for domain_result in domain_analysis.values():
            if not isinstance(domain_result, dict):
                continue
            for item in domain_result.get("items", []):
                for link in item.get("links", []):
                    if link.get("url"):
                        known.add(link["url"])

    return known


def extract_domains(urls: set[str]) -> set[str]:
    """Extract unique domains from a set of URLs."""
    return {urlparse(u).netloc for u in urls if urlparse(u).netloc}


def url_domain_allowed(url: str, known_domains: set[str]) -> bool:
    """Check whether a URL's domain is in the set of known-good domains.

    Returns True for empty/missing URLs (no filtering needed).
    """
    if not url:
        return True
    return urlparse(url).netloc in known_domains
