"""The report Claude submits, plus the final (scored, evidence-checked) report shown in Slack."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Severity = Literal["Critical", "High", "Medium", "Low"]


Availability = Literal["Generally Available", "Beta", "Pilot", "Developer Preview", "Not stated"]
PREVIEW_AVAILABILITY = ("Beta", "Pilot", "Developer Preview")


class Evidence(BaseModel):
    """Where in the release notes an item comes from. Checked in code by evidence_guard."""

    section: str
    printed_page: int
    release_note_quote: str


class RepoEvidence(BaseModel):
    """Where in the agent's repository the item applies. Checked in code by evidence_guard.check_repo."""

    repo_path: str
    repo_excerpt: str


class BreakingIssue(Evidence, RepoEvidence):
    title: str  # phrased in the agent's terms: "<agent element>: <what happens to it>"
    severity: Severity
    affected_element: str
    current_state: str  # how the agent / its metadata does it today (from the repository)
    release_change: str  # what the release changes
    fix: str


class UpcomingChange(Evidence, RepoEvidence):
    title: str
    severity: Severity
    effective: str
    affected_element: str
    current_state: str
    release_change: str
    action_needed: str


class Enhancement(Evidence, RepoEvidence):
    feature: str  # phrased in the agent's terms: "<agent element>: <what it gains>"
    availability: Availability
    applies_to: str
    current_state: str
    benefit: str  # as the release note describes it
    how_to_adopt: str


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


# ---- phase 1: the agent dossier ---------------------------------------------------------------


class TechnicalElement(BaseModel):
    element: str  # e.g. "OB_OrderService.getStatus", "callout:Shopify_API", "subagent order_status"
    kind: str  # e.g. "Apex class", "Named Credential", "Agent Script subagent", "Flow", "Permission set"
    location: str  # path in the repository
    detail: str  # platform features / APIs / settings it uses that a release could change


class AgentDossier(BaseModel):
    """What Claude learned from scanning the agent and all its dependencies (repository only)."""

    agent_profile: AgentProfile
    technical_inventory: list[TechnicalElement]
    watch_topics: list[str]  # release-note subjects that would matter to this agent


# ---- phase 2: candidates found while reading each chunk of the release notes ------------------


class Candidate(Evidence):
    category: Literal["breaking", "upcoming", "enhancement"]
    title: str
    severity: Severity
    affected_element: str
    rationale: str
    effective: str
    availability: Availability = "Not stated"
    priority_topic: bool = False  # set in code: found in a priority-topic chunk (not part of the schema)


class ReadingCoverage(BaseModel):
    release: str
    total_pdf_pages: int
    pages_read: int
    pages_not_read: list[int] = Field(default_factory=list)  # PDF pages whose chunk failed
    chunks: int
    priority_chunks: int
    priority_topics: list[str] = Field(default_factory=list)
    priority_sections: list[SectionRead] = Field(default_factory=list)
    candidates_found: int = 0
    candidates_unverified: int = 0  # dropped at chunk level: quote not on the cited page
    failures: list[str] = Field(default_factory=list)

    @property
    def complete(self) -> bool:
        return not self.pages_not_read


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
    coverage: ReadingCoverage | None = None
    sections_read: list[SectionRead] = Field(default_factory=list)  # sections Claude re-read while writing the report
    dependencies_scanned: list[str] = Field(default_factory=list)  # repository paths in the dependency scan
    dependency_notes: list[str] = Field(default_factory=list)
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

