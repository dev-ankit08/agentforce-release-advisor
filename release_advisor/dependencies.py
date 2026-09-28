"""Full dependency scan of one Agentforce agent inside its SFDX project.

Source-agnostic: it works on the project's files (path -> text) and knows nothing about GitHub.

Forward closure (followed transitively): starting from the agent's own definition files, every
project component whose API name appears in a file already in the scan is added, and its own
references are followed in turn - actions -> Apex / Flows / GenAiFunctions / prompt templates ->
the classes, subflows, objects, fields, credentials, custom metadata and labels those use, and so on.

Reverse wiring (added, not expanded further): project files that reference something in the forward
closure and configure or exercise it - permission sets and groups, profiles, triggers, Apex tests,
record-triggered flows, bots, plugins, connected / external client apps.

Nothing is dropped silently: if the scan exceeds its size budget, the files left out are listed in
`notes`, and the report says so.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# (kind, regex on "/" + path). The groups joined with "." give the component's API name.
_COMPONENT_RULES: list[tuple[str, re.Pattern]] = [
    ("AiAuthoringBundle", re.compile(r"/aiAuthoringBundles/([^/]+)/")),
    ("GenAiPlannerBundle", re.compile(r"/genAiPlannerBundles/([^/]+)/")),
    ("GenAiPlanner", re.compile(r"/genAiPlanners/([^/]+)\.genAiPlanner-meta\.xml$")),
    ("ApexClass", re.compile(r"/classes/([^/]+)\.cls(?:-meta\.xml)?$")),
    ("ApexTrigger", re.compile(r"/triggers/([^/]+)\.trigger(?:-meta\.xml)?$")),
    ("Flow", re.compile(r"/flows/([^/]+)\.flow-meta\.xml$")),
    ("CustomField", re.compile(r"/objects/([^/]+)/fields/([^/]+)\.field-meta\.xml$")),
    ("ValidationRule", re.compile(r"/objects/([^/]+)/validationRules/([^/]+)\.validationRule-meta\.xml$")),
    ("CustomObject", re.compile(r"/objects/([^/]+)/[^/]+\.object-meta\.xml$")),
    ("PermissionSet", re.compile(r"/permissionsets/([^/]+)\.permissionset-meta\.xml$")),
    ("PermissionSetGroup", re.compile(r"/permissionsetgroups/([^/]+)\.permissionsetgroup-meta\.xml$")),
    ("Profile", re.compile(r"/profiles/([^/]+)\.profile-meta\.xml$")),
    ("ConnectedApp", re.compile(r"/connectedApps/([^/]+)\.connectedApp-meta\.xml$")),
    ("ExternalClientApp", re.compile(r"/externalClientApps/([^/]+)\.eca-meta\.xml$")),
    ("NamedCredential", re.compile(r"/namedCredentials/([^/]+)\.namedCredential-meta\.xml$")),
    ("ExternalCredential", re.compile(r"/externalCredentials/([^/]+)\.externalCredential-meta\.xml$")),
    ("ExternalService", re.compile(r"/externalServiceRegistrations/([^/]+)\.externalServiceRegistration-meta\.xml$")),
    ("RemoteSiteSetting", re.compile(r"/remoteSiteSettings/([^/]+)\.remoteSite-meta\.xml$")),
    ("PromptTemplate", re.compile(r"/genAiPromptTemplates/([^/]+)\.genAiPromptTemplate-meta\.xml$")),
    ("GenAiFunction", re.compile(r"/genAiFunctions/([^/]+)/")),
    ("GenAiPlugin", re.compile(r"/genAiPlugins/([^/]+)\.genAiPlugin-meta\.xml$")),
    ("Bot", re.compile(r"/bots/([^/]+)/")),
    ("LightningWebComponent", re.compile(r"/lwc/([^/]+)/")),
    ("AuraComponent", re.compile(r"/aura/([^/]+)/")),
    ("ApexPage", re.compile(r"/pages/([^/]+)\.page(?:-meta\.xml)?$")),
    ("CustomMetadata", re.compile(r"/customMetadata/([^/]+)\.md-meta\.xml$")),
    ("CustomLabels", re.compile(r"/labels/([^/]+)\.labels-meta\.xml$")),
    ("QuickAction", re.compile(r"/quickActions/([^/]+)\.quickAction-meta\.xml$")),
    ("PlatformEventChannel", re.compile(r"/platformEventChannels/([^/]+)\.platformEventChannel-meta\.xml$")),
    ("StaticResource", re.compile(r"/staticresources/([^/.]+)")),
    ("DataCloudObject", re.compile(r"/(?:dataStreamDefinitions|dataLakeObjectDefinitions|mktDataModelObjects)/([^/.]+)")),
]

# Kinds added when they reference something in the forward closure (configuration, security, tests).
_REVERSE_KINDS = {
    "PermissionSet", "PermissionSetGroup", "Profile", "ApexTrigger", "ApexClass", "Flow", "Bot",
    "GenAiPlugin", "GenAiFunction", "GenAiPlannerBundle", "ConnectedApp", "ExternalClientApp",
}

_TEXT_EXTENSIONS = (
    ".cls", ".trigger", ".xml", ".agent", ".json", ".yaml", ".yml", ".md", ".js", ".ts", ".html",
    ".css", ".page", ".component", ".txt", ".csv", ".soql",
)
_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?")
_TARGET_RE = re.compile(r"\b(?!https?://)\w+://([\w.]+)")  # apex://Cls, flow://Flow, prompt://Tpl (not URLs)
_MIN_NAME_CHARS = 4  # shorter component names produce too many false matches in prose


def is_text_path(path: str) -> bool:
    return path.lower().endswith(_TEXT_EXTENSIONS)


def classify(path: str) -> tuple[str, str] | None:
    """(kind, api_name) of the component a file belongs to, from its path alone."""
    p = "/" + path
    for kind, regex in _COMPONENT_RULES:
        m = regex.search(p)
        if m:
            return kind, ".".join(m.groups())
    return None


def build_inventory(paths: list[str]) -> dict[str, list[str]]:
    """Metadata inventory from file paths alone: type -> sorted names."""
    found: dict[str, set[str]] = {}
    for path in paths:
        hit = classify(path)
        if hit:
            found.setdefault(hit[0], set()).add(hit[1])
    return {kind: sorted(names) for kind, names in sorted(found.items())}


@dataclass
class Edge:
    source: str  # path of the file containing the reference
    target: str  # component "Kind:Name"
    via: str  # the token that matched, e.g. "OB_OrderService" or "apex://OB_GetOrderStatus"
    direction: str = "uses"  # "uses" (forward) | "wires" (reverse: configures/tests the target)


@dataclass
class DependencyScan:
    seeds: list[str]  # the agent's own files
    files: dict[str, str]  # every file in the scan, path -> content (agent files included)
    components: dict[str, list[str]]  # "Kind:Name" -> its paths
    edges: list[Edge] = field(default_factory=list)
    reverse: list[str] = field(default_factory=list)  # components added as reverse wiring
    unresolved: list[str] = field(default_factory=list)  # declared targets not found in the project
    notes: list[str] = field(default_factory=list)

    def dependency_files(self) -> dict[str, str]:
        seeds = set(self.seeds)
        return {p: c for p, c in self.files.items() if p not in seeds}

    def outline(self) -> str:
        """Readable map of the scan for prompts and the CLI."""
        lines = [f"{len(self.components)} components, {len(self.files)} files."]
        by_kind: dict[str, list[str]] = {}
        for key in self.components:
            kind, name = key.split(":", 1)
            by_kind.setdefault(kind, []).append(name + (" (wiring)" if key in self.reverse else ""))
        for kind in sorted(by_kind):
            lines.append(f"- {kind}: {', '.join(sorted(by_kind[kind]))}")
        if self.edges:
            lines.append("References:")
            seen = set()
            for e in self.edges:
                row = f"  {e.source} --{e.direction}--> {e.target}"
                if row not in seen:
                    seen.add(row)
                    lines.append(row)
        if self.unresolved:
            lines.append("Declared targets not in the project (standard or org-only): " + ", ".join(self.unresolved))
        lines += [f"Note: {n}" for n in self.notes]
        return "\n".join(lines)


class _Index:
    def __init__(self, project: dict[str, str]):
        self.paths_by_component: dict[str, list[str]] = {}
        self.names: dict[str, set[str]] = {}  # lowercase token -> component keys
        for path in sorted(project):
            hit = classify(path)
            if not hit:
                continue
            kind, name = hit
            key = f"{kind}:{name}"
            self.paths_by_component.setdefault(key, []).append(path)
            for token in self._tokens_for(kind, name):
                if len(token) >= _MIN_NAME_CHARS:
                    self.names.setdefault(token.lower(), set()).add(key)

    @staticmethod
    def _tokens_for(kind: str, name: str) -> list[str]:
        if kind in ("CustomField", "ValidationRule"):
            obj, _, leaf = name.partition(".")
            return [name, leaf] if kind == "CustomField" else [name]
        if kind == "CustomMetadata":  # Type.Record -> the type (Type__mdt) and the record
            typ, _, record = name.partition(".")
            return [name, f"{typ}__mdt", record]
        return [name]

    def matches(self, text: str) -> dict[str, str]:
        """Component keys referenced in text -> the token that matched."""
        found: dict[str, str] = {}
        for token in set(_TOKEN_RE.findall(text)):
            for candidate in (token, *token.split(".")):
                for key in self.names.get(candidate.lower(), ()):
                    found.setdefault(key, candidate)
        return found


def scan(
    project: dict[str, str],
    seed_paths: list[str],
    max_chars: int,
    fallback_seed_kinds: tuple[str, ...] = ("ApexClass",),
) -> DependencyScan:
    """Crawl the agent's dependencies. project = every text file of the SFDX project (path -> content)."""
    index = _Index(project)
    files: dict[str, str] = {}
    components: dict[str, list[str]] = {}
    edges: list[Edge] = []
    skipped: list[str] = []
    budget = {"used": 0}

    def add_file(path: str) -> bool:
        if path in files:
            return True
        content = project.get(path, "")
        if budget["used"] + len(content) > max_chars:
            skipped.append(path)
            return False
        files[path] = content
        budget["used"] += len(content)
        return True

    def add_component(key: str) -> list[str]:
        """Add every file of a component; returns the newly added paths."""
        paths = index.paths_by_component.get(key, [])
        components.setdefault(key, paths)
        return [p for p in paths if p not in files and add_file(p)]

    seeds = [p for p in seed_paths if p in project]
    for p in seeds:
        add_file(p)
        hit = classify(p)
        if hit:
            components.setdefault(f"{hit[0]}:{hit[1]}", index.paths_by_component.get(f"{hit[0]}:{hit[1]}", [p]))

    # Declared action targets that are not in the project (standard actions, org-only metadata).
    unresolved: set[str] = set()
    for p in seeds:
        for target in _TARGET_RE.findall(project[p]):
            if not index.names.get(target.lower()):
                unresolved.add(target)

    def crawl(queue: list[str]) -> None:
        """Forward closure, breadth first: follow every reference until nothing new is found."""
        while queue:
            path = queue.pop(0)
            own = classify(path)
            own_key = f"{own[0]}:{own[1]}" if own else None
            for key, token in sorted(index.matches(files[path]).items()):
                if key == own_key:
                    continue
                edges.append(Edge(path, key, token))
                if key not in components:
                    queue.extend(add_component(key))

    crawl(list(files))

    # An agent whose actions declare no targets (bare @actions.x registered in the org): the project's
    # invocable Apex is what those actions run, so it is scanned as part of the agent.
    if not any(_TARGET_RE.search(project[p]) for p in seeds):
        added: list[str] = []
        for key, paths in index.paths_by_component.items():
            if key.split(":", 1)[0] in fallback_seed_kinds and key not in components:
                if any("@InvocableMethod" in project.get(p, "") for p in paths):
                    edges.append(Edge(seeds[0] if seeds else "(agent)", key, "@InvocableMethod"))
                    added.extend(add_component(key))
        crawl(added)

    # Reverse wiring: permission sets, triggers, tests ... that reference the forward closure.
    forward = set(components)
    reverse: list[str] = []
    for key, paths in sorted(index.paths_by_component.items()):
        if key in components or key.split(":", 1)[0] not in _REVERSE_KINDS:
            continue
        text = "\n".join(project.get(p, "") for p in paths)
        if key.startswith("ApexClass:") and "@istest" not in text.lower():
            continue  # a non-test class that uses the closure is a caller, not part of the agent
        hits = sorted(k for k in index.matches(text) if k in forward)
        if not hits:
            continue
        for target in hits:
            edges.append(Edge(paths[0], target, target.split(":", 1)[1], "wires"))
        add_component(key)
        reverse.append(key)

    notes = []
    if skipped:
        notes.append(
            f"Dependency scan reached its size budget ({max_chars:,} characters); {len(skipped)} file(s) were not "
            f"included: {', '.join(skipped[:30])}{' ...' if len(skipped) > 30 else ''}. Raise DEPENDENCY_MAX_CHARS "
            "to include them."
        )
    return DependencyScan(
        seeds=seeds,
        files=files,
        components=components,
        edges=edges,
        reverse=reverse,
        unresolved=sorted(unresolved),
        notes=notes,
    )

