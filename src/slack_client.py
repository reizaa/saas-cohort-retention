"""Minimal Slack sender (standard library only).

Dry-run is the default: the message is written to a preview file and nothing is sent.
To send, pass send=True and configure ONE of these in the environment (never in code):

    SLACK_BOT_TOKEN + SLACK_CHANNEL   -> chat.postMessage (supports thread replies)
    SLACK_WEBHOOK_URL                 -> incoming webhook (no thread support)
"""
import json
import os
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://slack.com/api/"


def _call(method: str, token: str, payload: dict) -> dict:
    req = urllib.request.Request(
        API + method,
        data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json; charset=utf-8"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        body = json.loads(r.read())
    if not body.get("ok"):
        raise RuntimeError(f"Slack {method} failed: {body.get('error')}")
    return body


def find_thread(contains: str, oldest_ts: float) -> str | None:
    """Return the ts of the first channel message since `oldest_ts` whose text contains
    `contains` (e.g. the daily KPI post the pulse should reply under)."""
    token, channel = os.environ["SLACK_BOT_TOKEN"], os.environ["SLACK_CHANNEL"]
    q = urllib.parse.urlencode({"channel": channel, "oldest": oldest_ts, "limit": 50})
    req = urllib.request.Request(f"{API}conversations.history?{q}",
                                 headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        body = json.loads(r.read())
    for m in reversed(body.get("messages", [])):        # oldest first
        if contains.lower() in m.get("text", "").lower():
            return m["ts"]
    return None


def post(message: dict, *, send: bool = False, thread_ts: str | None = None,
         preview: Path | None = None) -> str:
    """message = {"text": fallback, "blocks": [...]}."""
    if not send:
        if preview:
            preview.parent.mkdir(parents=True, exist_ok=True)
            preview.write_text(json.dumps(message, indent=2, ensure_ascii=False))
        return f"DRY-RUN: not sent (preview -> {preview})"

    token, channel = os.environ.get("SLACK_BOT_TOKEN"), os.environ.get("SLACK_CHANNEL")
    if token and channel:
        payload = {"channel": channel, **message}
        if thread_ts:
            payload["thread_ts"] = thread_ts
        ts = _call("chat.postMessage", token, payload)["ts"]
        return f"SENT: chat.postMessage ts={ts}" + (f" (thread {thread_ts})" if thread_ts else "")

    url = os.environ.get("SLACK_WEBHOOK_URL")
    if url:
        if thread_ts:
            print("note: incoming webhooks cannot reply in a thread - posting to channel")
        req = urllib.request.Request(url, data=json.dumps(message).encode(),
                                     headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=30).read()
        return "SENT: webhook"
    raise SystemExit("set SLACK_BOT_TOKEN + SLACK_CHANNEL or SLACK_WEBHOOK_URL to send")
