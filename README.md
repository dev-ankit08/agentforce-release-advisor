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
                                                          ├─ static_checks (deterministic, no LLM)
                                                          ├─ ReleaseNotesLibrary
                                                          │     └─ help_portal: latest release + official PDF export from help.salesforce.com
                                                          ├─ relevance     (techniques the agent uses → sections read in full)
                                                          ├─ ReleaseAdvisor → Claude
                                                          │     ├─ full text of the selected sections (in context, cached)
                                                          │     ├─ read_section            (read another section in full)
                                                          │     ├─ search_release_notes / read_release_notes_pages  (locate passages)
                                                          │     ├─ read_component          (Apex / Flow / GenAiFunction source)
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
- 🔴 **Breaking / must fix:** static-check findings plus release-driven issues, each with where, why, fix, a verbatim quote, and its page
- 🟡 **Upcoming changes needing action:** future-dated changes announced in the release notes, such as release updates enforced later, model reroutes, or scheduled retirements
- 🟢 **Recommended enhancements:** new capabilities in the release, each with what it applies to in your agent, the benefit as the release notes state it, a quote, and its page
- **Footer:** caveats, the score breakdown, the sections read in full, and how many items were removed because their quote wasn't found on the cited page

**Page references** look like `p. 164 (PDF p. 168)`, with the printed page number first, followed by the page in the downloaded PDF.

The **full report** is attached to the thread as a Markdown file. It has every item, every quote, and why each section was read.

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

## Relevant sections are read in full

The bot reads the release notes' table of contents, then decides from **the techniques your agent uses** which top-level sections Claude must read **in full**. It doesn't rely on search snippets. See `release_advisor/relevance.py`.

| Your agent / repository uses… | Read in full |
|---|---|
| Any Agentforce agent | Agentforce and Generative AI, AIforce, Release Updates |
| Apex (`apex://` actions or Apex classes) | Platform (Apex, sharing, developer changes) |
| Flows (`flow://` actions or Flows) | Automation |
| Permission sets, Connected / External Client Apps, Named / External Credentials, External Services, HTTP callouts | Security, Identity, and Privacy |
| `@MessagingSession` variables, a customer/service agent, messaging channels, human escalation | Service |
| Slack, or an employee agent | Slack Integrations |
| Data library, retriever, Data Cloud | Data 360 |

- **Change-log entries:** each selected section's entries in the "Release Note Changes by Month" log are included too, for example the Agentforce model reroute dates.
- **Claude can read more:** Claude also sees the full table of contents. If another section is relevant to your agent, it reads that one in full with `read_section`. The report lists every section read and why.
- **Adding sections:** use `EXTRA_FULL_READ_SECTIONS=Analytics,Sales`.
- **Size limit:** if the full-read text would exceed `MAX_FULL_READ_TOKENS` (default 400k), the bot stops and lists the sections. It never truncates. For example, `Order_Status_Returns_Agent` reads 6 sections, about 230k tokens.
- **Preview:** `python -m release_advisor.cli sections <Agent>` shows what would be read, and why, with no Claude call.

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

Set `ANTHROPIC_API_KEY`. The defaults are `claude-opus-5`, adaptive thinking, and effort `high`, with server-side refusal fallbacks turned on. You can change these in `.env`.

Try a full analysis from the terminal:

```bash
python -m release_advisor.cli sections Order_Status_Returns_Agent                      # which sections are read in full, and why (no Claude call)
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
| `/agent-release <AgentName> refresh` | Ignores the cached result and runs a new analysis |
| `@Release Advisor is Order_Status_Returns_Agent ready for the next release?` | Answers a free-text question in the thread |

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
  relevance.py         techniques the agent uses -> release-notes sections read in full
  evidence_guard.py    drops any item whose quote is not on its cited page
  source_guard.py      allowed download hosts for manual PDF links
  scoring.py           deterministic score/status
  cache.py             SQLite report cache
  service.py           glue used by Slack and CLI
  slack_render.py      Block Kit rendering
  slack_app.py         Slack Bolt app (Socket Mode)
  cli.py               local CLI
```
