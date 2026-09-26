"""Decide which release-notes sections must be read in full for a given agent.

Deterministic rules look at the agent definition and its project (actions, metadata inventory,
README/specs, component source). Each selected section carries the reason it was chosen, which
is shown in the report. Sections are top-level sections of the release notes table of contents.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .sources.base import AgentBundle

AGENTFORCE_SECTIONS = ["Agentforce and Generative AI", "AIforce", "Release Updates"]


@dataclass(frozen=True)
class Selection:
    section: str  # top-level section title in the table of contents
    reason: str
    changes_log: bool = True  # also include "<section> Release Note Changes by Month"


def _all_text(bundle: AgentBundle) -> str:
    return "\n".join(list(bundle.files.values()) + list(bundle.project_context.values()))


def detect(bundle: AgentBundle, extra_sections: list[str] | None = None) -> list[Selection]:
    text = _all_text(bundle)
    low = text.lower()
    inv = bundle.inventory
    picks: list[Selection] = [
        Selection(s, "Always read: this is an Agentforce agent") for s in AGENTFORCE_SECTIONS
    ]

    apex_targets = sorted(set(re.findall(r"apex://([\w.]+)", text)))
    if apex_targets or inv.get("ApexClass"):
        detail = f"Apex actions: {', '.join(apex_targets)}" if apex_targets else f"{len(inv['ApexClass'])} Apex classes in the project"
        picks.append(Selection("Platform", f"Uses Apex ({detail}); Apex, sharing and developer changes are in Platform"))

    flow_targets = sorted(set(re.findall(r"flow://([\w.]+)", text)))
    if flow_targets or inv.get("Flow"):
        detail = ", ".join(flow_targets) if flow_targets else f"{len(inv['Flow'])} Flows in the project"
        picks.append(Selection("Automation", f"Uses Flows ({detail})"))

    security_hits = []
    for kind in ("PermissionSet", "ConnectedApp", "ExternalClientApp", "NamedCredential", "ExternalCredential", "ExternalService"):
        if inv.get(kind):
            security_hits.append(f"{kind}: {', '.join(inv[kind][:4])}")
    if re.search(r"\bHttpRequest\b|callout:", text):
        security_hits.append("HTTP callouts in Apex")
    if re.search(r"connected app|external client app|named credential|oauth", low):
        security_hits.append("connected app / credentials referenced in docs")
    if security_hits:
        picks.append(Selection("Security, Identity, and Privacy", "; ".join(security_hits)))

    service_hits = []
    if "@messagingsession" in low or "messagingsession" in low:
        service_hits.append("MessagingSession variables")
    if re.search(r"agent_?type:\s*[\"']?(customer|service)", low) or "agentforceserviceagent" in low:
        service_hits.append("customer/service agent type")
    if re.search(r"\b(whatsapp|sms|messaging channel|messaging for in-app|enhanced chat|escalat\w* to (a )?human)\b", low):
        service_hits.append("messaging channel / human escalation")
    if service_hits:
        picks.append(Selection("Service", "; ".join(service_hits)))

    if "slack" in low or "agentforceemployeeagent" in low:
        picks.append(Selection("Slack Integrations", "Slack is referenced or it is an employee agent (surfaced in Slack)"))

    if inv.get("DataCloudObject") or re.search(r"data library|retriever|data cloud|data 360", low):
        picks.append(Selection("Data 360", "Data library / retriever / Data Cloud referenced"))

    for extra in extra_sections or []:
        picks.append(Selection(extra, "Added by configuration (EXTRA_FULL_READ_SECTIONS)"))

    # de-duplicate, keeping the first reason
    seen: set[str] = set()
    unique = []
    for p in picks:
        key = p.section.lower()
        if key not in seen:
            seen.add(key)
            unique.append(p)
    return unique
