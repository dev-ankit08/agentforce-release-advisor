# Agentforce Release Advisor

A Slack bot that acts as a virtual Salesforce architect for product and senior managers. It understands an Agentforce agent in depth: its definition, its metadata, and its business use case. It then compares the agent against the **latest Salesforce release notes** and reports:

- what breaks
- what upcoming changes need action
- which new capabilities are worth adopting, whether for customer experience and business impact, for product-manager tracking, or as improvements to the current implementation

**Guardrail:** every finding comes strictly from the **official Salesforce release notes**. Each one carries a verbatim quote and its page number, and the code checks that the quote is really on that page. The bot finds and downloads the latest release notes from help.salesforce.com by itself.

It works with any Agentforce agent defined in an SFDX project:

- **Agent Script** agents (`aiAuthoringBundles/<Name>/<Name>.agent`)
- **Legacy Agent Builder** agents (`genAiPlannerBundles/…`, `genAiPlanners/…`)

```
Slack  ──(/agent-release, @mention)──▶  slack_app  ──▶  AdvisorService
                                                          ├─ AgentSource  (GitHub today, Salesforce org later)
                                                          │     └─ dependencies: full dependency scan of the agent (transitive + wiring)
                                                          ├─ static_checks (deterministic, no LLM)
                                                          ├─ ReleaseNotesLibrary
                                                          │     └─ help_portal: latest release + official PDF export from help.salesforce.com
                                                          ├─ Phase 1  scanner.profile_agent      agent + every dependency file → agent dossier
                                                          ├─ Phase 2  scanner.scan_release_notes EVERY page of the release notes, chunk by chunk
                                                          │     ├─ relevance: reading plan (priority topics first, coverage checked in code)
                                                          │     └─ evidence_guard on every candidate finding
                                                          ├─ Phase 3  ReleaseAdvisor → Claude    candidates → report
                                                          │     ├─ read_release_notes_pages / search_release_notes / read_section (confirm)
                                                          │     ├─ read_component          (any file of the agent's project)
                                                          │     └─ submit_report           (strict JSON schema)
                                                          ├─ evidence_guard (drops any item whose quote isn't on its cited page)
                                                          ├─ scoring       (deterministic 0–100 score)
                                                          └─ ReportCache   (SQLite, keyed by commit SHA)
```

## What managers see

`/agent-release Order_Status_Returns_Agent` produces a threaded reply containing:

- **Header:** `Order_Status_Returns_Agent — Winter '27 readiness 55/100 Amber`
- **Context line:** definition type, repo and commit, project API version, the release assessed
- **Executive summary:** three plain sentences
- **Agent profile** _(from your repository)_: business use case, capabilities, impact value
- **At a glance:** counts of must-fix items, upcoming changes, GA enhancements and beta/pilot enhancements
- 🔴 **Breaking / must fix**, 🟡 **Upcoming changes needing action**, 🟢 **Enhancements, generally available** and 🧪 **Enhancements, beta / pilot / preview**, each laid out as a comparison:

  | What it means for your agent | Today in your agent | Winter '27 change / what's coming / what it adds | What to do | Source |
  |---|---|---|---|---|

  Headings are written in the agent's terms (`SystemKnowledge_Tooling credential: connected-app support ends`), not as the release-note title. Beta, pilot and developer-preview features are listed separately from generally available ones, using the label the release notes give them.
- **Only what applies to your agent:** every item cites a verbatim excerpt from your agent's Agent Script or metadata, as well as the release-notes quote. Both are checked in code, and items that can't point at your agent are dropped. Org-wide or tooling changes that don't touch the agent's elements are left out.
- **Footer:** caveats, the score breakdown, how many release-notes pages were read (all of them, unless a chunk failed, which is flagged), the priority sections, the number of files in the agent scan, and how many items were removed because their quote wasn't found on the cited page

**Page references** look like `p. 164 (PDF p. 168)`, with the printed page number first, followed by the page in the downloaded PDF.

The **full report** is attached to the thread as a Markdown file. It has the tables, and an evidence section with every release-notes quote and repository excerpt.

## Evidence: the latest release notes, picked automatically

