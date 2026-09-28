"""Reading plan for the release notes: every page is read, and priority topics come first.

No section is chosen or skipped by hard-coded rules. The whole document, from its first to its last
PDF page, is split into chunks that Claude reads one by one. Coverage is checked in code: a plan
that misses a page is a bug and raises.

Preference: sections and chunks about the priority topics (PRIORITY_TOPICS, by default Agentforce,
Agent Script, AIforce, Claude and other AI topics) are marked as priority. They are
  * read first, with ANTHROPIC_MODEL / ANTHROPIC_EFFORT (other chunks use SCAN_MODEL / SCAN_EFFORT,
    which default to the same),
  * marked as priority-topic findings and listed first in the final report.
A section is a priority section if its title names a priority topic or its pages mention the topics
densely; a chunk elsewhere in the document is a priority chunk if its own pages do.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .release_notes import ReleaseNotesDoc

CHARS_PER_TOKEN_ESTIMATE = 3.5
DEFAULT_PRIORITY_DENSITY = 5.0  # priority-topic mentions per page that make a section or chunk a priority one
FRONT_MATTER = "Front matter"


def estimate_tokens(text: str) -> int:
    return int(len(text) / CHARS_PER_TOKEN_ESTIMATE)


def _topic_patterns(topics: list[str]) -> list[tuple[str, re.Pattern]]:
    out = []
    for topic in topics:
        body = r"\s+".join(re.escape(w) for w in topic.split())
        # Acronyms (AI, LLM, MCP) must match as written; everything else is case-insensitive.
        flags = 0 if topic.isupper() and len(topic) <= 4 else re.IGNORECASE
        out.append((topic, re.compile(rf"(?<![A-Za-z0-9]){body}(?![A-Za-z0-9])", flags)))
    return out


@dataclass
class Chunk:
    index: int  # position in the document (0 = first chunk)
    pdf_pages: list[int]  # 1-based PDF pages, consecutive
    sections: list[str]
    tokens: int
    priority: bool = False
    topic_hits: dict[str, int] = field(default_factory=dict)

    def page_range(self, doc: ReleaseNotesDoc) -> str:
        first, last = self.pdf_pages[0], self.pdf_pages[-1]
        pa, pb = doc.printed_page(first), doc.printed_page(last)
        printed = f"printed {pa}-{pb}, " if pa and pb else ""
        return f"{printed}PDF {first}-{last}"

    def reason(self) -> str:
        if not self.topic_hits:
            return "full read (no priority topics on these pages)"
        top = sorted(self.topic_hits.items(), key=lambda kv: -kv[1])[:5]
        return "priority topics: " + ", ".join(f"{t} x{n}" for t, n in top)


@dataclass
class PrioritySection:
    title: str
    printed_pages: str
    reason: str


@dataclass
class ReadingPlan:
    release: str
    total_pages: int
    chunks: list[Chunk]  # reading order: priority chunks first, then the rest in document order
    priority_sections: list[PrioritySection]
    page_sections: list[str]  # index 0 = PDF page 1

    @property
    def tokens(self) -> int:
        return sum(c.tokens for c in self.chunks)

    def summary(self) -> str:
        pr = [c for c in self.chunks if c.priority]
        return (
            f"All {self.total_pages} PDF pages of the {self.release} release notes in {len(self.chunks)} chunks "
            f"(~{self.tokens:,} tokens); {len(pr)} priority chunk(s) read first."
        )


def page_sections(doc: ReleaseNotesDoc) -> list[str]:
    """Top-level section of every PDF page (pages without a printed number inherit the previous one)."""
    by_printed: dict[int, str] = {}
    for sec in doc.toc():
        for n in range(sec.printed_start, sec.printed_end + 1):
            by_printed.setdefault(n, sec.title)
    out: list[str] = []
    current = FRONT_MATTER
    for pdf in range(1, len(doc.pages) + 1):
        printed = doc.printed_page(pdf)
        if printed is not None and printed in by_printed:
            current = by_printed[printed]
        out.append(current)
    return out


def build_plan(
    doc: ReleaseNotesDoc,
    priority_topics: list[str],
    chunk_tokens: int,
    priority_density: float = DEFAULT_PRIORITY_DENSITY,
) -> ReadingPlan:
    patterns = _topic_patterns(priority_topics)
    sections = page_sections(doc)
    hits_per_page: list[dict[str, int]] = []
    for text in doc.pages:
        hits = {topic: len(rx.findall(text)) for topic, rx in patterns}
        hits_per_page.append({t: n for t, n in hits.items() if n})

    # Priority sections: title names a topic, or the section mentions the topics densely.
    section_pages: dict[str, list[int]] = {}
    for i, title in enumerate(sections):
        section_pages.setdefault(title, []).append(i)
    priority_titles: dict[str, str] = {}
    for title, idxs in section_pages.items():
        title_topics = [t for t, rx in patterns if rx.search(title)]
        total: dict[str, int] = {}
        for i in idxs:
            for t, n in hits_per_page[i].items():
                total[t] = total.get(t, 0) + n
        density = sum(total.values()) / max(1, len(idxs))
        if title_topics:
            priority_titles[title] = f"title names {', '.join(title_topics)}"
        elif density >= priority_density:
            top = sorted(total.items(), key=lambda kv: -kv[1])[:4]
            priority_titles[title] = f"{density:.1f} priority-topic mentions per page ({', '.join(f'{t} x{n}' for t, n in top)})"

    # Chunks: consecutive pages, a new chunk when the priority flag of the section changes or the budget is full.
    chunks: list[Chunk] = []
    pages: list[int] = []
    tokens = 0
    flag = None

    def flush() -> None:
        nonlocal pages, tokens
        if pages:
            secs = list(dict.fromkeys(sections[p - 1] for p in pages))
            chunks.append(Chunk(index=len(chunks), pdf_pages=pages, sections=secs, tokens=tokens))
        pages, tokens = [], 0

    for pdf in range(1, len(doc.pages) + 1):
        page_flag = sections[pdf - 1] in priority_titles
        page_tokens = estimate_tokens(doc.pages[pdf - 1]) + 20
        if pages and (page_flag != flag or tokens + page_tokens > chunk_tokens):
            flush()
        flag = page_flag
        pages.append(pdf)
        tokens += page_tokens
    flush()

    for chunk in chunks:
        total: dict[str, int] = {}
        for p in chunk.pdf_pages:
            for t, n in hits_per_page[p - 1].items():
                total[t] = total.get(t, 0) + n
        chunk.topic_hits = total
        chunk.priority = any(s in priority_titles for s in chunk.sections) or (
            sum(total.values()) / len(chunk.pdf_pages) >= priority_density
        )

    covered = [p for c in chunks for p in c.pdf_pages]
    if sorted(covered) != list(range(1, len(doc.pages) + 1)):
        raise RuntimeError("Reading plan does not cover every page of the release notes exactly once.")

    ordered = [c for c in chunks if c.priority] + [c for c in chunks if not c.priority]
    priority_sections = []
    for sec in doc.toc():
        if sec.title in priority_titles:
            priority_sections.append(PrioritySection(sec.title, f"{sec.printed_start}-{sec.printed_end}", priority_titles[sec.title]))
    return ReadingPlan(doc.release, len(doc.pages), ordered, priority_sections, sections)


def chunk_text(doc: ReleaseNotesDoc, plan: ReadingPlan, chunk: Chunk) -> str:
    """Complete text of a chunk, each page marked with its printed and PDF page and its section."""
    return "\n\n".join(
        f"[{doc.page_label(p)} | {plan.page_sections[p - 1]}]\n{doc.pages[p - 1]}" for p in chunk.pdf_pages
    )
