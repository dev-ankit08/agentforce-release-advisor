from __future__ import annotations

import re

from ..config import Settings
from .base import AgentBundle, AgentRef, AgentSource


def build_source(settings: Settings) -> AgentSource:
    if settings.agent_source == "github":
        from .github_source import GitHubAgentSource

        return GitHubAgentSource(
            settings.github_repos,
            token=settings.github_token,
            branch=settings.github_branch,
            api_url=settings.github_api_url,
        )
    if settings.agent_source == "salesforce_org":
        from .salesforce_org_source import SalesforceOrgAgentSource

        return SalesforceOrgAgentSource()
    raise ValueError(f"Unknown AGENT_SOURCE '{settings.agent_source}' (expected 'github' or 'salesforce_org').")


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def resolve_agent(refs: list[AgentRef], text: str) -> tuple[AgentRef | None, list[AgentRef]]:
    """Find the agent a user means in free text.

    Returns (match, candidates): match is set when exactly one agent fits; otherwise
    candidates holds the ambiguous options (empty when nothing matched).
    """
    needle = _norm(text)
    if not needle:
        return None, []
    exact = [r for r in refs if _norm(r.name) == needle]
    if len(exact) == 1:
        return exact[0], exact
    # Agent name mentioned inside a longer question, e.g. "is Order_Status_Returns_Agent ready?"
    mentioned = [r for r in refs if _norm(r.name) and _norm(r.name) in needle]
    if mentioned:
        longest = max(len(_norm(r.name)) for r in mentioned)
        mentioned = [r for r in mentioned if len(_norm(r.name)) == longest]
        return (mentioned[0], mentioned) if len(mentioned) == 1 else (None, mentioned)
    partial = [r for r in refs if needle in _norm(r.name)]
    if len(partial) == 1:
        return partial[0], partial
    return None, partial


__all__ = ["AgentBundle", "AgentRef", "AgentSource", "build_source", "resolve_agent"]
