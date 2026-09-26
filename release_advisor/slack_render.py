"""Render reports and agent lists as Slack Block Kit messages."""

from __future__ import annotations

from .report import FinalReport
from .sources import AgentRef

MAX_ITEMS_PER_SECTION = 5
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


def _quote(item, limit: int = 300) -> str:
    q = item.release_note_quote.strip().replace("\n", " ")
    return "> " + esc(q[:limit] + ("…" if len(q) > limit else ""))


def _section(text: str) -> dict:
    if len(text) > SECTION_TEXT_LIMIT:
        text = text[: SECTION_TEXT_LIMIT - 1] + "…"
    return {"type": "section", "text": {"type": "mrkdwn", "text": text}}


def _context(text: str) -> dict:
    return {"type": "context", "elements": [{"type": "mrkdwn", "text": text[:SECTION_TEXT_LIMIT]}]}


def _list_section(title: str, lines: list[str]) -> list[dict]:
    if not lines:
        return [_section(f"*{title} (0)*\n_None found._")]
    blocks = [_section(f"*{title} ({len(lines)})*")]
    blocks += [_section(line) for line in lines[:MAX_ITEMS_PER_SECTION]]
    if len(lines) > MAX_ITEMS_PER_SECTION:
        blocks.append(_context(f"+{len(lines) - MAX_ITEMS_PER_SECTION} more in the attached full report."))
    return blocks


def render_report(report: FinalReport, from_cache: bool = False) -> tuple[str, list[dict]]:
    s = report.submitted
    emoji = STATUS_EMOJI[report.status]
    headline = f"{s.agent_name} — {s.current_release} readiness {report.score}/100 {report.status}"

    breaking = [
        f"*[{f['severity']}] {esc(f['title'])}* _(static check of your repository)_\n{esc(f['detail'])}\n_Where:_ `{esc(f['element'])}`"
        for f in report.static_findings
    ] + [
        f"*[{i.severity}] {esc(i.title)}*\n_Where:_ {esc(i.affected_element)}\n"
        f"_Why:_ {esc(i.evidence)}\n_Fix:_ {esc(i.fix)}\n{_quote(i)}\n{_cite(report, i)}"
        for i in s.breaking_issues
    ]
    upcoming = [
        f"*[{c.severity}] {esc(c.title)}* — _{esc(c.effective)}_\n_Impact:_ {esc(c.impact)}\n"
        f"_Action:_ {esc(c.action_needed)}\n{_quote(c)}\n{_cite(report, c)}"
        for c in s.upcoming_changes
    ]
    enhancements = [
        f"*{esc(e.feature)}*\n_Applies to:_ {esc(e.applies_to)}\n_Benefit:_ {esc(e.benefit)}\n{_quote(e)}\n{_cite(report, e)}"
        for e in s.recommended_enhancements
    ]

    project = f"API v{report.project_api_version} ({report.project_release})" if report.project_api_version else "API version unknown"
    meta = (
        f"{KIND_LABEL.get(report.agent_kind, report.agent_kind)} · {esc(report.location)} @ `{report.revision[:7]}` · "
        f"Project {project} · Release assessed *{esc(s.current_release)}*"
    )
    p = s.agent_profile
    profile = (
        f"*Agent profile* _(from your repository)_\n*Use case:* {esc(p.business_use_case)}\n"
        f"*Capabilities:* {esc(', '.join(p.capabilities))}\n*Impact value:* {esc(p.impact_value)}"
    )

    blocks: list[dict] = [
        {"type": "header", "text": {"type": "plain_text", "text": f"{headline}"[:150], "emoji": True}},
        _context(meta),
        _section(f"{emoji} {esc(s.executive_summary)}"),
        _section(profile),
        {"type": "divider"},
        *_list_section(":red_circle: Breaking / must fix", breaking),
        {"type": "divider"},
        *_list_section(":large_yellow_circle: Upcoming changes needing action", upcoming),
        {"type": "divider"},
        *_list_section(":large_green_circle: Recommended enhancements", enhancements),
    ]

    footer: list[str] = [esc(n) for n in s.notes]
    if report.score_breakdown:
        footer.append("Score: 100 " + " ".join(esc(b.split(" ", 1)[0]) for b in report.score_breakdown))
    if report.removed_findings:
        footer.append(f"{len(report.removed_findings)} item(s) removed — quote not found on the cited release-notes page.")
    if report.sections_read:
        footer.append("Read in full: " + ", ".join(
            f"{esc(r.section)} (pp. {r.printed_pages})" for r in report.sections_read))
    footer.append(
        f"Evidence: official Salesforce {esc(s.current_release)} release notes only; page numbers are the printed "
        "page numbers." + (" _Cached result._" if from_cache else "")
    )
    blocks.append({"type": "divider"})
    blocks.append(_context("\n".join(f"• {line}" for line in footer)))

    return f"{emoji} {headline}", blocks[:50]


