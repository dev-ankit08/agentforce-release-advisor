"""Render reports and agent lists as Slack Block Kit messages."""

from __future__ import annotations

from .report import PREVIEW_AVAILABILITY, FinalReport
from .sources import AgentRef

SECTION_TEXT_LIMIT = 2900  # Slack hard limit is 3000 chars per section text
STATUS_EMOJI = {"Green": ":large_green_circle:", "Amber": ":large_orange_circle:", "Red": ":red_circle:"}
KIND_LABEL = {"agent_script": "Agent Script", "legacy_planner": "Legacy Agent Builder"}


def esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _cite(report: FinalReport, item) -> str:
    """Slack link to the cited page, e.g. <...#page=164|p. 160 (PDF p. 164)> plus the section."""
    label = report.citation_label(item.printed_page)
    url = report.citation_url(item.printed_page)
    ref = f"<{url}|{label}>" if url else label
    return f"_{esc(item.section)}, {ref}_"


def _section(text: str) -> dict:
    if len(text) > SECTION_TEXT_LIMIT:
        text = text[: SECTION_TEXT_LIMIT - 1] + "…"
    return {"type": "section", "text": {"type": "mrkdwn", "text": text}}


def _context(text: str) -> dict:
    return {"type": "context", "elements": [{"type": "mrkdwn", "text": text[:SECTION_TEXT_LIMIT]}]}


def _coverage_warnings(report: FinalReport) -> list[str]:
    lines = list(report.dependency_notes)
    if report.coverage and report.coverage.pages_not_read:
        lines += report.coverage.failures
        lines.append(f"{len(report.coverage.pages_not_read)} release-notes page(s) could not be read; findings "
                     "on those pages may be missing.")
    return lines


def _split_enhancements(report: FinalReport) -> tuple[list, list]:
    """(generally available or unlabeled, beta / pilot / developer preview)."""
    items = report.submitted.recommended_enhancements
    return ([e for e in items if e.availability not in PREVIEW_AVAILABILITY],
            [e for e in items if e.availability in PREVIEW_AVAILABILITY])


MAX_BLOCKS_PER_MESSAGE = 45  # Slack allows 50


def _item_block(report: FinalReport, heading: str, cells: list[tuple[str, str]], item) -> dict:
    fields = [{"type": "mrkdwn", "text": f"*{label}*\n{esc(value)}"[:1990]} for label, value in cells if value]
    fields.append({"type": "mrkdwn", "text": f"*Source*\n{_cite(report, item)}"[:1990]})
    return {"type": "section", "text": {"type": "mrkdwn", "text": heading[:SECTION_TEXT_LIMIT]}, "fields": fields[:10]}


def _enh_label(e) -> str:
    return "" if e.availability == "Generally Available" else f" _({esc(e.availability)})_"


def _summary_lines(report: FinalReport) -> dict[str, list[str]]:
    """One line per item for the overview message."""
    s = report.submitted
    ga, preview = _split_enhancements(report)
    page = lambda i: f"p. {i.printed_page}"
    return {
        "breaking": [f"• *[{f['severity']}]* {esc(f['title'])} _(static check)_" for f in report.static_findings]
                    + [f"• *[{i.severity}]* {esc(i.title)} · {page(i)}" for i in s.breaking_issues],
        "upcoming": [f"• *[{c.severity}]* {esc(c.title)} — _{esc(c.effective)}_ · {page(c)}" for c in s.upcoming_changes],
        "ga": [f"• {esc(e.feature)} · {page(e)}" for e in ga],
        "preview": [f"• {esc(e.feature)}{_enh_label(e)} · {page(e)}" for e in preview],
    }


def _lines_section(title: str, lines: list[str]) -> list[dict]:
    if not lines:
        return [_section(f"*{title} (0)*\n_None found._")]
    out, chunk = [], f"*{title} ({len(lines)})*"
    for line in lines:
        if len(chunk) + len(line) + 1 > SECTION_TEXT_LIMIT:
            out.append(_section(chunk))
            chunk = ""
        chunk = f"{chunk}\n{line}" if chunk else line
    return out + [_section(chunk)]


