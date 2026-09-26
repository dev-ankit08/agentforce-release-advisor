"""Placeholder for reading agents straight from a Salesforce org.

Planned implementation (once a Connected App / External Client App is available):
  * Authenticate with the OAuth 2.0 JWT bearer flow as a read-only integration user.
  * list_agents: Tooling API query on AiAuthoringBundle (Agent Script) and GenAiPlannerBundle (legacy).
  * load_agent: Metadata API retrieve of the bundle; api_version = org's highest supported API
    version (GET /services/data), revision = org instance + bundle LastModifiedDate.
  * read_component: Tooling API query on ApexClass.Body / Flow metadata by name.

Selecting AGENT_SOURCE=salesforce_org before this exists fails fast with a clear message.
"""

from __future__ import annotations

from .base import AgentBundle, AgentRef, AgentSource


class SalesforceOrgAgentSource(AgentSource):
    def __init__(self, *_, **__):
        raise NotImplementedError(
            "AGENT_SOURCE=salesforce_org is not implemented yet. Use AGENT_SOURCE=github for now."
        )

    def list_agents(self) -> list[AgentRef]:  # pragma: no cover
        raise NotImplementedError

    def load_agent(self, ref: AgentRef) -> AgentBundle:  # pragma: no cover
        raise NotImplementedError

    def read_component(self, ref: AgentRef, name: str) -> str:  # pragma: no cover
        raise NotImplementedError
