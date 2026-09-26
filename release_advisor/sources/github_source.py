"""Read Agentforce agents from one or more GitHub repositories containing SFDX projects.

Supported layouts (anywhere in the repo, any number of SFDX projects):
  .../aiAuthoringBundles/<Name>/<Name>.agent            -> Agent Script agent
  .../genAiPlannerBundles/<Name>/<Name>.genAiPlannerBundle -> legacy Agent Builder agent
  .../genAiPlanners/<Name>.genAiPlanner-meta.xml         -> legacy Agent Builder agent
"""

from __future__ import annotations

import json
import posixpath
import re
import time
from dataclasses import dataclass
from urllib.parse import quote, urlparse

import requests

from .base import MAX_CONTEXT_FILE_CHARS, AgentBundle, AgentRef, AgentSource, clip

_AGENT_SCRIPT_RE = re.compile(r"(?:^|/)aiAuthoringBundles/([^/]+)/[^/]+\.agent$")
_PLANNER_BUNDLE_RE = re.compile(r"(?:^|/)genAiPlannerBundles/([^/]+)/[^/]+\.genAiPlannerBundle(?:-meta\.xml)?$")
_PLANNER_RE = re.compile(r"(?:^|/)genAiPlanners/([^/]+)\.genAiPlanner-meta\.xml$")
_TARGET_RE = re.compile(r"""target:\s*["']?(\w+)://([\w.]+)""")
_XML_NAME_RE = re.compile(
    r"<(?:genAiPluginName|genAiFunctionName|functionName|pluginName|invocationTarget)>\s*([\w.]+)\s*</"
)

_SNAPSHOT_TTL_SECONDS = 300
MAX_INVOCABLE_SCAN = 25  # Apex classes scanned for @InvocableMethod when actions declare no targets


class GitHubError(RuntimeError):
    pass


@dataclass
class _Snapshot:
    sha: str
    branch: str
    paths: list[str]
    fetched_at: float


def parse_repo_url(url: str) -> tuple[str, str, str | None]:
    """Return (owner, repo, branch-or-None) from https://github.com/owner/repo[/tree/branch]."""
    url = url.strip()
    if not url.startswith("http"):
        url = "https://" + url
    parts = [p for p in urlparse(url).path.split("/") if p]
    if len(parts) < 2:
        raise GitHubError(f"Not a GitHub repository URL: {url}")
    owner, repo = parts[0], parts[1].removesuffix(".git")
    branch = "/".join(parts[3:]) if len(parts) > 3 and parts[2] == "tree" else None
    return owner, repo, branch


class _Repo:
    def __init__(self, url: str, session: requests.Session, api_url: str, branch_override: str | None):
        self.url = url
        self.owner, self.name, url_branch = parse_repo_url(url)
        self.branch_hint = branch_override or url_branch
        self._session = session
        self._api = api_url.rstrip("/")
        self._snapshot: _Snapshot | None = None

    @property
    def slug(self) -> str:
        return f"{self.owner}/{self.name}"

    def _get(self, path: str, raw: bool = False) -> requests.Response:
        headers = {"Accept": "application/vnd.github.raw"} if raw else {}
        resp = self._session.get(f"{self._api}/repos/{self.slug}{path}", headers=headers, timeout=30)
        if resp.status_code == 404:
            raise GitHubError(
                f"GitHub returned 404 for {self.slug}{path}. Check the repo URL/branch, "
                "and set GITHUB_TOKEN if the repository is private."
            )
        if resp.status_code == 403 and resp.headers.get("X-RateLimit-Remaining") == "0":
            raise GitHubError("GitHub API rate limit reached. Set GITHUB_TOKEN to raise the limit.")
        if not resp.ok:
            raise GitHubError(f"GitHub API error {resp.status_code} for {self.slug}{path}: {resp.text[:300]}")
        return resp

    def snapshot(self) -> _Snapshot:
        if self._snapshot and time.time() - self._snapshot.fetched_at < _SNAPSHOT_TTL_SECONDS:
            return self._snapshot
        branch = self.branch_hint or self._get("").json()["default_branch"]
        sha = self._get(f"/commits/{quote(branch, safe='')}").json()["sha"]
        tree = self._get(f"/git/trees/{sha}?recursive=1").json()
        if tree.get("truncated"):
            raise GitHubError(
                f"{self.slug} is too large for a single recursive tree listing; "
                "point GITHUB_REPOS at a smaller repo or a /tree/<branch> containing the SFDX project."
            )
        paths = [item["path"] for item in tree.get("tree", []) if item.get("type") == "blob"]
        self._snapshot = _Snapshot(sha=sha, branch=branch, paths=paths, fetched_at=time.time())
        return self._snapshot

    def read(self, path: str) -> str:
        sha = self.snapshot().sha
        return self._get(f"/contents/{quote(path)}?ref={sha}", raw=True).text