def render_report(report: FinalReport, from_cache: bool = False) -> tuple[str, list[dict]]:
    """The overview message: status, summary, counts and one line per item. Details follow in the thread."""
    s = report.submitted
    emoji = STATUS_EMOJI[report.status]
    release = s.current_release
    headline = f"{s.agent_name} — {release} readiness {report.score}/100 {report.status}"
    lines = _summary_lines(report)

    project = f"API v{report.project_api_version} ({report.project_release})" if report.project_api_version else "API version unknown"
    meta = (
        f"{KIND_LABEL.get(report.agent_kind, report.agent_kind)} · {esc(report.location)} @ `{report.revision[:7]}` · "
        f"Project {project} · Release assessed *{esc(release)}*"
    )
    p = s.agent_profile
    profile = (
        f"*Agent profile* _(from your repository)_\n*Use case:* {esc(p.business_use_case)}\n"
        f"*Capabilities:* {esc(', '.join(p.capabilities))}\n*Impact value:* {esc(p.impact_value)}"
    )
    glance = (
        f"*At a glance:* :red_circle: {len(lines['breaking'])} must fix · :large_yellow_circle: {len(lines['upcoming'])} upcoming · "
        f":large_green_circle: {len(lines['ga'])} GA enhancement(s) · :test_tube: {len(lines['preview'])} beta/pilot"
    )

    blocks: list[dict] = [
        {"type": "header", "text": {"type": "plain_text", "text": f"{headline}"[:150], "emoji": True}},
        _context(meta),
        _section(f"{emoji} {esc(s.executive_summary)}"),
        _section(glance),
        _section(profile),
        {"type": "divider"},
        *_lines_section(":red_circle: Breaking / must fix", lines["breaking"]),
        *_lines_section(":large_yellow_circle: Upcoming changes needing action", lines["upcoming"]),
        *_lines_section(":large_green_circle: Enhancements — generally available", lines["ga"]),
        *_lines_section(":test_tube: Enhancements — beta, pilot or preview (try in a sandbox)", lines["preview"]),
    ]

    footer: list[str] = [":thread: *Full details for every item (today → this release → what to do) are in the thread below.*"]
    footer += [esc(n) for n in s.notes]
    if report.score_breakdown:
        footer.append("Score: 100 " + " ".join(esc(b.split(" ", 1)[0]) for b in report.score_breakdown))
    if report.removed_findings:
        footer.append(f"{len(report.removed_findings)} item(s) removed — release-notes quote or repository excerpt "
                      "could not be verified.")
    footer += [f":warning: {esc(line)}" for line in _coverage_warnings(report)]
    if report.coverage:
        c = report.coverage
        footer.append(
            f"Read {c.pages_read}/{c.total_pdf_pages} release-notes pages in {c.chunks} chunks; priority topics first"
            + (f" ({', '.join(esc(s.section) for s in c.priority_sections[:6])})" if c.priority_sections else "")
            + f". Agent scan: {len(report.dependencies_scanned)} file(s) incl. dependencies."
        )
    footer.append(
        f"Evidence: official Salesforce {esc(release)} release notes only; every item is tied to your agent's "
        "script or metadata. Page numbers are printed page numbers." + (" _Cached result._" if from_cache else "")
    )
    blocks.append({"type": "divider"})
    blocks.append(_context("\n".join(f"• {line}" for line in footer)))
    return f"{emoji} {headline}", blocks[:50]


def render_report_details(report: FinalReport) -> list[tuple[str, list[dict]]]:
    """Thread replies: one message per section with every item as Today / This release / What to do."""
    s = report.submitted
    release = s.current_release
    ga, preview = _split_enhancements(report)

    def enh(e) -> dict:
        return _item_block(report, f"*{esc(e.feature)}*{_enh_label(e)}\n_Applies to:_ {esc(e.applies_to)}",
                           [("Today in your agent", e.current_state), (f"What {release} adds", e.benefit),
                            ("How to adopt", e.how_to_adopt)], e)

    groups = [
        (":red_circle: Breaking / must fix", [
            _section(f"*[{f['severity']}] {esc(f['title'])}* _(static check of your repository)_\n"
                     f"{esc(f['detail'])}\n_Where:_ `{esc(f['element'])}`") for f in report.static_findings
        ] + [
            _item_block(report, f"*[{i.severity}] {esc(i.title)}*",
                        [("Today in your agent", i.current_state), (f"{release} change", i.release_change),
                         ("What to do", i.fix)], i) for i in s.breaking_issues
        ]),
        (":large_yellow_circle: Upcoming changes needing action", [
            _item_block(report, f"*[{c.severity}] {esc(c.title)}* — _{esc(c.effective)}_",
                        [("Today in your agent", c.current_state), ("What's coming", c.release_change),
                         ("What to do", c.action_needed)], c) for c in s.upcoming_changes
        ]),
        (":large_green_circle: Enhancements — generally available (ready to adopt)", [enh(e) for e in ga]),
        (":test_tube: Enhancements — beta, pilot or preview (try in a sandbox first)", [enh(e) for e in preview]),
    ]
    messages: list[tuple[str, list[dict]]] = []
    for title, items in groups:
        if not items:
            continue
        page: list[dict] = [_section(f"*{title} ({len(items)})*")]
        for item in items:
            if len(page) + 2 > MAX_BLOCKS_PER_MESSAGE:
                messages.append((title, page))
                page = [_section(f"*{title} (continued)*")]
            page += [item, {"type": "divider"}]
        messages.append((title, page[:-1]))
    return messages


