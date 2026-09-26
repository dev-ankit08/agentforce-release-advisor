"""Deterministic, release-independent checks on an Agent Script (.agent) file.

These run without an org and without the LLM. They catch structural problems that
would make the agent fail to compile/publish regardless of release notes.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from .sources.base import AgentBundle


@dataclass(frozen=True)
class StaticFinding:
    rule: str
    severity: str  # Critical | High | Medium | Low
    title: str
    detail: str
    element: str

    def to_dict(self) -> dict:
        return asdict(self)


_ACTION_REF_RE = re.compile(r"@actions\.(\w+)")
_TRANSITION_REF_RE = re.compile(r"@(subagent|topic)\.(\w+)")
_BLOCK_DECL_RE = re.compile(r"^(start_agent|subagent|topic)\s+(\w+)\s*:", re.MULTILINE)
_KEY_LINE_RE = re.compile(r"^(\s*)(\w+):\s*(.*)$")


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" \t"))


def defined_actions(source: str) -> set[str]:
    """Action names declared with a `target:` somewhere inside their block."""
    lines = source.splitlines()
    names: set[str] = set()
    for i, line in enumerate(lines):
        match = _KEY_LINE_RE.match(line)
        if not match or match.group(3).strip():
            continue  # only `name:` lines that open a block
        base = len(match.group(1))
        for nxt in lines[i + 1 :]:
            if not nxt.strip():
                continue
            if _indent(nxt) <= base:
                break
            if nxt.strip().startswith("target:"):
                names.add(match.group(2))
                break
    return names


def run_static_checks(bundle: AgentBundle) -> list[StaticFinding]:
    if bundle.ref.kind != "agent_script":
        return []
    agent_files = {p: c for p, c in bundle.files.items() if p.endswith(".agent")}
    if not agent_files:
        return [
            StaticFinding(
                "missing-agent-file", "Critical", "Agent Script file not found",
                "The authoring bundle folder has no .agent file.", bundle.ref.path,
            )
        ]

    findings: list[StaticFinding] = []
    for path, source in agent_files.items():
        refs = set(_ACTION_REF_RE.findall(source))
        missing = sorted(refs - defined_actions(source))
        for name in missing:
            findings.append(
                StaticFinding(
                    "undefined-action", "High", f"Action '{name}' is referenced but never defined",
                    f"`@actions.{name}` is used, but no action block named '{name}' declares a `target:` "
                    "(e.g. apex://ClassName or flow://FlowName). Unless the action exists as org metadata, "
                    "the bundle will not compile or publish.",
                    f"{path} → @actions.{name}",
                )
            )

        declared = {name for _, name in _BLOCK_DECL_RE.findall(source)}
        for kind, name in sorted(set(_TRANSITION_REF_RE.findall(source))):
            if name not in declared:
                findings.append(
                    StaticFinding(
                        "undefined-transition", "High", f"Transition to undefined {kind} '{name}'",
                        f"`@{kind}.{name}` is referenced but no `{kind} {name}:` block exists.",
                        f"{path} → @{kind}.{name}",
                    )
                )

        if not re.search(r"^system\s*:", source, re.MULTILINE):
            findings.append(
                StaticFinding("missing-system", "Medium", "No `system:` block",
                              "The agent has no system instructions block.", path)
            )
        if not re.search(r"^\s*developer_name\s*:", source, re.MULTILINE):
            findings.append(
                StaticFinding("missing-developer-name", "Medium", "No `config.developer_name`",
                              "The config block does not set developer_name.", path)
            )
        if not re.search(r"^start_agent\s+\w+\s*:", source, re.MULTILINE):
            findings.append(
                StaticFinding("missing-start-agent", "High", "No `start_agent` block",
                              "Agent Script requires exactly one start_agent entry point.", path)
            )
    return findings