class GitHubAgentSource(AgentSource):
    def __init__(
        self,
        repo_urls: list[str],
        token: str | None = None,
        branch: str | None = None,
        api_url: str = "https://api.github.com",
        session: requests.Session | None = None,
    ):
        if not repo_urls:
            raise GitHubError("No repositories configured. Set GITHUB_REPOS to one or more GitHub repo URLs.")
        self._session = session or requests.Session()
        self._session.headers.update({"X-GitHub-Api-Version": "2022-11-28", "User-Agent": "agentforce-release-advisor"})
        if token:
            self._session.headers["Authorization"] = f"Bearer {token}"
        self._repos = {r.slug: r for r in (_Repo(u, self._session, api_url, branch) for u in repo_urls)}

    # ---- AgentSource -------------------------------------------------------------------------

    def list_agents(self) -> list[AgentRef]:
        refs: list[AgentRef] = []
        for repo in self._repos.values():
            snap = repo.snapshot()
            project_roots = sorted(
                (posixpath.dirname(p) for p in snap.paths if posixpath.basename(p) == "sfdx-project.json"),
                key=len,
                reverse=True,
            )
            for path in snap.paths:
                for regex, kind in (
                    (_AGENT_SCRIPT_RE, "agent_script"),
                    (_PLANNER_BUNDLE_RE, "legacy_planner"),
                    (_PLANNER_RE, "legacy_planner"),
                ):
                    match = regex.search(path)
                    if match:
                        refs.append(
                            AgentRef(
                                name=match.group(1),
                                kind=kind,
                                location=f"github.com/{repo.slug}@{snap.branch}",
                                path=path,
                                project_root=_nearest_root(path, project_roots),
                            )
                        )
                        break
        return _dedupe(refs)

    def load_agent(self, ref: AgentRef) -> AgentBundle:
        repo = self._repo_for(ref)
        snap = repo.snapshot()
        folder = posixpath.dirname(ref.path)
        if ref.kind == "agent_script" or "genAiPlannerBundles/" in ref.path:
            own_paths = [p for p in snap.paths if posixpath.dirname(p) == folder]
        else:
            own_paths = [ref.path]
        files = {p: clip(repo.read(p)) for p in sorted(own_paths)}

        api_version = None
        project_file = posixpath.join(ref.project_root, "sfdx-project.json") if ref.project_root else "sfdx-project.json"
        if project_file in snap.paths:
            try:
                api_version = json.loads(repo.read(project_file)).get("sourceApiVersion")
            except (ValueError, GitHubError):
                api_version = None

        related: set[str] = set()
        for content in files.values():
            related.update(name for _, name in _TARGET_RE.findall(content))
            related.update(_XML_NAME_RE.findall(content))

        project_paths = [p for p in snap.paths if not ref.project_root or p.startswith(ref.project_root + "/")]
        inventory = build_inventory(project_paths)
        context: dict[str, str] = {}
        for path in _context_doc_paths(project_paths, ref.project_root):
            try:
                context[path] = clip(repo.read(path), MAX_CONTEXT_FILE_CHARS)
            except GitHubError as exc:
                context[path] = f"[could not read: {exc}]"
        for name in sorted(related):
            try:
                source = self.read_component(ref, name)
                path = source.split("\n", 1)[0].removeprefix("// ").strip()
                context[path] = clip(source, MAX_CONTEXT_FILE_CHARS)
            except GitHubError:
                continue  # referenced component not in this repo (e.g. standard action)
        if not related:
            # Actions without declared targets (bare @actions.x): the project's invocable Apex classes
            # are the candidates the agent's actions are registered from.
            classes = [p for p in project_paths if p.endswith(".cls") and "/classes/" in p
                       and not re.search(r"test", posixpath.basename(p), re.I)]
            for path in classes[:MAX_INVOCABLE_SCAN]:
                try:
                    source = repo.read(path)
                except GitHubError:
                    continue
                if "@InvocableMethod" in source:
                    context[path] = clip(source, MAX_CONTEXT_FILE_CHARS)

        return AgentBundle(
            ref=ref,
            revision=snap.sha,
            files=files,
            api_version=api_version,
            related_components=sorted(related),
            project_context=context,
            inventory=inventory,
        )

    def read_component(self, ref: AgentRef, name: str) -> str:
        repo = self._repo_for(ref)
        root = ref.project_root
        candidates = _component_paths(name)
        for path in repo.snapshot().paths:
            if root and not path.startswith(root + "/"):
                continue
            if any(path.endswith(c) for c in candidates):
                return f"// {path}\n" + clip(repo.read(path))
        raise GitHubError(f"No Apex class, Flow, GenAiFunction or GenAiPlugin named '{name}' found in {ref.location}.")

    # ---- helpers -----------------------------------------------------------------------------

    def _repo_for(self, ref: AgentRef) -> _Repo:
        slug = ref.location.removeprefix("github.com/").split("@", 1)[0]
        try:
            return self._repos[slug]
        except KeyError as exc:
            raise GitHubError(f"Unknown repository for agent {ref.name}: {ref.location}") from exc


