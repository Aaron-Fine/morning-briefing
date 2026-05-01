"""Shared URL utilities for the Morning Digest pipeline."""

from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

_URL_FIELDS = ("url", "final_url", "resolved_url", "canonical_url")
_TRACKING_QUERY_PREFIXES = ("utm_",)
_TRACKING_QUERY_KEYS = {
    "fbclid",
    "gclid",
    "igshid",
    "mc_cid",
    "mc_eid",
}


def registered_domain(url: str) -> str:
    """Return the registered domain (e.g. 'example.com') for a URL."""
    if not url:
        return ""
    parsed = urlparse(str(url).strip())
    netloc = parsed.netloc or ""
    # Remove port if present
    if ":" in netloc:
        netloc = netloc.split(":")[0]
    # Remove www. prefix for normalization
    if netloc.lower().startswith("www."):
        netloc = netloc[4:]
    return netloc.lower()


def canonicalize_url(url: str) -> str:
    """Return a stable comparison form for a publisher URL.

    This intentionally preserves path and non-tracking query parameters while
    normalizing harmless drift such as fragments, scheme/netloc casing,
    trailing slashes, and common tracking query fields.
    """
    if not url:
        return ""
    parsed = urlparse(str(url).strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""

    query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.lower().startswith(_TRACKING_QUERY_PREFIXES)
        and key.lower() not in _TRACKING_QUERY_KEYS
    ]
    path = parsed.path or "/"
    if path != "/":
        path = path.rstrip("/")
    return urlunparse(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            path,
            "",
            urlencode(query, doseq=True),
            "",
        )
    )


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
        for field in _URL_FIELDS:
            if item.get(field):
                known.add(item[field])
    for item in raw_sources.get("local_news", []):
        for field in _URL_FIELDS:
            if item.get(field):
                known.add(item[field])
    for t in raw_sources.get("analysis_transcripts", []):
        for field in _URL_FIELDS:
            if t.get(field):
                known.add(t[field])

    if domain_analysis:
        for domain_result in domain_analysis.values():
            if not isinstance(domain_result, dict):
                continue
            for item in domain_result.get("items", []):
                for link in item.get("links", []):
                    if link.get("url"):
                        known.add(link["url"])

    return known


def collect_canonical_urls(known_urls: set[str]) -> set[str]:
    """Return canonical URL comparison keys for known source URLs."""
    return {canonical for url in known_urls if (canonical := canonicalize_url(url))}


def url_known(url: str, known_urls: set[str]) -> bool:
    """Return True when a URL is exactly or canonically source-backed."""
    if not url:
        return True
    if url in known_urls:
        return True
    canonical = canonicalize_url(url)
    return bool(canonical and canonical in collect_canonical_urls(known_urls))


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
