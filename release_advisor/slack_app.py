"""Slack entry point (Socket Mode): slash command + @mentions."""

from __future__ import annotations

import logging
import re
import threading
import time

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from .config import Settings, get_settings
from .service import AdvisorService
from .slack_render import USAGE, esc, render_agent_list, render_markdown, render_report

log = logging.getLogger(__name__)

_MENTION_RE = re.compile(r"<@[A-Z0-9]+>")
_PROGRESS_INTERVAL_SECONDS = 8


def parse_request(text: str) -> dict:
    """Split user text into intent, agent text, focus and refresh flag."""
    clean = _MENTION_RE.sub("", text or "").strip()
    words = clean.split()
    lowered = [w.lower().strip("?.!,") for w in words]
    if not words or lowered[0] in {"help", "usage"}:
        return {"intent": "help"}
    if lowered[0] == "list" or "which agents" in clean.lower() or "list agents" in clean.lower():
        return {"intent": "list"}
    focus = "both"
    if any(w in {"next", "upcoming", "preview"} for w in lowered):
        focus = "next"
    elif any(w in {"current", "now", "today"} for w in lowered) and focus == "both":
        focus = "current"
    fresh = any(w in {"refresh", "fresh", "rerun"} for w in lowered)
    return {"intent": "analyze", "text": clean, "focus": focus, "fresh": fresh}


def build_app(settings: Settings) -> App:
    app = App(token=settings.slack_bot_token)
    service = AdvisorService(settings)
    slots = threading.BoundedSemaphore(settings.max_concurrent_analyses)
    usage = USAGE.format(cmd=settings.slack_command)

    def handle(text: str, say_blocks, post_status, update_status, upload=None) -> None:
        req = parse_request(text)
        if req["intent"] == "help":
            say_blocks("Usage", [{"type": "section", "text": {"type": "mrkdwn", "text": usage}}])
            return
        if req["intent"] == "list":
            say_blocks(*render_agent_list(service.list_agents()))
            return

        resolution = service.resolve(req["text"])
        if resolution.agent is None:
            if resolution.candidates:
                intro = "That matches more than one agent — please name one of these:"
                say_blocks(*render_agent_list(resolution.candidates, intro))
            else:
                intro = f"I couldn't find an agent in _{esc(req['text'])}_. Available agents:"
                say_blocks(*render_agent_list(resolution.all_agents, intro))
            return

        agent = resolution.agent
        if not slots.acquire(blocking=False):
            say_blocks("Busy", [{"type": "section", "text": {"type": "mrkdwn", "text":
                       ":hourglass: Several analyses are already running. Please try again in a few minutes."}}])
            return
        status_ts = None
        try:
            status_ts = post_status(f":mag: Analyzing *{esc(agent.name)}* against official Salesforce release notes… (usually 1–3 min)")
            last = [0.0]

            def progress(msg: str) -> None:
                now = time.time()
                if now - last[0] >= _PROGRESS_INTERVAL_SECONDS:
                    last[0] = now
                    update_status(status_ts, f":mag: *{esc(agent.name)}* — {esc(msg)[:200]}", None)

            report, cached = service.analyze(
                agent, question=req["text"], focus=req["focus"], fresh=req["fresh"], progress=progress
            )
            text, blocks = render_report(report, from_cache=cached)
            update_status(status_ts, text, blocks)
            if upload and status_ts:
                release = report.submitted.current_release.replace("'", "").replace(" ", "")
                try:
                    upload(status_ts, f"{agent.name}_{release}_release_report.md", render_markdown(report))
                except Exception:
                    log.exception("Could not attach the full report (is the files:write scope granted?)")
        except Exception as exc:
            log.exception("Analysis failed for %s", agent.name)
            update_status(status_ts, f":warning: Analysis of *{esc(agent.name)}* failed: {esc(str(exc))[:500]}", None)
        finally:
            slots.release()

    @app.command(settings.slack_command)
    def on_command(ack, command, client, respond):
        ack()
        channel = command["channel_id"]

        def say_blocks(text, blocks):
            respond(text=text, blocks=blocks, response_type="ephemeral")

        def post_status(text):
            try:
                resp = client.chat_postMessage(channel=channel, text=text)
                return resp["ts"]
            except Exception:  # bot not in channel: fall back to response_url
                respond(text=text, response_type="in_channel")
                return None

        def update_status(ts, text, blocks):
            if ts:
                client.chat_update(channel=channel, ts=ts, text=text, blocks=blocks or [])
            else:
                respond(text=text, blocks=blocks, response_type="in_channel", replace_original=False)

        def upload(ts, filename, content):
            client.files_upload_v2(channel=channel, thread_ts=ts, filename=filename, content=content,
                                   title="Full release report", initial_comment="Full report with every citation:")

        handle(command.get("text", ""), say_blocks, post_status, update_status, upload)

    @app.event("app_mention")
    def on_mention(event, client):
        channel = event["channel"]
        thread_ts = event.get("thread_ts") or event["ts"]

        def say_blocks(text, blocks):
            client.chat_postMessage(channel=channel, thread_ts=thread_ts, text=text, blocks=blocks)

        def post_status(text):
            return client.chat_postMessage(channel=channel, thread_ts=thread_ts, text=text)["ts"]

        def update_status(ts, text, blocks):
            client.chat_update(channel=channel, ts=ts, text=text, blocks=blocks or [])

        def upload(_ts, filename, content):
            client.files_upload_v2(channel=channel, thread_ts=thread_ts, filename=filename, content=content,
                                   title="Full release report", initial_comment="Full report with every citation:")

        handle(event.get("text", ""), say_blocks, post_status, update_status, upload)

    return app


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = get_settings()
    missing = [n for n, v in (("SLACK_BOT_TOKEN", settings.slack_bot_token), ("SLACK_APP_TOKEN", settings.slack_app_token)) if not v]
    if missing:
        raise SystemExit(f"Missing environment variables: {', '.join(missing)}")
    app = build_app(settings)
    threading.Thread(target=_prefetch_release_notes, args=(settings,), daemon=True).start()
    SocketModeHandler(app, settings.slack_app_token).start()


def _prefetch_release_notes(settings: Settings) -> None:
    """Warm the release-notes cache at startup; the first export can take several minutes."""
    from .release_notes import ReleaseNotesLibrary

    try:
        library = ReleaseNotesLibrary(settings)
        target = library.target_release()
        if target:
            doc = library.get(target, progress=lambda m: log.info("Release notes: %s", m))
            log.info("Release notes ready: %s (%d pages)", doc.release, len(doc.pages))
    except Exception:
        log.exception("Could not prefetch release notes; they will be fetched on first request")


if __name__ == "__main__":
    main()
