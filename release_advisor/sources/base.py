"""Source-agnostic model of an Agentforce agent definition.

Every agent source (GitHub repo today, Salesforce org later) produces the same
AgentRef / AgentBundle objects, so the advisor never cares where the agent came from.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

MAX_FILE_CHARS = 150_000
MAX_CONTEXT_FILE_CHARS = 30_000  # per README/spec/component file in project_context


@dataclass(frozen=True)
class AgentRef:
    """Lightweight pointer to an agent, used for listing and name resolution."""

    name: str
    kind: str  # "agent_script" | "legacy_planner"
    location: str  # human-readable origin, e.g. "github.com/acme/agents@main"
    path: str  # path of the primary definition file within the source
    project_root: str = ""  # directory that holds sfdx-project.json ("" = repo root)


@dataclass
class AgentBundle:
    """Everything needed to review one agent."""

    ref: AgentRef
    revision: str  # commit SHA, org release, ... - used for cache keys
    files: dict[str, str]  # path -> content of the agent's own definition files
    api_version: str | None  # sourceApiVersion of the enclosing project
    related_components: list[str] = field(default_factory=list)  # names Claude can fetch via read_component
    # Business context from the project: README, specs, test specs, and the source of the
    # components the agent's actions call. path -> content
    project_context: dict[str, str] = field(default_factory=dict)
    # Metadata inventory of the project: type -> names, e.g. {"ApexClass": [...], "PermissionSet": [...]}
    inventory: dict[str, list[str]] = field(default_factory=dict)


def clip(text: str, limit: int = MAX_FILE_CHARS) -> str:
    """Cap very large files, stating explicitly that the content was cut."""
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n\n[TRUNCATED: file is {len(text)} characters; first {limit} shown]"


class AgentSource(ABC):
    @abstractmethod
    def list_agents(self) -> list[AgentRef]:
        """All Agentforce agents this source can see."""

    @abstractmethod
    def load_agent(self, ref: AgentRef) -> AgentBundle:
        """Load the agent's definition files and metadata."""

    @abstractmethod
    def read_component(self, ref: AgentRef, name: str) -> str:
        """Return source of a related component (Apex class, Flow, GenAiFunction, ...) by name."""
