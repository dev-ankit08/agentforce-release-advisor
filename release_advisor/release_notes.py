"""Official Salesforce release-notes PDFs: pick the release, fetch the PDF, extract, search.

Which release: TARGET_RELEASE. The default "latest" asks help.salesforce.com for the current
release-notes version (see help_portal.py); an explicit name such as "Winter '27" pins it.

Where the PDF comes from, in order of preference:
  1. RELEASE_NOTES_DIR       - a PDF you saved yourself (release taken from the filename, e.g.
                               winter27.pdf, or from the cover page).
  2. RELEASE_NOTES_PDF_URLS  - an explicit link, e.g. "Winter '27=https://...pdf".
  3. help.salesforce.com     - the site's own PDF export (what its "PDF" button does). Automatic.
  4. resources.docs.salesforce.com - the historical official URL pattern (releases up to Winter '25).

Each release's document is downloaded once and kept (.cache/release_notes/<release>.pdf plus the
extracted text in <release>.json). It is reused until help.salesforce.com reports a different latest
release; only then is the new release's document downloaded.
"""

from __future__ import annotations

import io
import json
import logging
import math
import os
import re
import threading
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import requests
from pypdf import PdfReader

from . import source_guard
from .config import Settings
from .help_portal import HelpPortalClient, HelpPortalError
from .releases import canonical, label_from_release_number, release_number, release_to_api, slug

log = logging.getLogger(__name__)

HELP_PORTAL_ORIGIN = "help.salesforce.com PDF export"
LATEST_RELEASE_TTL_SECONDS = 6 * 3600
MAX_PDF_BYTES = 150 * 1024 * 1024
MAX_PAGES_PER_READ = 5
SNIPPET_CHARS = 1400
_STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "are", "from", "you", "your", "can", "not", "use",
    "new", "now", "what", "how", "all", "has", "have", "will", "any", "its", "into", "our",
}
_COVER_RE = re.compile(r"((?:Spring|Summer|Winter)\s*['’]?\s*(?:\d{4}|\d{2}))\s+Release\s+Notes", re.IGNORECASE)
_WORD_RE = re.compile(r"[a-z0-9][a-z0-9_\-.']*[a-z0-9]|[a-z0-9]")


class ReleaseNotesUnavailable(RuntimeError):
    pass


def legacy_pdf_url(label: str) -> str:
    return (
        f"https://resources.docs.salesforce.com/{release_number(label)}/latest/en-us/sfdc/pdf/"
        f"salesforce_{slug(label)}_release_notes.pdf"
    )


def help_article_url(label: str) -> str:
    return (
        "https://help.salesforce.com/s/articleView?id=release-notes.salesforce_release_notes.htm"
        f"&release={release_number(label)}&type=5"
    )


def parse_url_map(raw: str) -> dict[str, str]:
    """ "Winter '27=https://a.pdf; Summer '26=https://b.pdf" -> {"Winter '27": "https://a.pdf", ...}"""
    out: dict[str, str] = {}
    for entry in filter(None, (e.strip() for e in raw.split(";"))):
        label, sep, url = entry.partition("=")
        name = canonical(label.strip())
        if not sep or not name:
            raise ValueError(f"Bad RELEASE_NOTES_PDF_URLS entry: {entry!r} (expected \"Winter '27=https://...pdf\")")
        out[name] = url.strip()
    return out


_TOC_LINE_RE = re.compile(r"^(?P<title>\S.*?)[\s.]{5,}(?P<page>\d+)\s*$")
_CHANGES_HEADING_RE = re.compile(r"(?m)^(?P<product>\S[^\n]*?) (?:Release Note Changes|Features Released) by Month\s*$")
CHANGES_LOG_SECTION = "Release Note Changes"


@dataclass
class Section:
    title: str
    printed_start: int
    printed_end: int  # inclusive; < printed_start means the section has no pages of its own

    @property
    def page_count(self) -> int:
        return max(0, self.printed_end - self.printed_start + 1)