_TITLE = {
    "type": "string",
    "description": (
        "Heading in the agent's terms: '<agent element>: <what happens to it>', e.g. "
        "'SystemKnowledge_Tooling credential: connected-app support ends'. Not the release-note title."
    ),
}
_AFFECTED = {"type": "string", "description": "The agent element or metadata item: subagent, action, Apex class, credential, permission set, channel ..."}
_CURRENT = {"type": "string", "description": "How the agent or its metadata does this today, from the repository (one or two sentences)."}
_CHANGE = {"type": "string", "description": "What this release changes, as the release notes describe it (one or two sentences)."}
_REPO_EVIDENCE = {
    "repo_path": {"type": "string", "description": "Repository path of the file that shows the agent uses the element."},
    "repo_excerpt": {
        "type": "string",
        "description": (
            "A short verbatim excerpt (one line or phrase, at least ~15 characters) copied exactly from that file. "
            "It is checked against the file; items whose excerpt is not found are discarded."
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
                "description": (
                    "Changes in this release that break, retire or require changes to an element THIS agent's "
                    "Agent Script or metadata actually uses (shown by repo_excerpt)."
                ),
                "items": _obj(
                    {
                        "title": _TITLE,
                        "severity": _SEVERITY,
                        "affected_element": _AFFECTED,
                        "current_state": _CURRENT,
                        "release_change": _CHANGE,
                        "fix": {"type": "string", "description": "What to change in the agent or its metadata, per the release notes."},
                        **_REPO_EVIDENCE,
                        **_EVIDENCE,
                    }
                ),
            },
            "upcoming_changes": {
                "type": "array",
                "description": (
                    "Future-dated changes announced in these notes (enforcement dates, retirements, reroutes) that "
                    "affect an element THIS agent's Agent Script or metadata actually uses."
                ),
                "items": _obj(
                    {
                        "title": _TITLE,
                        "severity": _SEVERITY,
                        "effective": {"type": "string", "description": "Date or release, as stated in the notes."},
                        "affected_element": _AFFECTED,
                        "current_state": _CURRENT,
                        "release_change": {"type": "string", "description": "What is coming, as the release notes describe it."},
                        "action_needed": {"type": "string", "description": "What to do in the agent or its metadata, and by when."},
                        **_REPO_EVIDENCE,
                        **_EVIDENCE,
                    }
                ),
            },
            "recommended_enhancements": {
                "type": "array",
                "description": (
                    "New capabilities in these notes that a specific element of this agent could adopt: better "
                    "customer experience and business impact, better tracking for product managers, or improvements "
                    "to the existing implementation."
                ),
                "items": _obj(
                    {
                        "feature": {
                            "type": "string",
                            "description": (
                                "Heading in the agent's terms: '<agent element>: <what it gains>', e.g. "
                                "'explain_apex_component: compiler-accurate Apex answers'. Not the release-note title."
                            ),
                        },
                        "availability": {
                            "type": "string",
                            "enum": ["Generally Available", "Beta", "Pilot", "Developer Preview", "Not stated"],
                            "description": "As the release notes label the feature (e.g. '(Beta)', '(Generally Available)').",
                        },
                        "applies_to": _AFFECTED,
                        "current_state": _CURRENT,
                        "benefit": {"type": "string", "description": "What the feature adds, as the release note describes it."},
                        "how_to_adopt": {"type": "string", "description": "The concrete change to make in this agent."},
                        **_REPO_EVIDENCE,
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


_STR = {"type": "string"}

AGENT_DOSSIER_SCHEMA = _obj(
    {
        "agent_profile": SUBMIT_REPORT_TOOL["input_schema"]["properties"]["agent_profile"],
        "technical_inventory": {
            "type": "array",
            "description": (
                "Every element of the agent and its dependencies that a Salesforce release could affect: Agent "
                "Script blocks and constructs, actions and their targets, Apex classes and the platform APIs they "
                "call, Flows and their element types, objects and fields, permission sets, credentials and "
                "callouts, channels, prompt templates, models, API versions."
            ),
            "items": _obj({"element": _STR, "kind": _STR, "location": _STR, "detail": _STR}),
        },
        "watch_topics": {
            "type": "array",
            "items": _STR,
            "description": "Release-note subjects that would matter to this agent, as short phrases.",
        },
    }
)

CHUNK_FINDINGS_SCHEMA = _obj(
    {
        "candidates": {
            "type": "array",
            "items": _obj(
                {
                    "category": {"type": "string", "enum": ["breaking", "upcoming", "enhancement"]},
                    "title": _STR,
                    "severity": _SEVERITY,
                    "affected_element": {"type": "string", "description": "Element of the agent or its dependencies it applies to."},
                    "rationale": {"type": "string", "description": "Why it applies to this agent specifically."},
                    "effective": {"type": "string", "description": "Date or release for upcoming changes as the notes state it, else \"\"."},
                    "availability": {
                        "type": "string",
                        "enum": ["Generally Available", "Beta", "Pilot", "Developer Preview", "Not stated"],
                        "description": "How the release notes label the feature, e.g. '(Beta)'; \"Not stated\" if unlabeled.",
                    },
                    **_EVIDENCE,
                }
            ),
        },
        "notes": {"type": "string", "description": "Anything relevant that could not be itemised, or \"\"."},
    }
)