def _cell(text: str) -> str:
    return (text or "—").replace("|", "\\|").replace("\r", "").replace("\n", "<br>").strip()


def _table(headers: list[str], rows: list[list[str]]) -> list[str]:
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    out += ["| " + " | ".join(_cell(c) for c in row) + " |" for row in rows]
    return out + [""]


def render_markdown(report: FinalReport) -> str:
    """The complete report as Markdown (attached to the Slack thread, or written by the CLI)."""
    s = report.submitted
    p = s.agent_profile
    release = s.current_release
    ga, preview = _split_enhancements(report)
    ids: list[tuple[str, object]] = []  # (id, item) in the order shown, for the evidence section

    def source(item) -> str:
        url = report.citation_url(item.printed_page)
        label = report.citation_label(item.printed_page).split(" (")[0]
        return f"[{label}]({url})" if url else label

    def tag(prefix: str, item) -> str:
        ident = f"{prefix}{sum(1 for i, _ in ids if i.startswith(prefix)) + 1}"
        ids.append((ident, item))
        return ident

    n_break = len(report.static_findings) + len(s.breaking_issues)
    out = [
        f"# {s.agent_name} — {release} release readiness: {report.score}/100 ({report.status})",
        "",
        f"- Definition: {KIND_LABEL.get(report.agent_kind, report.agent_kind)}, {report.location} @ `{report.revision[:7]}`",
        f"- Project API version: {report.project_api_version or 'unknown'} ({report.project_release or 'n/a'})",
        f"- Release assessed: {release}" + (f"; later release named in the notes: {s.upcoming_release}" if s.upcoming_release not in ("", "n/a") else ""),
        "",
        "## Executive summary",
        "",
        s.executive_summary,
        "",
        "## At a glance",
        "",
        *_table(["", "Count", "What it means"], [
            ["🔴 Breaking / must fix", str(n_break), f"Changes in {release} that need a change in your agent now"],
            ["🟡 Upcoming changes", str(len(s.upcoming_changes)), "Announced for a later date; plan the work"],
            ["🟢 Enhancements — generally available", str(len(ga)), "Ready to adopt in production"],
            ["🧪 Enhancements — beta / pilot / preview", str(len(preview)), "Try in a sandbox first"],
        ]),
        "## Agent profile (from your repository)",
        "",
        f"**Business use case:** {p.business_use_case}",
        "",
        "**Capabilities:**",
        *[f"- {c}" for c in p.capabilities],
        "",
        "**Key metadata:**",
        *[f"- {m}" for m in p.key_metadata],
        "",
        f"**Impact value:** {p.impact_value}",
        "",
        "## 🔴 Breaking / must fix",
        "",
    ]
    if report.static_findings:
        out += ["**Found in your repository (static checks):**", ""]
        out += _table(["Severity", "Issue", "Where", "Detail"],
                      [[f["severity"], f["title"], f"`{f['element']}`", f["detail"]] for f in report.static_findings])
    if s.breaking_issues:
        out += _table(
            ["#", "Severity", "What it means for your agent", "Today in your agent", f"{release} change", "What to do", "Source"],
            [[tag("B", i), i.severity, f"**{i.title}**", i.current_state, i.release_change, i.fix, source(i)]
             for i in s.breaking_issues])
    if not n_break:
        out += [f"_Nothing in the {release} release notes breaks this agent._", ""]

    out += ["## 🟡 Upcoming changes needing action", ""]
    if s.upcoming_changes:
        out += _table(
            ["#", "Severity", "What it means for your agent", "Today in your agent", "What's coming", "When", "What to do", "Source"],
            [[tag("U", c), c.severity, f"**{c.title}**", c.current_state, c.release_change, c.effective, c.action_needed, source(c)]
             for c in s.upcoming_changes])
    else:
        out += ["_None found in the release notes._", ""]

    out += ["## 🟢 Recommended enhancements", ""]
    headers = ["#", "Enhancement for your agent", "Applies to", "Today in your agent", f"What {release} adds", "How to adopt", "Source"]
    out += ["### Generally available — ready to adopt", ""]
    if ga:
        out += _table(headers, [
            [tag("G", e), f"**{e.feature}**" + (" _(availability not labeled in the notes)_" if e.availability == "Not stated" else ""),
             e.applies_to, e.current_state, e.benefit, e.how_to_adopt, source(e)] for e in ga])
    else:
        out += ["_None found in the release notes._", ""]
    out += ["### Beta, pilot and preview — try in a sandbox first", ""]
    if preview:
        out += _table(headers[:2] + ["Status"] + headers[2:], [
            [tag("P", e), f"**{e.feature}**", e.availability, e.applies_to, e.current_state, e.benefit, e.how_to_adopt, source(e)]
            for e in preview])
    else:
        out += ["_None found in the release notes._", ""]

    if ids:
        out += ["## Evidence", "",
                "Each item is backed by the release notes (verbatim, checked against the cited page) and by your "
                "repository (verbatim, checked against the cited file).", ""]
        for ident, item in ids:
            url = report.citation_url(item.printed_page)
            label = report.citation_label(item.printed_page)
            cite = f"[{label}]({url})" if url else label
            quote = item.release_note_quote.strip().replace("\n", " ")
            excerpt = item.repo_excerpt.strip().replace("\n", " ").replace("`", "'")
            out += [f"**{ident}.** *{item.section}*, {cite}", "", f"> {quote}", "",
                    f"In your agent: `{item.repo_path}` — `{excerpt}`", ""]

    out += ["## How the release notes were read", ""]
    c = report.coverage
    if c:
        out += [f"- Pages read: **{c.pages_read} of {c.total_pdf_pages}** PDF pages, in {c.chunks} chunks "
                f"({c.priority_chunks} priority chunk(s) read first)."]
        out += [f"- Priority topics: {', '.join(c.priority_topics)}"]
        out += [f"- Candidate findings: {c.candidates_found} found while reading, "
                f"{c.candidates_unverified} dropped because the quote was not on the cited page."]
        if c.priority_sections:
            out += ["- Priority sections:"]
            out += [f"  - **{s_.section}** (printed pages {s_.printed_pages}): {s_.reason}" for s_ in c.priority_sections]
    for line in _coverage_warnings(report):
        out += [f"- ⚠️ {line}"]
    if report.sections_read:
        out += ["- Re-read while writing the report: " + ", ".join(f"{r.section} (pp. {r.printed_pages})" for r in report.sections_read)]
    out += ["", "## Agent and dependencies scanned (from your repository)", ""]
    out += [f"- `{path}`" for path in report.dependencies_scanned] or ["- none"]
    out += [""]
    if s.notes or report.removed_findings or report.score_breakdown:
        out += ["## Notes", ""]
        out += [f"- {n}" for n in s.notes]
        if report.score_breakdown:
            out += ["- Score: 100 " + "; ".join(report.score_breakdown)]
        if report.removed_findings:
            out += [f"- Removed (evidence could not be verified): {r}" for r in report.removed_findings]
        out += [""]
    out += [f"_Evidence: official Salesforce {release} release notes only. \"p.\" is the printed page number "
            f"and \"PDF p.\" the page in the downloaded PDF; links open the official release notes._", ""]
    return "\n".join(out)


def render_agent_list(agents: list[AgentRef], intro: str = "") -> tuple[str, list[dict]]:
    if not agents:
        text = "No Agentforce agents found in the configured source."
        return text, [_section(text)]
    lines = [f"• `{esc(a.name)}` — {KIND_LABEL.get(a.kind, a.kind)} · {esc(a.location)}" for a in agents]
    blocks = []
    if intro:
        blocks.append(_section(intro))
    chunk: list[str] = []
    for line in lines:
        if sum(len(x) + 1 for x in chunk) + len(line) > SECTION_TEXT_LIMIT:
            blocks.append(_section("\n".join(chunk)))
            chunk = []
        chunk.append(line)
    if chunk:
        blocks.append(_section("\n".join(chunk)))
    return f"{len(agents)} Agentforce agent(s) available", blocks[:50]


USAGE = (
    "*Usage*\n"
    "• `{cmd} list` — list agents\n"
    "• `{cmd} <AgentName> [current|next|both] [refresh]` — release-compliance report\n"
    "• Or mention me: _@Release Advisor is Order_Status_Returns_Agent ready for the next release?_"
)
