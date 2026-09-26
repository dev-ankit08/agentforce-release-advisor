"""Enforce "official Salesforce sources only" on every cited URL.

A finding survives only if its source_url (1) is https on an allow-listed host and
(2) was actually returned during this analysis - by the release-notes PDF tools or by
web_search / web_fetch.
"""

from __future__ import annotations

from typing import Any, Iterable
from urllib.parse import parse_qs, urlparse


def host_allowed(url: str, allowed_domains: Iterable[str]) -> bool:
    try:
        parsed = urlparse(url.strip())
    except ValueError:
        return False
    if parsed.scheme != "https" or not parsed.hostname:
        return False
    host = parsed.hostname.lower()
    return any(host == d or host.endswith("." + d) for d in (d.lower() for d in allowed_domains))


UrlKey = tuple[str, str, str, str]


def url_key(url: str) -> UrlKey:
    """Normalise a URL for comparison: host, path, help-article id and release number.

    The fragment (e.g. "#page=12" on a PDF) and other query noise are ignored.
    """
    parsed = urlparse(url.strip())
    host = (parsed.hostname or "").lower().removeprefix("www.")
    path = parsed.path.rstrip("/").lower()
    query = parse_qs(parsed.query)
    article_id = query.get("id", [""])[0].lower()
    release = query.get("release", [""])[0]
    return host, path, article_id, release


def was_seen(url: str, seen: set[UrlKey]) -> bool:
    key = url_key(url)
    if key in seen:
        return True
    # A citation that omits ?release= still matches a retrieved page with the same article.
    return not key[3] and any(s[:3] == key[:3] for s in seen)


def collect_urls(obj: Any, out: set[UrlKey]) -> None:
    """Walk a dumped server-tool result block and record every URL it contains."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key == "url" and isinstance(value, str):
                out.add(url_key(value))
            else:
                collect_urls(value, out)
    elif isinstance(obj, list):
        for item in obj:
            collect_urls(item, out)


def check(url: str, allowed_domains: Iterable[str], seen: set[UrlKey]) -> str | None:
    """Return None if the URL is acceptable, else a short reason."""
    if not host_allowed(url, allowed_domains):
        return "not an official Salesforce source"
    if not was_seen(url, seen):
        return "source was not retrieved during research"
    return None