@dataclass
class ReleaseNotesDoc:
    release: str
    cite_url: str  # official URL to cite; "#page=N" (PDF page) is appended per page
    origin: str  # where the PDF came from (URL or local file)
    pages: list[str]  # index 0 = PDF page 1

    def __post_init__(self) -> None:
        # Printed page numbers come from each page's footer (its last line), e.g. PDF 162 -> "158".
        self.printed: list[int | None] = [_footer_number(p) for p in self.pages]
        self._pdf_by_printed = {n: i + 1 for i, n in enumerate(self.printed) if n is not None}
        self._toc: list[Section] | None = None

    # ---- page numbers ------------------------------------------------------------------------

    def page_url(self, pdf_page: int) -> str:
        return f"{self.cite_url}#page={pdf_page}"

    def pdf_page(self, printed_page: int) -> int | None:
        return self._pdf_by_printed.get(printed_page)

    def printed_page(self, pdf_page: int) -> int | None:
        return self.printed[pdf_page - 1] if 1 <= pdf_page <= len(self.pages) else None

    def page_label(self, pdf_page: int) -> str:
        printed = self.printed_page(pdf_page)
        return f"Printed page {printed} | PDF page {pdf_page}" if printed else f"PDF page {pdf_page}"

    def text_for_printed(self, printed_page: int) -> str | None:
        pdf = self.pdf_page(printed_page)
        return self.pages[pdf - 1] if pdf else None

    # ---- sections (from the printed table of contents) -----------------------------------------

    def toc(self) -> list[Section]:
        """Top-level sections from the table of contents at the front of the PDF."""
        if self._toc is None:
            entries: list[tuple[str, int]] = []
            for text in self.pages[:12]:
                for line in text.splitlines():
                    m = _TOC_LINE_RE.match(line.strip())
                    if m:
                        entries.append((m.group("title").strip(" ."), int(m.group("page"))))
            last_printed = max((n for n in self.printed if n is not None), default=0)
            self._toc = [
                Section(title, start, (entries[i + 1][1] - 1) if i + 1 < len(entries) else last_printed)
                for i, (title, start) in enumerate(entries)
            ]
        return self._toc

    def find_section(self, title: str) -> Section:
        wanted = _norm_title(title)
        for sec in self.toc():
            if _norm_title(sec.title) == wanted:
                return sec
        matches = [s for s in self.toc() if wanted and wanted in _norm_title(s.title)]
        if len(matches) == 1:
            return matches[0]
        available = ", ".join(s.title for s in self.toc()) or "none found"
        raise ReleaseNotesUnavailable(
            f"Section '{title}' is not in the {self.release} release notes table of contents. Available: {available}"
        )

    def section_text(self, title: str) -> str:
        """The complete text of a top-level section, each page marked with its printed and PDF page."""
        sec = self.find_section(title)
        parts = []
        for printed in range(sec.printed_start, sec.printed_end + 1):
            pdf = self.pdf_page(printed)
            if pdf:
                parts.append(f"[{self.page_label(pdf)} | {sec.title}]\n{self.pages[pdf - 1]}")
        if not parts:
            return f"[{sec.title}: no pages of its own in this release's notes]"
        return "\n\n".join(parts)

    def changes_log_text(self, product: str) -> str:
        """The "<product> Release Note Changes by Month" entries from the changes log."""
        log_sec = self.find_section(CHANGES_LOG_SECTION)
        chunks: list[str] = []
        for printed in range(log_sec.printed_start, log_sec.printed_end + 1):
            pdf = self.pdf_page(printed)
            if pdf:
                chunks.append(f"[{self.page_label(pdf)} | Release Note Changes]\n{self.pages[pdf - 1]}")
        text = "\n".join(chunks)
        headings = list(_CHANGES_HEADING_RE.finditer(text))
        for i, m in enumerate(headings):
            if _norm_title(m.group("product")) == _norm_title(product):
                end = headings[i + 1].start() if i + 1 < len(headings) else len(text)
                body = text[m.start():end].strip()
                # keep the page marker that precedes the heading so citations stay possible
                marker = text.rfind("[Printed page", 0, m.start())
                prefix = text[marker: text.find("]", marker) + 1] + "\n" if marker != -1 else ""
                return prefix + body
        return ""

    def toc_listing(self) -> str:
        return "\n".join(
            f"- {s.title} (printed pages {s.printed_start}-{s.printed_end}, {s.page_count} pages)" for s in self.toc()
        )


