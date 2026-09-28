"""Runtime configuration, loaded from environment variables (and an optional .env file)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()

# Trust the operating system's certificate store (needed behind corporate TLS-inspecting proxies).
if os.getenv("USE_SYSTEM_CERTS", "true").strip().lower() in {"1", "true", "yes", "on"}:
    try:
        import truststore

        truststore.inject_into_ssl()
    except ImportError:  # optional dependency
        pass

# Only official Salesforce properties. Web search/fetch are restricted to these hosts
# (subdomains included) and every cited source URL is re-checked against them.
DEFAULT_ALLOWED_DOMAINS = [
    "help.salesforce.com",
    "developer.salesforce.com",
    "releasenotes.docs.salesforce.com",
    "resources.docs.salesforce.com",  # official release-notes PDF downloads
    "trust.salesforce.com",
    "status.salesforce.com",
]


# Release-notes topics given preference. Short all-caps terms (AI, LLM) match as whole words, case-sensitive.
DEFAULT_PRIORITY_TOPICS = [
    "Agentforce", "Agent Script", "AIforce", "Claude", "Einstein", "Generative AI", "AI", "LLM",
    "large language model", "Prompt Builder", "prompt template", "Model Context Protocol", "MCP",
    "Atlas Reasoning", "agent action", "Data 360", "Data Cloud", "retriever", "Trust Layer",
]


def _list(name: str, default: list[str] | None = None) -> list[str]:
    raw = os.getenv(name, "")
    items = [x.strip() for x in raw.split(",") if x.strip()]
    return items or list(default or [])


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    # Claude
    anthropic_model: str = field(default_factory=lambda: os.getenv("ANTHROPIC_MODEL", "claude-opus-5"))
    anthropic_effort: str = field(default_factory=lambda: os.getenv("ANTHROPIC_EFFORT", "high"))
    enable_fallbacks: bool = field(default_factory=lambda: _bool("ANTHROPIC_ENABLE_FALLBACKS", True))
    max_agent_turns: int = field(default_factory=lambda: int(os.getenv("MAX_AGENT_TURNS", "25")))
    # Hosts release-notes PDFs may be downloaded from (explicit RELEASE_NOTES_PDF_URLS / legacy URLs).
    allowed_domains: list[str] = field(
        default_factory=lambda: _list("ALLOWED_SOURCE_DOMAINS", DEFAULT_ALLOWED_DOMAINS)
    )

    # Official release-notes PDFs (primary evidence). See release_notes.py for lookup order.
    release_notes_dir: str = field(default_factory=lambda: os.getenv("RELEASE_NOTES_DIR", "release_notes"))
    release_notes_pdf_urls: str = field(default_factory=lambda: os.getenv("RELEASE_NOTES_PDF_URLS", ""))
    release_notes_cache_dir: str = field(
        default_factory=lambda: os.getenv("RELEASE_NOTES_CACHE_DIR", ".cache/release_notes")
    )
    # The one release every agent is assessed against; lookups for other releases are refused.
    # "latest" (default) = the current release according to help.salesforce.com; or pin e.g. "Winter '27".
    target_release: str = field(default_factory=lambda: os.getenv("TARGET_RELEASE", "latest"))
    # The whole release-notes document is read, every page (relevance.py builds the reading plan).
    # Topics given preference: read first, at ANTHROPIC_EFFORT, and weighted higher in the final report.
    priority_topics: list[str] = field(default_factory=lambda: _list("PRIORITY_TOPICS", DEFAULT_PRIORITY_TOPICS))
    # Size of each release-notes chunk sent to Claude (estimated tokens), and how many run in parallel.
    scan_chunk_tokens: int = field(default_factory=lambda: int(os.getenv("SCAN_CHUNK_TOKENS", "60000")))
    scan_concurrency: int = field(default_factory=lambda: int(os.getenv("SCAN_CONCURRENCY", "4")))
    # A section/chunk outside the topic-named sections is a priority one at this many topic mentions per page.
    priority_density: float = field(default_factory=lambda: float(os.getenv("PRIORITY_DENSITY", "5")))
    # Model and effort for chunks outside the priority topics (every page is still read). Same as the main
    # model and effort by default; lower them to save cost.
    scan_model: str = field(default_factory=lambda: os.getenv("SCAN_MODEL") or os.getenv("ANTHROPIC_MODEL", "claude-opus-5"))
    scan_effort: str = field(default_factory=lambda: os.getenv("SCAN_EFFORT") or os.getenv("ANTHROPIC_EFFORT", "high"))

    # Dependency scan of the agent (dependencies.py): stop adding files beyond this many characters
    # (files left out are listed in the report, never dropped silently).
    dependency_max_chars: int = field(default_factory=lambda: int(os.getenv("DEPENDENCY_MAX_CHARS", "1500000")))

    # Where agent definitions come from: "github" (now) or "salesforce_org" (later).
    agent_source: str = field(default_factory=lambda: os.getenv("AGENT_SOURCE", "github"))

    # GitHub source
    github_repos: list[str] = field(default_factory=lambda: _list("GITHUB_REPOS"))
    github_branch: str | None = field(default_factory=lambda: os.getenv("GITHUB_BRANCH") or None)
    github_token: str | None = field(default_factory=lambda: os.getenv("GITHUB_TOKEN") or None)
    github_api_url: str = field(default_factory=lambda: os.getenv("GITHUB_API_URL", "https://api.github.com"))

    # Slack
    slack_bot_token: str | None = field(default_factory=lambda: os.getenv("SLACK_BOT_TOKEN") or None)
    slack_app_token: str | None = field(default_factory=lambda: os.getenv("SLACK_APP_TOKEN") or None)
    slack_command: str = field(default_factory=lambda: os.getenv("SLACK_COMMAND", "/agent-release"))
    max_concurrent_analyses: int = field(default_factory=lambda: int(os.getenv("MAX_CONCURRENT_ANALYSES", "3")))

    # Report cache
    cache_path: str = field(default_factory=lambda: os.getenv("CACHE_PATH", ".cache/reports.sqlite3"))
    cache_ttl_hours: float = field(default_factory=lambda: float(os.getenv("CACHE_TTL_HOURS", "24")))


def get_settings() -> Settings:
    return Settings()
