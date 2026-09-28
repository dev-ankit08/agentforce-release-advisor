"""Read Agentforce agents from one or more GitHub repositories containing SFDX projects.

Supported layouts (anywhere in the repo, any number of SFDX projects):
  .../aiAuthoringBundles/<Name>/<Name>.agent            -> Agent Script agent
  .../genAiPlannerBundles/<Name>/<Name>.genAiPlannerBundle -> legacy Agent Builder agent
  .../genAiPlanners/<Name>.genAiPlanner-meta.xml         -> legacy Agent Builder agent

The repository is downloaded once per commit as an archive, so the agent's full dependency graph
(dependencies.py) can be scanned without one API call per file.
"""

from __future__ import annotations

import io
import json
import posixpath
import re
import tarfile
import time
from dataclasses import dataclass
from urllib.parse import quote, urlparse

import requests

from .. import dependencies
from .base import MAX_CONTEXT_FILE_CHARS, AgentBundle, AgentRef, AgentSource, clip

_AGENT_SCRIPT_RE = re.compile(r"(?:^|/)aiAuthoringBundles/([^/]+)/[^/]+\.agent$")
_PLANNER_BUNDLE_RE = re.compile(r"(?:^|/)genAiPlannerBundles/([^/]+)/[^/]+\.genAiPlannerBundle(?:-meta\.xml)?$")
_PLANNER_RE = re.compile(r"(?:^|/)genAiPlanners/([^/]+)\.genAiPlanner-meta\.xml$")

_SNAPSHOT_TTL_SECONDS = 300
MAX_ARCHIVE_BYTES = 300 * 1024 * 1024
MAX_ARCHIVE_FILE_BYTES = 2 * 1024 * 1024  # larger text files are almost always generated data
_SKIP_DIRS = ("/node_modules/", "/.sfdx/", "/.sf/", "/.git/")


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
        self._archive: tuple[str, dict[str, str]] | None = None  # (sha, path -> text)

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

    def archive(self) -> dict[str, str]:
        """Every text file of the repository at the snapshot commit, downloaded once as a tarball."""
        sha = self.snapshot().sha
        if self._archive and self._archive[0] == sha:
            return self._archive[1]
        resp = self._session.get(f"{self._api}/repos/{self.slug}/tarball/{sha}", timeout=300, stream=True)
        if not resp.ok:
            raise GitHubError(f"Could not download {self.slug}@{sha[:7]} as an archive: HTTP {resp.status_code}")
        buf = io.BytesIO()
        for chunk in resp.iter_content(1 << 20):
            buf.write(chunk)
            if buf.tell() > MAX_ARCHIVE_BYTES:
                raise GitHubError(f"{self.slug} archive is larger than {MAX_ARCHIVE_BYTES // (1 << 20)} MB.")
        buf.seek(0)
        files: dict[str, str] = {}
        with tarfile.open(fileobj=buf, mode="r:gz") as tar:
            for member in tar:
                if not member.isfile() or member.size > MAX_ARCHIVE_FILE_BYTES:
                    continue
                # Entries are "<owner>-<repo>-<sha>/<path>"; drop the top-level folder.
                path = member.name.split("/", 1)[1] if "/" in member.name else member.name
                if any(d in "/" + path for d in _SKIP_DIRS) or not dependencies.is_text_path(path):
                    continue
                handle = tar.extractfile(member)
                if handle is not None:
                    files[path] = handle.read().decode("utf-8", errors="replace")
        self._archive = (sha, files)
        return files

    def read(self, path: str) -> str:
        files = self.archive()
        if path in files:
            return files[path]
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
        dependency_max_chars: int = 1_500_000,
    ):
        if not repo_urls:
            raise GitHubError("No repositories configured. Set GITHUB_REPOS to one or more GitHub repo URLs.")
        self._session = session or requests.Session()
        self._session.headers.update({"X-GitHub-Api-Version": "2022-11-28", "User-Agent": "agentforce-release-advisor"})
        if token:
            self._session.headers["Authorization"] = f"Bearer {token}"
        self.dependency_max_chars = dependency_max_chars
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

        project_paths = [p for p in snap.paths if not ref.project_root or p.startswith(ref.project_root + "/")]
        archive = repo.archive()
        project = {p: archive[p] for p in project_paths if p in archive}
        project.update(files)
        dep_scan = dependencies.scan(project, list(files), self.dependency_max_chars)

        context = {
            path: clip(project.get(path) or repo.read(path), MAX_CONTEXT_FILE_CHARS)
            for path in _context_doc_paths(project_paths, ref.project_root)
        }
        return AgentBundle(
            ref=ref,
            revision=snap.sha,
            files=files,
            api_version=api_version,
            related_components=sorted({k.split(":", 1)[1] for k in dep_scan.components} - {ref.name}),
            project_context=context,
            inventory=dependencies.build_inventory(project_paths),
            dependencies={p: clip(c) for p, c in dep_scan.dependency_files().items()},
            dependency_outline=dep_scan.outline(),
            dependency_notes=dep_scan.notes,
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
        raise GitHubError(f"No component named '{name}' found in {ref.location}.")

    # ---- helpers -----------------------------------------------------------------------------

    def _repo_for(self, ref: AgentRef) -> _Repo:
        slug = ref.location.removeprefix("github.com/").split("@", 1)[0]
        try:
            return self._repos[slug]
        except KeyError as exc:
            raise GitHubError(f"Unknown repository for agent {ref.name}: {ref.location}") from exc


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
    obj, _, leaf = name.partition(".")
    return [
        f"/classes/{name}.cls",
        f"/triggers/{name}.trigger",
        f"/flows/{name}.flow-meta.xml",
        f"/genAiFunctions/{name}/{name}.genAiFunction-meta.xml",
        f"/genAiFunctions/{name}.genAiFunction-meta.xml",
        f"/genAiPlugins/{name}.genAiPlugin-meta.xml",
        f"/genAiPromptTemplates/{name}.genAiPromptTemplate-meta.xml",
        f"/objects/{name}/{name}.object-meta.xml",
        f"/objects/{obj}/fields/{leaf}.field-meta.xml",
        f"/permissionsets/{name}.permissionset-meta.xml",
        f"/namedCredentials/{name}.namedCredential-meta.xml",
        f"/externalCredentials/{name}.externalCredential-meta.xml",
        f"/customMetadata/{name}.md-meta.xml",
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