def _footer_number(text: str) -> int | None:
    lines = [line.strip() for line in text.strip().splitlines() if line.strip()]
    return int(lines[-1]) if lines and lines[-1].isdigit() else None


def _norm_title(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower().replace("’", "'")).strip()


def _terms(text: str) -> list[str]:
    return [w for w in _WORD_RE.findall(text.lower()) if len(w) >= 3 and w not in _STOPWORDS]


class ReleaseNotesLibrary:
    def __init__(
        self,
        settings: Settings,
        session: requests.Session | None = None,
        portal: HelpPortalClient | None = None,
    ):
        self.settings = settings
        self._session = session or requests.Session()
        self._session.headers.setdefault("User-Agent", "agentforce-release-advisor")
        self._portal = portal or HelpPortalClient()
        self._cache_dir = Path(settings.release_notes_cache_dir)
        self._docs: dict[str, tuple[ReleaseNotesDoc, float]] = {}
        self._lock = threading.Lock()
        self._url_map = parse_url_map(settings.release_notes_pdf_urls)
        self._cover_labels: dict[tuple, str | None] = {}
        self._latest: tuple[str, float] | None = None

    # ---- target release ----------------------------------------------------------------------

    def target_release(self) -> str | None:
        """The release every agent is assessed against, or None when unrestricted."""
        raw = (self.settings.target_release or "").strip()
        if not raw:
            return None
        if raw.lower() != "latest":
            label = canonical(raw)
            if not label:
                raise ReleaseNotesUnavailable(f"TARGET_RELEASE={raw!r} is not a release name (e.g. \"Winter '27\" or latest).")
            return label
        return self.latest_release()

    def latest_release(self) -> str:
        """Current release according to help.salesforce.com (cached for a few hours)."""
        if self._latest and time.time() - self._latest[1] < LATEST_RELEASE_TTL_SECONDS:
            return self._latest[0]
        try:
            label = label_from_release_number(self._portal.latest_release_number())
            if not label:
                raise HelpPortalError("unrecognised release number")
        except HelpPortalError as exc:
            # Keep working with the newest document we already have (downloaded or provided manually).
            known = set(self.configured_releases()) | set(self.downloaded_releases())
            if not known:
                raise ReleaseNotesUnavailable(
                    f"Could not determine the latest release from help.salesforce.com ({exc}). "
                    "Set TARGET_RELEASE explicitly or add the PDF to RELEASE_NOTES_DIR."
                ) from exc
            label = max(known, key=lambda l: release_to_api(l) or 0)
            log.warning("Latest release lookup failed (%s); using newest available document: %s", exc, label)
        self._latest = (label, time.time())
        return label

    # ---- discovery ---------------------------------------------------------------------------

    def _local_files(self) -> dict[str, Path]:
        folder = self.settings.release_notes_dir
        if not folder or not os.path.isdir(folder):
            return {}
        found: dict[str, Path] = {}
        for path in sorted(Path(folder).glob("*.pdf")):
            label = canonical(path.stem) or self._label_from_cover(path)
            if label:
                found[label] = path
            else:
                log.warning("Ignoring %s: cannot tell which release it covers (rename it, e.g. winter27.pdf)", path)
        return found

    def _label_from_cover(self, path: Path) -> str | None:
        """Read the release name from the first pages, e.g. "Salesforce Winter '27 Release Notes"."""
        stat = path.stat()
        key = (str(path), stat.st_mtime, stat.st_size)
        if key not in self._cover_labels:
            label = None
            try:
                reader = PdfReader(str(path))
                cover = " ".join((reader.pages[i].extract_text() or "") for i in range(min(3, len(reader.pages))))
                match = _COVER_RE.search(cover)
                label = canonical(match.group(1)) if match else None
            except Exception as exc:
                log.warning("Could not read %s: %s", path, exc)
            self._cover_labels[key] = label
        return self._cover_labels[key]

    def configured_releases(self) -> dict[str, str]:
        """Releases with an explicitly provided PDF (local file or URL) -> origin."""
        out = {label: url for label, url in self._url_map.items()}
        out.update({label: str(path) for label, path in self._local_files().items()})
        return out

    # ---- loading -----------------------------------------------------------------------------

    def downloaded_releases(self) -> dict[str, int]:
        """Releases whose document is already cached on disk -> page count (0 = PDF kept, text not extracted)."""
        out: dict[str, int] = {}
        if not self._cache_dir.is_dir():
            return out
        for path in self._cache_dir.glob("*.json"):
            label = canonical(path.stem)
            if not label:
                continue
            try:
                out[label] = len(json.loads(path.read_text(encoding="utf-8")).get("pages", []))
            except (OSError, ValueError):
                continue
        for path in self._cache_dir.glob("*.pdf"):
            label = canonical(path.stem)
            if label:
                out.setdefault(label, 0)
        return out

    def get(self, release: str, progress=None, refresh: bool = False) -> ReleaseNotesDoc:
        """Return the release's notes. A document is downloaded once per release and reused after that;
        refresh=True forces a new download (manual use, e.g. when Salesforce publishes corrections)."""
        label = canonical(release)
        if not label:
            raise ReleaseNotesUnavailable(f"'{release}' is not a Salesforce release name (e.g. \"Winter '27\").")
        target = self.target_release()
        if target and label != target:
            raise ReleaseNotesUnavailable(
                f"Only the {target} release notes are in scope (TARGET_RELEASE). Use the {target} notes instead."
            )
        with self._lock:
            if not refresh and label in self._docs:
                return self._docs[label][0]
            doc, fetched_at = self._load(label, progress, refresh)
            self._docs[label] = (doc, fetched_at)
            return doc

    def _load(self, label: str, progress=None, refresh: bool = False) -> tuple[ReleaseNotesDoc, float]:
        progress = progress or (lambda _m: None)
        text_cache = self._cache_dir / f"{slug(label)}.json"
        pdf_cache = self._cache_dir / f"{slug(label)}.pdf"
        local = self._local_files().get(label)
        if local is not None:
            origin, cite = str(local), help_article_url(label)
        elif label in self._url_map:
            origin = cite = self._url_map[label]
        else:
            origin, cite = HELP_PORTAL_ORIGIN, help_article_url(label)

        # 1. This release's document is already downloaded and extracted -> reuse it.
        if not refresh and text_cache.exists():
            try:
                data = json.loads(text_cache.read_text(encoding="utf-8"))
            except ValueError:
                data = {}
            if data.get("origin") == origin and data.get("pages"):
                log.info("%s release notes already downloaded (%d pages) - reusing", label, len(data["pages"]))
                return ReleaseNotesDoc(label, data["cite_url"], origin, data["pages"]), data.get("fetched_at", 0)

        # 2. The PDF is already on disk (manual copy, or an earlier download whose text cache is gone).
        if local is not None:
            pdf_bytes = local.read_bytes()
        elif not refresh and pdf_cache.exists():
            log.info("%s release notes PDF already downloaded - re-extracting text", label)
            pdf_bytes = pdf_cache.read_bytes()
        # 3. A release we don't have yet (or a forced refresh) -> download once and keep the PDF.
        else:
            progress(f"New release {label} detected - downloading its release notes")
            if origin == HELP_PORTAL_ORIGIN:
                pdf_bytes = self._from_help_portal(label, progress)
            else:
                pdf_bytes = self._download(label, origin)
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            pdf_cache.write_bytes(pdf_bytes)

        pages = self._extract(pdf_bytes, origin)
        fetched_at = time.time()
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        text_cache.write_text(
            json.dumps({"origin": origin, "cite_url": cite, "fetched_at": fetched_at, "pages": pages}),
            encoding="utf-8",
        )
        log.info("Loaded %s release notes: %d pages from %s", label, len(pages), origin)
        return ReleaseNotesDoc(label, cite, origin, pages), fetched_at

    def _from_help_portal(self, label: str, progress=None) -> bytes:
        try:
            return self._portal.download_release_notes_pdf(release_number(label), progress=progress)
        except HelpPortalError as portal_exc:
            # Older releases are still published at a static official URL.
            try:
                return self._download(label, legacy_pdf_url(label))
            except ReleaseNotesUnavailable:
                raise ReleaseNotesUnavailable(
                    f"Could not fetch the {label} release notes PDF from help.salesforce.com ({portal_exc}). "
                    f"As a fallback, save it with the PDF button on {help_article_url(label)} into "
                    f"RELEASE_NOTES_DIR."
                ) from portal_exc

    def _download(self, label: str, url: str) -> bytes:
        if not source_guard.host_allowed(url, self.settings.allowed_domains):
            raise ReleaseNotesUnavailable(f"Refusing to download {url}: not an official Salesforce domain.")
        try:
            resp = self._session.get(url, timeout=120, stream=True)
        except requests.RequestException as exc:
            raise ReleaseNotesUnavailable(f"Could not download {label} release notes: {exc}") from exc
        if resp.status_code == 404:
            raise ReleaseNotesUnavailable(f"No official PDF found for {label} at {url}.")
        if not resp.ok:
            raise ReleaseNotesUnavailable(f"Download of {label} release notes failed: HTTP {resp.status_code}")
        buf = io.BytesIO()
        for chunk in resp.iter_content(1 << 20):
            buf.write(chunk)
            if buf.tell() > MAX_PDF_BYTES:
                raise ReleaseNotesUnavailable(f"{url} is larger than {MAX_PDF_BYTES // (1 << 20)} MB.")
        data = buf.getvalue()
        if not data.startswith(b"%PDF"):
            raise ReleaseNotesUnavailable(f"{url} did not return a PDF.")
        return data

    @staticmethod
    def _extract(pdf_bytes: bytes, origin: str) -> list[str]:
        try:
            reader = PdfReader(io.BytesIO(pdf_bytes))
            pages = [(page.extract_text() or "") for page in reader.pages]
        except Exception as exc:
            raise ReleaseNotesUnavailable(f"Could not read PDF {origin}: {exc}") from exc
        if not any(p.strip() for p in pages):
            raise ReleaseNotesUnavailable(f"PDF {origin} contains no extractable text.")
        return [re.sub(r"[ \t]+", " ", p).strip() for p in pages]

    # ---- querying ----------------------------------------------------------------------------

    def search(self, release: str, query: str, max_results: int = 6) -> list[dict]:
        doc = self.get(release)
        phrases = [p.lower() for p in re.findall(r'"([^"]+)"', query)]
        terms = list(dict.fromkeys(_terms(query)))
        if not terms and not phrases:
            return []
        lowered = [p.lower() for p in doc.pages]
        n = len(lowered)
        df = {t: sum(1 for p in lowered if t in p) for t in terms}
        idf = {t: math.log((n + 1) / (df[t] + 1)) + 0.1 for t in terms}

        scored = []
        for i, text in enumerate(lowered):
            counts = Counter(w for w in _WORD_RE.findall(text) if w in idf)
            score = sum(min(counts[t], 5) * idf[t] for t in terms)
            score += sum(8.0 for ph in phrases if ph in text)
            score *= 1 + 0.15 * sum(1 for t in terms if counts[t])  # reward covering more terms
            if score > 0:
                scored.append((score, i))
        scored.sort(reverse=True)

        results = []
        for _, i in scored[:max_results]:
            text = doc.pages[i]
            anchor_terms = sorted((t for t in terms if t in lowered[i]), key=lambda t: -idf[t])
            anchor = phrases[0] if phrases and phrases[0] in lowered[i] else (anchor_terms[0] if anchor_terms else "")
            pos = lowered[i].find(anchor) if anchor else 0
            start = max(0, pos - SNIPPET_CHARS // 3)
            snippet = text[start : start + SNIPPET_CHARS]
            results.append({"printed_page": doc.printed_page(i + 1), "pdf_page": i + 1, "snippet": snippet})
        return results

    def read_pages(self, release: str, start: int, end: int) -> list[dict]:
        """Full text of printed pages start..end (at most MAX_PAGES_PER_READ)."""
        doc = self.get(release)
        end = min(end, start + MAX_PAGES_PER_READ - 1)
        out = []
        for printed in range(max(1, start), end + 1):
            pdf = doc.pdf_page(printed)
            if pdf:
                out.append({"printed_page": printed, "pdf_page": pdf, "text": doc.pages[pdf - 1]})
        return out
