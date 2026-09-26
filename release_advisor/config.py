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
    # Sections read in full are chosen from the techniques the agent uses (relevance.py); add more here,
    # as table-of-contents titles, e.g. "Analytics,Sales".
    extra_full_read_sections: list[str] = field(default_factory=lambda: _list("EXTRA_FULL_READ_SECTIONS"))
    # Stop (never truncate) if the sections to read in full exceed this many tokens.
    max_full_read_tokens: int = field(default_factory=lambda: int(os.getenv("MAX_FULL_READ_TOKENS", "400000")))

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