_INVENTORY_RULES: list[tuple[str, re.Pattern]] = [
    ("ApexClass", re.compile(r"/classes/([^/]+)\.cls$")),
    ("ApexTrigger", re.compile(r"/triggers/([^/]+)\.trigger$")),
    ("Flow", re.compile(r"/flows/([^/]+)\.flow-meta\.xml$")),
    ("CustomObject", re.compile(r"/objects/([^/]+)/[^/]+\.object-meta\.xml$")),
    ("CustomField", re.compile(r"/objects/([^/]+)/fields/([^/]+)\.field-meta\.xml$")),
    ("PermissionSet", re.compile(r"/permissionsets/([^/]+)\.permissionset-meta\.xml$")),
    ("ConnectedApp", re.compile(r"/connectedApps/([^/]+)\.connectedApp-meta\.xml$")),
    ("ExternalClientApp", re.compile(r"/externalClientApps/([^/]+)\.eca-meta\.xml$")),
    ("NamedCredential", re.compile(r"/namedCredentials/([^/]+)\.namedCredential-meta\.xml$")),
    ("ExternalCredential", re.compile(r"/externalCredentials/([^/]+)\.externalCredential-meta\.xml$")),
    ("ExternalService", re.compile(r"/externalServiceRegistrations/([^/]+)\.externalServiceRegistration-meta\.xml$")),
    ("PromptTemplate", re.compile(r"/genAiPromptTemplates/([^/]+)\.genAiPromptTemplate-meta\.xml$")),
    ("GenAiFunction", re.compile(r"/genAiFunctions/([^/]+)/")),
    ("GenAiPlugin", re.compile(r"/genAiPlugins/([^/]+)\.genAiPlugin-meta\.xml$")),
    ("Bot", re.compile(r"/bots/([^/]+)/")),
    ("LightningWebComponent", re.compile(r"/lwc/([^/]+)/")),
    ("StaticResource", re.compile(r"/staticresources/([^/.]+)")),
    ("DataCloudObject", re.compile(r"/(?:dataStreamDefinitions|dataLakeObjectDefinitions|mktDataModelObjects)/([^/.]+)")),
]


def build_inventory(paths: list[str]) -> dict[str, list[str]]:
    """Metadata inventory from file paths alone (no downloads)."""
    found: dict[str, set[str]] = {}
    for path in paths:
        p = "/" + path
        for kind, regex in _INVENTORY_RULES:
            m = regex.search(p)
            if m:
                name = ".".join(m.groups())
                found.setdefault(kind, set()).add(name)
    return {kind: sorted(names) for kind, names in sorted(found.items())}


def _context_doc_paths(paths: list[str], root: str) -> list[str]:
    """README, agent specs and test specs of the project (bounded)."""
    prefix = root + "/" if root else ""
    picked: list[str] = []
    for path in paths:
        rel = path[len(prefix):] if path.startswith(prefix) else path
        name = posixpath.basename(rel).lower()
        if "/" not in rel and name.startswith("readme"):
            picked.append(path)
        elif re.match(r"^(specs|tests|config)/", rel) and name.endswith((".yaml", ".yml")) and "spec" in name:
            picked.append(path)
    return sorted(picked)[:8]


def _component_paths(name: str) -> list[str]:
    return [
        f"/classes/{name}.cls",
        f"/flows/{name}.flow-meta.xml",
        f"/genAiFunctions/{name}/{name}.genAiFunction-meta.xml",
        f"/genAiFunctions/{name}.genAiFunction-meta.xml",
        f"/genAiPlugins/{name}.genAiPlugin-meta.xml",
        f"/genAiPromptTemplates/{name}.genAiPromptTemplate-meta.xml",
    ]


def _nearest_root(path: str, roots_longest_first: list[str]) -> str:
    for root in roots_longest_first:
        if root == "" or path.startswith(root + "/"):
            return root
    return ""


def _dedupe(refs: list[AgentRef]) -> list[AgentRef]:
    """A planner bundle folder may hold both the file and its -meta.xml; keep one per agent."""
    seen: dict[tuple[str, str, str], AgentRef] = {}
    for ref in refs:
        key = (ref.location, posixpath.dirname(ref.path) if ref.kind != "legacy_planner" else ref.name, ref.kind)
        seen.setdefault(key, ref)
    return sorted(seen.values(), key=lambda r: (r.name.lower(), r.location))