def render_markdown(report: FinalReport) -> str:
    """The complete report as Markdown (attached to the Slack thread, or written by the CLI)."""
    s = report.submitted
    p = s.agent_profile

    def cite(item) -> str:
        url = report.citation_url(item.printed_page)
        label = report.citation_label(item.printed_page)
        return f"*{item.section}*, [{label}]({url})" if url else f"*{item.section}*, {label}"

    def quote(item) -> str:
        return "> " + item.release_note_quote.strip().replace("\n", " ")

    out = [
        f"# {s.agent_name} — {s.current_release} release readiness: {report.score}/100 ({report.status})",
        "",
        f"- Definition: {KIND_LABEL.get(report.agent_kind, report.agent_kind)}, {report.location} @ `{report.revision[:7]}`",
        f"- Project API version: {report.project_api_version or 'unknown'} ({report.project_release or 'n/a'})",
        f"- Release assessed: {s.current_release}" + (f"; later release named in the notes: {s.upcoming_release}" if s.upcoming_release not in ("", "n/a") else ""),
        "",
        "## Executive summary",
        "",
        s.executive_summary,
        "",
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
    if not report.static_findings and not s.breaking_issues:
        out += ["_None found in the release notes._", ""]
    for f in report.static_findings:
        out += [f"### [{f['severity']}] {f['title']} (static check of your repository)", "", f["detail"], "",
                f"Where: `{f['element']}`", ""]
    for i in s.breaking_issues:
        out += [f"### [{i.severity}] {i.title}", "", f"- **Where:** {i.affected_element}", f"- **Why:** {i.evidence}",
                f"- **Fix:** {i.fix}", "", quote(i), "", f"Source: {cite(i)}", ""]
    out += ["## 🟡 Upcoming changes needing action", ""]
    if not s.upcoming_changes:
        out += ["_None found in the release notes._", ""]
    for c in s.upcoming_changes:
        out += [f"### [{c.severity}] {c.title} — {c.effective}", "", f"- **Impact:** {c.impact}",
                f"- **Action:** {c.action_needed}", "", quote(c), "", f"Source: {cite(c)}", ""]
    out += ["## 🟢 Recommended enhancements", ""]
    if not s.recommended_enhancements:
        out += ["_None found in the release notes._", ""]
    for e in s.recommended_enhancements:
        out += [f"### {e.feature}", "", f"- **Applies to:** {e.applies_to}", f"- **Benefit:** {e.benefit}", "",
                quote(e), "", f"Source: {cite(e)}", ""]
    out += ["## Release notes sections read in full", ""]
    out += [f"- **{r.section}** (printed pages {r.printed_pages}): {r.reason}" for r in report.sections_read] or ["- none"]
    out += [""]
    if s.notes or report.removed_findings or report.score_breakdown:
        out += ["## Notes", ""]
        out += [f"- {n}" for n in s.notes]
        if report.score_breakdown:
            out += ["- Score: 100 " + "; ".join(report.score_breakdown)]
        if report.removed_findings:
            out += [f"- Removed (quote not found on the cited page): {r}" for r in report.removed_findings]
        out += [""]
    out += [f"_Evidence: official Salesforce {s.current_release} release notes only. \"p.\" is the printed page number "
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
