"""Command-line entry point, for local testing without Slack.

  python -m release_advisor.cli list
  python -m release_advisor.cli deps Order_Status_Returns_Agent            # the agent's full dependency scan (no Claude call)
  python -m release_advisor.cli sections                                   # how the whole release notes will be read (no Claude call)
  python -m release_advisor.cli analyze Order_Status_Returns_Agent [--markdown report.md] [--json] [--fresh]
  python -m release_advisor.cli static Order_Status_Returns_Agent
  python -m release_advisor.cli notes list | fetch latest | toc latest | search latest "Agent Script"
"""

from __future__ import annotations

import argparse
import json
import logging
import sys

from .config import get_settings
from .release_notes import ReleaseNotesLibrary, ReleaseNotesUnavailable
from .service import AdvisorService
from .slack_render import render_markdown, render_report
from .static_checks import run_static_checks


def _blocks_to_text(blocks: list[dict]) -> str:
    out = []
    for block in blocks:
        if block["type"] == "header":
            out.append("=" * 80 + "\n" + block["text"]["text"] + "\n" + "=" * 80)
        elif block["type"] == "section":
            out.append(block["text"]["text"])
        elif block["type"] == "context":
            out.append("  " + " ".join(e["text"] for e in block["elements"]))
        elif block["type"] == "divider":
            out.append("-" * 80)
    return "\n".join(out)


def _progress(msg: str) -> None:
    print(f"  ... {msg}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="release_advisor")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="List agents in the configured source")
    sub.add_parser("sections", help="Reading plan for the whole release notes (priority topics first)")
    for name in ("analyze", "static", "deps"):
        p = sub.add_parser(name)
        p.add_argument("agent")
        if name == "analyze":
            p.add_argument("--focus", choices=["current", "next", "both"], default="both")
            p.add_argument("--question", default="")
            p.add_argument("--fresh", action="store_true", help="Write a new report (reuses the saved scan of this commit)")
            p.add_argument("--rescan", action="store_true", help="Also re-read the agent and the whole release notes")
            p.add_argument("--json", action="store_true", help="Print the full report as JSON")
            p.add_argument("--markdown", metavar="FILE", help="Also write the full report as Markdown")
    notes = sub.add_parser("notes", help="Inspect official release-notes PDFs")
    notes_sub = notes.add_subparsers(dest="notes_cmd", required=True)
    notes_sub.add_parser("list", help="Target release and downloaded documents")
    fetch = notes_sub.add_parser("fetch", help="Load a release's notes (downloads only if not already downloaded)")
    fetch.add_argument("release")
    fetch.add_argument("--refresh", action="store_true", help="Force a new download even if already downloaded")
    toc = notes_sub.add_parser("toc", help="Table of contents with printed and PDF page ranges")
    toc.add_argument("release")
    search = notes_sub.add_parser("search", help="Keyword search in a release's notes")
    search.add_argument("release")
    search.add_argument("query")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING)
    # Windows consoles default to cp1252; release-notes text contains characters it cannot encode.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    settings = get_settings()

    if args.cmd == "notes":
        library = ReleaseNotesLibrary(settings)
        try:
            if args.notes_cmd == "list":
                target = library.target_release()
                downloaded = library.downloaded_releases()
                print(f"Target release: {target or '(unrestricted)'}  [TARGET_RELEASE={settings.target_release}]")
                if target:
                    state = "already downloaded - will be reused" if target in downloaded else "not downloaded yet - will be downloaded on first use"
                    print(f"  {target}: {state}")
                for label, pages in sorted(downloaded.items()):
                    print(f"  downloaded  {label:12} {pages or '?'} pages")
                for label, origin in sorted(library.configured_releases().items()):
                    print(f"  manual PDF  {label:12} {origin}")
                return 0
            release = library.target_release() if args.release.lower() in {"latest", "target"} else args.release
            if args.notes_cmd == "fetch":
                doc = library.get(release, progress=_progress, refresh=args.refresh)
                print(f"{doc.release}: {len(doc.pages)} pages\n  origin:  {doc.origin}\n  cite as: {doc.cite_url}")
            elif args.notes_cmd == "toc":
                doc = library.get(release, progress=_progress)
                for sec in doc.toc():
                    pdf_a, pdf_b = doc.pdf_page(sec.printed_start), doc.pdf_page(sec.printed_end)
                    pdf = f"PDF {pdf_a}-{pdf_b}" if pdf_a and pdf_b and sec.page_count else "-"
                    print(f"{sec.title:42} printed {sec.printed_start}-{sec.printed_end:<6} {pdf:14} {sec.page_count} pages")
            else:
                for hit in library.search(release, args.query):
                    print(f"--- printed page {hit['printed_page']} (PDF {hit['pdf_page']})\n{hit['snippet'][:600]}\n")
        except ReleaseNotesUnavailable as exc:
            print(str(exc), file=sys.stderr)
            return 1
        return 0

    service = AdvisorService(settings)

    if args.cmd == "sections":
        doc = service.advisor.target_doc(_progress)
        plan = service.advisor.reading_plan(doc)
        print(plan.summary())
        print(f"Priority topics: {', '.join(settings.priority_topics)}")
        for sec in plan.priority_sections:
            print(f"  priority section  {sec.title:40} printed pp. {sec.printed_pages:10} {sec.reason}")
        print("Reading order:")
        for n, chunk in enumerate(plan.chunks, 1):
            tag = "PRIORITY" if chunk.priority else "full    "
            print(f"  {n:3}. {tag} {chunk.page_range(doc):32} ~{chunk.tokens:>7,} tok  "
                  f"{', '.join(chunk.sections)[:60]}  [{chunk.reason()}]")
        return 0

    if args.cmd == "list":
        for a in service.list_agents():
            print(f"{a.name:45} {a.kind:15} {a.location}  ({a.path})")
        return 0

    resolution = service.resolve(args.agent)
    if resolution.agent is None:
        names = [a.name for a in (resolution.candidates or resolution.all_agents)]
        print(f"Agent '{args.agent}' not found or ambiguous. Options: {', '.join(names)}", file=sys.stderr)
        return 2

    if args.cmd == "static":
        bundle = service.source.load_agent(resolution.agent)
        print(json.dumps([f.to_dict() for f in run_static_checks(bundle)], indent=2))
        return 0

    if args.cmd == "deps":
        bundle = service.source.load_agent(resolution.agent)
        print(f"{bundle.ref.name}: {len(bundle.files)} definition file(s), {len(bundle.dependencies)} dependency file(s), "
              f"~{sum(map(len, bundle.dependencies.values())):,} characters")
        print(bundle.dependency_outline)
        return 0

    report, cached = service.analyze(
        resolution.agent, question=args.question, focus=args.focus, fresh=args.fresh, progress=_progress,
        rescan=args.rescan,
    )
    if args.markdown:
        with open(args.markdown, "w", encoding="utf-8") as fh:
            fh.write(render_markdown(report))
        print(f"Full report written to {args.markdown}", file=sys.stderr)
    if args.json:
        print(report.model_dump_json(indent=2))
    else:
        print(_blocks_to_text(render_report(report, from_cache=cached)[1]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
