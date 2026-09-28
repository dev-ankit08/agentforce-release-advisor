"""Glue between agent source, cache and advisor; shared by the Slack app and the CLI."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .advisor import ReleaseAdvisor
from .cache import ReportCache
from .config import Settings
from .report import FinalReport
from .sources import AgentRef, build_source, resolve_agent


@dataclass
class Resolution:
    agent: AgentRef | None
    candidates: list[AgentRef]
    all_agents: list[AgentRef]


class AdvisorService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.source = build_source(settings)
        self.advisor = ReleaseAdvisor(settings, self.source)
        self.cache = ReportCache(settings.cache_path, settings.cache_ttl_hours)

    def list_agents(self) -> list[AgentRef]:
        return self.source.list_agents()

    def resolve(self, text: str) -> Resolution:
        agents = self.list_agents()
        match, candidates = resolve_agent(agents, text)
        return Resolution(match, candidates, agents)

    def analyze(
        self,
        agent: AgentRef,
        question: str = "",
        focus: str = "both",
        fresh: bool = False,
        progress: Callable[[str], None] | None = None,
        rescan: bool = False,
    ) -> tuple[FinalReport, bool]:
        """Return (report, from_cache)."""
        target = self.advisor.notes.target_release()
        if target:
            # Fetch the release notes up front (fails fast, before any Claude spend).
            self.advisor.notes.get(target, progress=progress)
        bundle = self.source.load_agent(agent)
        # A new target release or newly added PDF must invalidate earlier reports.
        notes = ",".join(sorted(self.advisor.notes.configured_releases()))
        topics = ",".join(self.settings.priority_topics)
        key = ReportCache.key(agent.location, agent.name, bundle.revision, f"v4|{focus}|{target}|{notes}|{topics}")
        if not (fresh or rescan):
            cached = self.cache.get(key)
            if cached:
                return cached, True
        report = self.advisor.analyze(bundle, question=question, focus=focus, progress=progress, rescan=rescan)
        self.cache.put(key, report)
        return report, False
