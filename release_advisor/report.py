"""The report Claude submits, plus the final (scored, evidence-checked) report shown in Slack."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Severity = Literal["Critical", "High", "Medium", "Low"]


class Evidence(BaseModel):
    """Where in the release notes an item comes from. Checked in code by evidence_guard."""

    section: str
    printed_page: int
    release_note_quote: str


class BreakingIssue(Evidence):
    title: str
    severity: Severity
    affected_element: str
    evidence: str
    fix: str


class UpcomingChange(Evidence):
    title: str
    severity: Severity
    effective: str
    impact: str
    action_needed: str


class Enhancement(Evidence):
    feature: str
    applies_to: str
    benefit: str


class AgentProfile(BaseModel):
    business_use_case: str
    capabilities: list[str]
    key_metadata: list[str]
    impact_value: str


class SubmittedReport(BaseModel):
    """Exactly what Claude passes to the submit_report tool."""

    agent_name: str
    current_release: str
    upcoming_release: str
    agent_profile: AgentProfile
    executive_summary: str
    breaking_issues: list[BreakingIssue]
    upcoming_changes: list[UpcomingChange]
    recommended_enhancements: list[Enhancement]
    notes: list[str]


class SectionRead(BaseModel):
    section: str
    reason: str
    printed_pages: str


class FinalReport(BaseModel):
    submitted: SubmittedReport
    agent_kind: str
    location: str
    revision: str
    project_api_version: str | None
    project_release: str | None
    static_findings: list[dict] = Field(default_factory=list)
    score: int
    status: Literal["Green", "Amber", "Red"]
    score_breakdown: list[str] = Field(default_factory=list)
    removed_findings: list[str] = Field(default_factory=list)
    sections_read: list[SectionRead] = Field(default_factory=list)
    cite_base_url: str = ""  # official release notes URL; "#page=<pdf page>" is appended per item
    pdf_pages: dict[int, int] = Field(default_factory=dict)  # printed page -> PDF page, for cited pages

    def citation_url(self, printed_page: int) -> str:
        pdf = self.pdf_pages.get(printed_page)
        return f"{self.cite_base_url}#page={pdf}" if self.cite_base_url and pdf else self.cite_base_url

    def citation_label(self, printed_page: int) -> str:
        pdf = self.pdf_pages.get(printed_page)
        return f"p. {printed_page} (PDF p. {pdf})" if pdf else f"p. {printed_page}"


def _obj(properties: dict, description: str | None = None) -> dict:
    schema = {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }
    if description:
        schema["description"] = description
    return schema


_SEVERITY = {"type": "string", "enum": ["Critical", "High", "Medium", "Low"]}
_EVIDENCE = {
    "section": {"type": "string", "description": "Release notes section the item comes from, e.g. \"Agentforce and Generative AI\"."},
    "printed_page": {
        "type": "integer",
        "description": "Printed page number (from the [Printed page N | ...] marker) where the quote appears.",
    },
    "release_note_quote": {
        "type": "string",
        "description": (
            "A short verbatim quote (one or two sentences, at most ~400 characters) copied exactly from that page "
            "of the release notes that supports this item. It is checked against the page text; items whose quote "
            "is not found are discarded."
        ),
    },
}

SUBMIT_REPORT_TOOL = {
    "name": "submit_report",
    "description": (
        "Submit the final release report for the agent. Call exactly once, after reading the release notes. "
        "Every breaking issue, upcoming change and enhancement must be backed by a verbatim quote from the "
        "release notes with its printed page number."
    ),
    "strict": True,
    "input_schema": _obj(
        {
            "agent_name": {"type": "string"},
            "current_release": {"type": "string", "description": "The release assessed, e.g. \"Winter '27\"."},
            "upcoming_release": {
                "type": "string",
                "description": "A later release the notes name for future-dated changes, or \"n/a\".",
            },
            "agent_profile": _obj(
                {
                    "business_use_case": {"type": "string", "description": "From the repository: what the agent is for."},
                    "capabilities": {"type": "array", "items": {"type": "string"}, "description": "Topics/subagents/actions."},
                    "key_metadata": {"type": "array", "items": {"type": "string"}, "description": "Apex, objects, permission sets, channels used."},
                    "impact_value": {"type": "string", "description": "From the repository: the business value the agent delivers."},
                },
                "Built only from the repository (agent definition, README, specs, metadata).",
            ),
            "executive_summary": {
                "type": "string",
                "description": "At most 3 plain-language sentences for product and senior managers.",
            },
            "breaking_issues": {
                "type": "array",
                "description": "Changes in this release that break, retire or require changes to something THIS agent uses.",
                "items": _obj(
                    {
                        "title": {"type": "string"},
                        "severity": _SEVERITY,
                        "affected_element": {"type": "string", "description": "Subagent/topic/action/class/config affected."},
                        "evidence": {"type": "string", "description": "What in the agent or repo is affected."},
                        "fix": {"type": "string", "description": "The change the release notes call for."},
                        **_EVIDENCE,
                    }
                ),
            },
            "upcoming_changes": {
                "type": "array",
                "description": "Future-dated changes announced in these notes (enforcement dates, retirements, reroutes) that affect THIS agent.",
                "items": _obj(
                    {
                        "title": {"type": "string"},
                        "severity": _SEVERITY,
                        "effective": {"type": "string", "description": "Date or release, as stated in the notes."},
                        "impact": {"type": "string"},
                        "action_needed": {"type": "string"},
                        **_EVIDENCE,
                    }
                ),
            },
            "recommended_enhancements": {
                "type": "array",
                "description": (
                    "New capabilities in these notes that this agent could adopt: better customer experience and "
                    "business impact, better performance tracking for product managers, and improvements to the "
                    "existing implementation."
                ),
                "items": _obj(
                    {
                        "feature": {"type": "string"},
                        "applies_to": {"type": "string", "description": "The specific agent element or metadata it applies to."},
                        "benefit": {"type": "string", "description": "The benefit as the release note describes it."},
                        **_EVIDENCE,
                    }
                ),
            },
            "notes": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Caveats, e.g. a category with nothing found in the release notes.",
            },
        }
    ),
}
