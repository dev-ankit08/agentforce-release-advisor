"""Enforce "strictly from the release notes": every item's quote must appear on its cited page.

An item is kept only if its release_note_quote, after normalisation (case, whitespace, bullets,
quote/apostrophe styles, hyphenation at line breaks), is found on the cited printed page or an
adjacent page (quotes can run across a page break). Anything else is dropped and counted.
"""

from __future__ import annotations

import re

from .release_notes import ReleaseNotesDoc

MIN_QUOTE_CHARS = 20

_TRANSLATE = str.maketrans({
    "’": "'", "‘": "'", "ʼ": "'", "“": '"', "”": '"', "–": "-", "—": "-", " ": " ",
    "•": " ", "�": " ",
})


def normalize(text: str) -> str:
    text = text.translate(_TRANSLATE).lower()
    text = re.sub(r"-\s*\n\s*", "", text)  # words hyphenated across lines
    text = re.sub(r"[^a-z0-9']+", " ", text)  # drop punctuation, bullets, quotes
    return re.sub(r"\s+", " ", text).strip()


def _strip_footer(page: str) -> str:
    """Drop the running footer ("Salesforce Release Notes <section>" + page number) so quotes that
    continue onto the next page still match."""
    lines = page.rstrip().splitlines()
    if lines and lines[-1].strip().isdigit():
        lines.pop()
        if lines and lines[-1].strip().startswith("Salesforce Release Notes"):
            lines.pop()
    return "\n".join(lines)


def check(quote: str, printed_page: int, doc: ReleaseNotesDoc) -> str | None:
    """Return None if the quote is verified on the page, else a short reason."""
    if doc.pdf_page(printed_page) is None:
        return f"page {printed_page} does not exist in the {doc.release} release notes"
    needle = normalize(quote)
    if len(needle) < MIN_QUOTE_CHARS:
        return "quote too short to verify"
    pages = [doc.text_for_printed(p) for p in (printed_page - 1, printed_page, printed_page + 1)]
    window = normalize(" ".join(_strip_footer(p) for p in pages if p))
    if needle in window:
        return None
    return f"quote not found on page {printed_page}"