1. **Which release.** With `TARGET_RELEASE=latest` (the default), the bot asks help.salesforce.com for its current release-notes version. Today that's `264` = **Winter '27**. When Salesforce moves to the next release, the bot follows automatically. To pin a release, set `TARGET_RELEASE="Winter '27"`. Requests for any other release's notes are refused.
2. **The PDF.** `help_portal.py` does exactly what the **PDF** button on the release notes page does:
   - asks help.salesforce.com to export the PDF
   - waits for the export to finish
   - downloads the file

   The first export takes a few minutes; Winter '27 is about 1,100 pages and 33 MB. **Downloaded once per release.** On every request the bot checks which release is latest (a quick lookup):
   - **Same as the downloaded document** (for example, still Winter '27): the saved document in `.cache/release_notes/` (`winter27.pdf` plus its extracted text) is reused, with no download.
   - **A new release** (for example, Spring '27): that release's document is downloaded once and saved.
   - **To force a new download** (for example, if Salesforce publishes corrections): run `python -m release_advisor.cli notes fetch latest --refresh`.

   The Slack bot pre-fetches the notes at startup.
3. **Fallbacks.** help.salesforce.com's export endpoint is internal to the site, not a published API. If it ever changes, you can save the PDF manually into `release_notes/`, or set `RELEASE_NOTES_PDF_URLS`. The bot uses that copy instead.

## How a review works

### Phase 1: the agent and all its dependencies

The repository is downloaded once per commit as an archive. `release_advisor/dependencies.py` then crawls the agent's dependency graph inside its SFDX project. No list of what to look at is hard-coded; any project component whose API name appears in a scanned file is followed:

- **Forward, transitively:** the agent's actions → their Apex classes, Flows, GenAiFunctions and prompt templates → the classes, subflows, objects, fields, custom metadata, labels, named/external credentials and so on that those use, until nothing new is found.
- **Wiring:** permission sets and groups, profiles, triggers, Apex tests, flows, bots and connected/external client apps that reference anything in the forward set. These are added, but not expanded further.
- **Not in the project:** declared targets that are standard or org-only actions are listed as such.

Claude reads the agent definition, the README and specs, and **every file of that scan**, and writes the **agent dossier**. The dossier holds the business profile, a technical inventory of every element a release could affect (with its location), and the release-note subjects to watch for. If the scan exceeds `DEPENDENCY_MAX_CHARS` (default 1.5M characters), the files left out are listed in the report. Nothing is dropped silently.

Preview the scan with no Claude call: `python -m release_advisor.cli deps <Agent>`.

### Phase 2: the whole release notes, AI topics first

No section is chosen or skipped by rules. `release_advisor/relevance.py` splits the **entire** document, first PDF page to last, into chunks of about `SCAN_CHUNK_TOKENS` (default 60k). It checks in code that every page is covered exactly once. Claude reads every chunk in full with the dossier in context, and returns candidate findings with verbatim quotes. Each quote is checked against its page right away.

**Preference for AI topics.** Sections and chunks about the `PRIORITY_TOPICS` are marked as priority. The defaults are Agentforce, Agent Script, AIforce, Claude, Einstein, Generative AI, AI, LLM, Prompt Builder, MCP, Data 360 and similar. A section is a priority section when its title names a topic, or when its pages mention the topics at least `PRIORITY_DENSITY` times per page (default 5). A chunk elsewhere counts as priority when its own pages are that dense. Priority chunks are:

- read first,
- read with `ANTHROPIC_MODEL` / `ANTHROPIC_EFFORT` (default Sonnet 5 at `medium`). The other chunks use `SCAN_MODEL` / `SCAN_EFFORT` (default the same model at `low`).
- marked `priority_topic` and listed first in the report.

Every other chunk is still read in full. For Winter '27 that's all 1,096 PDF pages in 19 chunks, about 720k tokens, 6 of them priority chunks. The dossier prefix is cached across chunks, and chunks run `SCAN_CONCURRENCY` (default 4) at a time. A chunk that fails twice is reported as pages not read, never passed off as a complete read.

Preview the reading plan with no Claude call: `python -m release_advisor.cli sections`.

### Phase 3: the report

Claude receives the dossier, all verified candidates and the reading coverage. It merges duplicates, drops candidates that don't hold up, and checks implementation details with `read_component`. It can also re-read pages to confirm. It then submits the report, and every quote is checked again.

## How "strictly from the release notes" is enforced

1. Claude is instructed to use only the release notes, not its own knowledge or general best practices.
2. Every breaking issue, upcoming change and enhancement must include a **verbatim quote** and its **printed page number**.
3. After the run, `evidence_guard.py` checks each quote against the text of that page (or the next one, if the quote runs over a page break). Items whose quote isn't found are **dropped**, and the footer says how many.
4. The citation link is built in code, never by the model.
5. The agent profile is the only part not from the release notes. It's labelled "from your repository".

## Scoring

The score is calculated in code, so it's the same every time for the same findings. See `release_advisor/scoring.py`.

- Start at 100.
- Subtract for each breaking issue or static finding: 30 for Critical, 15 for High, 5 for Medium.
- Subtract 10 if the project's `sourceApiVersion` is more than one release behind the current GA release.

Status is **Red** if there is any Critical item or the score is below 50, **Amber** if the score is below 80, and **Green** otherwise.

## Setup

### 1. Install

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows  (source .venv/bin/activate on macOS/Linux)
pip install -r requirements.txt
cp .env.example .env            # then fill it in
```

### 2. Agent source: GitHub

Set `GITHUB_REPOS` to one or more comma-separated repo URLs containing SFDX projects. Add `/tree/<branch>` to a URL to pin a branch. For private repos, set `GITHUB_TOKEN` to a fine-grained token with **Contents: Read-only** access.

Check that the bot can see your agents:

```bash
python -m release_advisor.cli list
python -m release_advisor.cli static Order_Status_Returns_Agent     # deterministic checks only, no API cost
```

### 3. Release notes (automatic)

There's nothing to download by hand. To check, or to warm the cache before a demo:

```bash
python -m release_advisor.cli notes list                          # shows the resolved target release
python -m release_advisor.cli notes fetch latest                  # exports + extracts the PDF (first time: several minutes)
python -m release_advisor.cli notes search latest "Agent Script"
```

### 4. Claude

Set `ANTHROPIC_API_KEY`. The defaults keep cost down: `claude-sonnet-5` with adaptive thinking, effort `medium` for priority chunks and the report, and `low` for the other chunks. Server-side refusal fallbacks are off. For deeper analysis set `ANTHROPIC_MODEL=claude-opus-5` and a higher effort in `.env`. The bot logs the model it uses at startup.

Try a full analysis from the terminal:

```bash
python -m release_advisor.cli deps Order_Status_Returns_Agent                          # the agent's full dependency scan (no Claude call)
python -m release_advisor.cli sections                                                 # reading plan for the whole release notes (no Claude call)
python -m release_advisor.cli analyze Order_Status_Returns_Agent --markdown report.md  # full report with quotes and page numbers
python -m release_advisor.cli analyze Order_Status_Returns_Agent --json > report.json
```

### 5. Slack

1. Go to https://api.slack.com/apps, choose **Create New App**, then **From an app manifest**, and paste `slack_manifest.yml`.
2. Under **Basic Information**, go to **App-Level Tokens** and create a token with `connections:write`. Put it in `SLACK_APP_TOKEN` (starts with `xapp-`).
3. Install the app to your workspace. Put the **Bot User OAuth Token** in `SLACK_BOT_TOKEN` (starts with `xoxb-`).
4. Invite the bot to your channel with `/invite @Release Advisor`.
5. Run the bot:

```bash
python -m release_advisor
```

Socket Mode needs no public URL. The bot can run on any host that has outbound internet access, such as a VM, a container, or an internal server.

### Using it in Slack

| Command | Result |
|---|---|
| `/agent-release list` | Lists all agents found in the configured source |
| `/agent-release <AgentName>` | Report covering the current and upcoming releases |
| `/agent-release <AgentName> next` | Focuses on the upcoming release (`current` focuses on the current one) |
| `/agent-release <AgentName> refresh` | Writes a new report. The agent scan and release-notes read for the same commit are reused (`cli analyze --rescan` re-reads them too) |
| `@Release Advisor is Order_Status_Returns_Agent ready for the next release?` | Answers a free-text question in the thread |
| `@Release Advisor I want release suggestions for the Knowledge agent` | Natural phrasing works: the agent is matched by the words of its name (`System_Knowledge_Agent` → "knowledge"). If several agents match, the bot asks which one |
| Direct message to the bot, e.g. `release suggestions for Knowledge agent` | Same as a mention, no @ needed |

Reports are cached per agent, commit SHA, and focus for `CACHE_TTL_HOURS` (default 24). A new commit to the agent triggers a new analysis automatically.

## Switching to a Salesforce org later

Agent sources implement `release_advisor/sources/base.py::AgentSource` with three methods: `list_agents`, `load_agent`, and `read_component`. `sources/salesforce_org_source.py` is a stub that outlines the planned approach: JWT bearer auth through a Connected App, Tooling API for listing, and Metadata API retrieve for the bundle. Once it's implemented, set `AGENT_SOURCE=salesforce_org`. Nothing else in the app changes.

## Project layout

```
release_advisor/
  config.py            env-driven settings
  releases.py          API version ⇄ release name ("68.0" ⇄ "Winter '27")
  help_portal.py       help.salesforce.com client: latest release + official PDF export
  release_notes.py     target-release resolution, PDF caching/refresh, page search
  sources/             AgentSource interface, GitHub implementation, org stub, name resolution
  static_checks.py     Agent Script structural checks (undefined actions/transitions, missing blocks)
  advisor.py           Claude loop: prompts, tools, pause_turn handling, report finalisation
  report.py            submit_report schema + Pydantic models
  dependencies.py      full dependency scan of the agent inside its SFDX project
  scanner.py           phase 1 (agent dossier) and phase 2 (read every chunk of the release notes)
  relevance.py         reading plan: every page, priority topics first
  evidence_guard.py    drops any item whose quote is not on its cited page
  source_guard.py      allowed download hosts for manual PDF links
  scoring.py           deterministic score/status
  cache.py             SQLite report cache
  service.py           glue used by Slack and CLI
  slack_render.py      Block Kit rendering
  slack_app.py         Slack Bolt app (Socket Mode)
  cli.py               local CLI
```
