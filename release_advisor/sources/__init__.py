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
            dependency_max_chars=settings.dependency_max_chars,
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
    if partial:
        return None, partial
    return _by_name_words(refs, text)


# Words that appear in many agent names and say nothing about which agent is meant.
_GENERIC_NAME_WORDS = {"agent", "agents", "agentforce", "bot", "the", "and", "for", "service", "employee"}


def _name_words(name: str) -> set[str]:
    """"System_Knowledge_Agent" / "OrderStatusAgent" -> {"system", "knowledge"} / {"order", "status"}."""
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", name)
    words = {w for w in re.split(r"[^A-Za-z0-9]+", spaced.lower()) if len(w) >= 3}
    return words - _GENERIC_NAME_WORDS


def _by_name_words(refs: list[AgentRef], text: str) -> tuple[AgentRef | None, list[AgentRef]]:
    """Natural phrasing: "release suggestions for the Knowledge agent" -> System_Knowledge_Agent.

    The agent whose distinctive name words appear most often in the text wins; a tie is ambiguous.
    """
    said = {w.rstrip("s") for w in re.findall(r"[a-z0-9]{3,}", text.lower())}
    scored = []
    for ref in refs:
        hits = sum(1 for w in _name_words(ref.name) if w.rstrip("s") in said)
        if hits:
            scored.append((hits, ref))
    if not scored:
        return None, []
    best = max(h for h, _ in scored)
    top = [r for h, r in scored if h == best]
    return (top[0], top) if len(top) == 1 else (None, top)


__all__ = ["AgentBundle", "AgentRef", "AgentSource", "build_source", "resolve_agent"]
