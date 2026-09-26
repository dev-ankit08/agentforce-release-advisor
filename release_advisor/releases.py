"""Mapping between Salesforce API versions and release names.

Salesforce ships three releases a year and bumps the API version by one each time:
API 60.0 = Spring '24, 61.0 = Summer '24, 62.0 = Winter '25, ... 68.0 = Winter '27.
Winter releases are named after the following calendar year.
"""

from __future__ import annotations

import re

_BASE_API = 60  # Spring '24
_BASE_YEAR = 24
_SEASONS = ["Spring", "Summer", "Winter"]
_LABEL_RE = re.compile(r"(?<![a-z])(Spring|Summer|Winter)[\s_\-]*['’]?\s*(\d{4}|\d{2})(?!\d)", re.IGNORECASE)


def api_to_release(api_version: float | int | str | None) -> str | None:
    """Return the release label (e.g. "Winter '27") for an API version, or None."""
    if api_version is None:
        return None
    try:
        major = int(float(api_version))
    except (TypeError, ValueError):
        return None
    if major < 20:
        return None
    offset = major - _BASE_API
    season = _SEASONS[offset % 3]
    year = _BASE_YEAR + offset // 3 + (1 if season == "Winter" else 0)
    return f"{season} '{year:02d}"


def release_number(label: str | None) -> int | None:
    """Salesforce's internal release number used in docs URLs (Spring '24 = 248, +2 per release)."""
    api = release_to_api(label)
    return None if api is None else 248 + 2 * (api - _BASE_API)


def label_from_release_number(number: int) -> str | None:
    """264 -> "Winter '27" (inverse of release_number)."""
    if number < 248 or number % 2:
        return None
    return api_to_release(_BASE_API + (number - 248) // 2)


def slug(label: str) -> str:
    """"Winter '27" -> "winter27"."""
    api = release_to_api(label)
    if api is None:
        raise ValueError(f"Not a release name: {label!r}")
    season, year = api_to_release(api).split(" '")
    return f"{season.lower()}{year}"


def canonical(label: str | None) -> str | None:
    """Normalise "winter 2027" / "Winter27" / "Winter ’27" to "Winter '27"."""
    return api_to_release(release_to_api(label)) if label else None


def release_to_api(label: str | None) -> int | None:
    """Return the major API version for a label such as "Winter '27" or "Spring 2026"."""
    if not label:
        return None
    match = _LABEL_RE.search(label)
    if not match:
        return None
    season = match.group(1).capitalize()
    year = int(match.group(2)) % 100
    s = _SEASONS.index(season)
    release_year = year - 1 if season == "Winter" else year
    return _BASE_API + (release_year - _BASE_YEAR) * 3 + s
