"""Vendored Slack shadow notifier v1. Discord delivery remains authoritative.

NOTIFICATION_MODE=discord (default) or shadow. No cutover switch is exposed until
real Slack delivery, audience, image upload and rollback have been verified.
Secrets are read from environment only and are never logged or persisted.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time
import urllib.error
import urllib.request

ALLOWED_CHANNELS = {"alerts": "C0C6CBVA5TM", "reports": "C0C6LGRJ30R"}
API = "https://slack.com/api/"


class DeliveryError(Exception):
    def __init__(self, message, known_rejection=False):
        super().__init__(message)
        self.known_rejection = known_rejection


def safe_text(value):
    value = str(value or "")
    value = re.sub(r"<@!?\d+>|<@&\d+>|@everyone|@here", "", value)
    # Escape all incoming Slack control syntax before restoring HTTP links.
    value = value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    value = re.sub(r"\[([^\]\n]+)\]\((https?://[^\s)]+)\)", r"<\2|\1>", value)
    return value.strip()


def render(payload, category, repo, include_run=True):
    sections = [safe_text(payload.get("content", ""))]
    for embed in payload.get("embeds", []):
        title = safe_text(embed.get("title", ""))
        if embed.get("url", "").startswith(("https://", "http://")):
            title += "\n" + safe_text(embed["url"])
        sections.extend([title, safe_text(embed.get("description", ""))])
        for field in embed.get("fields", []):
            # Do not publish raw stderr/API responses from private diary failures.
            if repo.endswith("/a0ba-diary-blog") and category == "alerts" and field.get("name") in ("詳細", "レスポンス"):
                continue
            sections.append(safe_text(field.get("name", "")) + ": " + safe_text(field.get("value", "")))
        if embed.get("footer", {}).get("text"):
            sections.append(safe_text(embed["footer"]["text"]))
        if embed.get("image", {}).get("url", "").startswith(("https://", "http://")):
            sections.append(safe_text(embed["image"]["url"]))
    for row in payload.get("components", []):
        for component in row.get("components", []):
            if component.get("url", "").startswith(("https://", "http://")):
                sections.append(safe_text(component.get("label", "Issue")) + ": " + safe_text(component["url"]))
            elif component.get("custom_id", "").startswith(("approve:", "reject:")):
                action, number = component["custom_id"].split(":", 1)
                if number.isdigit():
                    guidance = "承認ボタンは廃止。証拠・build contractを確認してローカル試作を判断" if action == "approve" else "GitHub Issueで /reject をコメント"
                    sections.append(f"https://github.com/{repo}/issues/{number}: {guidance}")
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    if run_id and include_run:
        sections.append(f"https://github.com/{repo}/actions/runs/{run_id}")
    body = "\n\n".join(s for s in sections if s)
    # Keep content complete; chunk at message boundaries rather than truncating.
    return [body[i:i + 3500] for i in range(0, len(body), 3500)] or ["通知"]


def request(url, *, data, token=None, binary=False, form=False):
    headers = {"Content-Type": "application/octet-stream" if binary else ("application/x-www-form-urlencoded" if form else "application/json; charset=utf-8")}
    if token:
        headers["Authorization"] = "Bearer " + token
    from urllib.parse import urlencode
    raw = data if binary else (urlencode(data).encode() if form else json.dumps(data, ensure_ascii=False).encode())
    req = urllib.request.Request(url, data=raw, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            return response.read()
    except urllib.error.HTTPError as error:
        # Only 429 is safe to retry. Timeouts/5xx may already have delivered.
        if error.code == 429:
            delay = max(int(error.headers.get("Retry-After", "1")), 1)
            error.close()
            if delay > 30:
                raise DeliveryError("Slack retry window exceeds bounded shadow budget") from None
            time.sleep(delay)
            with urllib.request.urlopen(req, timeout=15) as response:
                return response.read()
        raise DeliveryError("Slack HTTP failure", known_rejection=error.code in {400, 401, 403, 404}) from None
    except (OSError, ValueError):
        raise DeliveryError("Slack transport failure; delivery may be uncertain") from None


def api(method, data, token):
    form = method in {"files.getUploadURLExternal", "files.completeUploadExternal"}
    if form:
        data = {k: json.dumps(v) if isinstance(v, (list, dict)) else v for k, v in data.items()}
    response = json.loads(request(API + method, data=data, token=token, form=form))
    if response.get("ok") is not True:
        # Only explicit pre-delivery rejections allow another provider. Server
        # errors/unknown codes can be ambiguous even with ok:false.
        safe = response.get("error") in {"invalid_auth", "not_authed", "missing_scope", "channel_not_found", "not_in_channel", "no_permission", "invalid_arguments", "missing_argument", "invalid_blocks", "msg_too_long"}
        raise DeliveryError("Slack API rejected delivery", known_rejection=safe)
    return response


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2))
    temporary.replace(path)


def _mirror(payload, category="reports", event="notification", file=None):
    """Best effort shadow delivery; failure never changes Discord/primary behavior."""
    if os.environ.get("NOTIFICATION_MODE", "discord") not in {"shadow", "slack"}:
        return {"status": "disabled"}
    primary_without_ledger = os.environ.get("NOTIFICATION_MODE") == "slack" and os.environ.get("NOTIFY_DURABLE_LEDGER") != "true"
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if repo not in {"kaionn/" + r for r in ("lazy-product-lab", "pain-collector", "signal-lab", "a0ba-diary-blog", "life")}:
        return {"status": "blocked", "reason": "repository not approved"}
    expected = ALLOWED_CHANNELS.get(category)
    configured = os.environ.get("SLACK_ALERT_CHANNEL_ID" if category == "alerts" else "SLACK_REPORT_CHANNEL_ID", "")
    token = os.environ.get("SLACK_BOT_TOKEN", "")
    config_missing = not expected or configured != expected or not token
    chunks = render(payload, category, repo)
    file_path = Path(file) if file else None
    file_bytes = file_path.read_bytes() if file_path else None
    # Timestamp/avatar/color fields are transport decoration, not event identity.
    durable = os.environ.get("NOTIFY_DURABLE_LEDGER") == "true"
    # Runtime links are diagnostics, not logical event identity. Same generated
    # artifact/content revision has one key across runs, including catch-up.
    stable_chunks = render(payload, category, repo, include_run=False)
    identity = {"repo": repo, "event": event, "category": category, "run": "durable-v1" if durable or os.environ.get("NOTIFICATION_MODE") == "slack" else os.environ.get("GITHUB_RUN_ID", "local"), "body": stable_chunks if durable else chunks,
                "file": hashlib.sha256(file_bytes).hexdigest() if file_bytes is not None else None}
    key = hashlib.sha256(json.dumps(identity, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    directory = Path(os.environ.get("NOTIFY_STATE_DIR", ".notification-state"))
    state_path = directory / (key + ".json")
    if durable or os.environ.get("NOTIFICATION_MODE") == "slack":
        # Original rendered content enables notification-only recovery; credentials
        # and unsanitized Discord payloads never enter the outbox or Git ledger.
        outbox = Path(".notification-outbox") / key
        write_json(outbox / "event.json", {"key": key, "category": category, "event": event, "rendered_chunks": chunks, "stable_chunks": stable_chunks, "file_name": file_path.name if file_path else None})
        if file_path:
            import shutil
            shutil.copyfile(file_path, outbox / file_path.name)
    if config_missing or primary_without_ledger:
        return {"status": "blocked", "key": key, "reason": "Slack primary requires durable ledger" if primary_without_ledger else "sender/channel not configured"}
    ledger = None
    if durable:
        try:
            from notify_ledger import GitLedger
            ledger = GitLedger(repo, key)
            prior = ledger.load()
        except Exception:
            print("::warning::Durable notification ledger unavailable; no Slack send; Discord retained.", file=sys.stderr)
            return {"status": "ledger_unavailable", "key": key}
        if prior:
            write_json(state_path, prior)
            if prior.get("status") in {"sent", "fallback_sent"}:
                return {"status": "already_sent", "key": key}
            # Never take over an unfinished claim, even from an earlier run.
            return {"status": "needs_reconciliation", "key": key}
    state = json.loads(state_path.read_text()) if state_path.exists() else {"key": key, "channel": expected, "repo": repo, "event": event, "parts": [], "status": "pending"}
    if state.get("status") in {"sent", "fallback_sent"}:
        return {"status": "already_sent", "key": key}
    if state.get("status") in {"needs_reconciliation", "rejected", "fallback_sending"}:
        return {"status": "needs_reconciliation", "key": key}
    if ledger:
        state.update(schema=1, status="sending", stage="reserved", run_id=os.environ.get("GITHUB_RUN_ID", ""), run_attempt=os.environ.get("GITHUB_RUN_ATTEMPT", "1"), mode=os.environ.get("NOTIFICATION_MODE", "discord"))
    def persist():
        # Durable acknowledgement must precede any subsequent Slack mutation.
        if ledger:
            ledger.save(state)
        write_json(state_path, state)
    # Persist only identifiers/progress. Payloads may contain private content;
    # rerun the notification-only fixture to reconcile, never upload credentials.
    try:
        persist()  # CAS claim; concurrent loser never reaches Slack.
    except Exception:
        return {"status": "ledger_unavailable" if ledger else "adapter_failed", "key": key}
    try:
        for index, chunk in enumerate(chunks):
            if index < len(state["parts"]):
                continue
            prefix = "[SHADOW TEST] " if os.environ.get("NOTIFICATION_MODE") == "shadow" else ""
            data = {"channel": expected, "text": prefix + chunk, "unfurl_links": False, "unfurl_media": False}
            if state["parts"]:
                data["thread_ts"] = state["parts"][0]
            state["stage"] = "text:" + str(index)
            persist()
            response = api("chat.postMessage", data, token)
            ts = response.get("ts")
            if not ts:
                raise DeliveryError("Slack acknowledgement missing timestamp")
            state["parts"].append(ts)
            persist()
        if file_path and not state.get("file_sent"):
            if not state.get("file_id"):
                state["stage"] = "get_upload_url"
                persist()
                upload = api("files.getUploadURLExternal", {"filename": file_path.name, "length": len(file_bytes)}, token)
                url = upload.get("upload_url", "")
                from urllib.parse import urlparse
                parsed = urlparse(url)
                if parsed.scheme != "https" or not (parsed.hostname or "").endswith(".slack.com"):
                    raise DeliveryError("Slack upload URL rejected")
                state["file_id"] = upload["file_id"]
                state["stage"] = "upload_bytes"
                persist()
                request(url, data=file_bytes, binary=True)
                state["file_uploaded"] = True
                persist()
            if not state.get("file_uploaded"):
                raise DeliveryError("File transport state is unconfirmed")
            state["stage"] = "complete_upload"
            persist()
            api("files.completeUploadExternal", {"files": [{"id": state["file_id"], "title": file_path.name}], "channel_id": expected, "thread_ts": state["parts"][0]}, token)
            state["file_sent"] = True
            persist()
        state["status"] = "sent"
        persist()
        return {"status": "sent", "key": key}
    except Exception as error:
        rejected = isinstance(error, DeliveryError) and error.known_rejection and not state.get("parts") and not state.get("file_id")
        state["status"] = "rejected" if rejected else "needs_reconciliation"
        try:
            persist()
        except Exception:
            write_json(state_path, state)
        print("::warning::Slack shadow delivery incomplete; Discord retained. Check notification delivery artifact.", file=sys.stderr)
        return {"status": "known_rejected" if rejected else "needs_reconciliation", "key": key}


def flag_primary_error():
    if os.environ.get("NOTIFICATION_MODE") != "slack":
        return
    os.environ["NOTIFY_DELIVERY_ERROR"] = "true"
    # Runner command file is separate from the workspace receipt directory.
    # Persist only a boolean so the final audit catches local receipt failures.
    command_file = os.environ.get("GITHUB_ENV")
    if command_file:
        try:
            with open(command_file, "a") as output:
                output.write("NOTIFY_DELIVERY_ERROR=true\n")
        except OSError:
            print("::error::Primary notification state cannot be recorded; reconciliation required.", file=sys.stderr)


def mirror(payload, category="reports", event="notification", file=None):
    try:
        result = _mirror(payload, category, event, file)
    except Exception:
        print("::warning::Notification adapter failed; inspect receipt/outbox.", file=sys.stderr)
        result = {"status": "adapter_failed"}
    if os.environ.get("NOTIFICATION_MODE") in {"shadow", "slack"}:
        try:
            write_json(Path(os.environ.get("NOTIFY_STATE_DIR", ".notification-state")) / "last-result.json", result)
        except Exception:
            flag_primary_error()
    if result.get("status") not in {"sent", "already_sent", "known_rejected", "disabled"}:
        flag_primary_error()
    return result


def discord_gate(result=None):
    """Reserve a Discord fallback only after a confirmed empty Slack rejection.

    Unknown Slack or ledger outcomes NEVER trigger a second provider. A crash
    after fallback reservation also requires manual reconciliation.
    """
    if os.environ.get("NOTIFICATION_MODE", "discord") != "slack":
        return True
    try:
        directory = Path(os.environ.get("NOTIFY_STATE_DIR", ".notification-state"))
        result = result if result is not None else json.loads((directory / "last-result.json").read_text())
        if result.get("status") != "known_rejected":
            return False
        from notify_ledger import GitLedger
        store = GitLedger(os.environ.get("GITHUB_REPOSITORY", ""), result["key"])
        state = store.load()
        if not state or state.get("status") != "rejected" or state.get("parts") or state.get("file_id") or state.get("run_id") != os.environ.get("GITHUB_RUN_ID") or state.get("run_attempt") != os.environ.get("GITHUB_RUN_ATTEMPT", "1"):
            return False
        state.update(status="fallback_sending", stage="discord_fallback")
        store.save(state)
        write_json(directory / (result["key"] + ".json"), state)
        return True
    except Exception:
        print("::warning::Fallback reservation unavailable; no blind Discord send.", file=sys.stderr)
        return False


def discord_ack(http_status):
    if os.environ.get("NOTIFICATION_MODE", "discord") != "slack":
        return
    try:
        directory = Path(os.environ.get("NOTIFY_STATE_DIR", ".notification-state"))
        result = json.loads((directory / "last-result.json").read_text())
        if result.get("status") != "known_rejected":
            return
        from notify_ledger import GitLedger
        store = GitLedger(os.environ.get("GITHUB_REPOSITORY", ""), result["key"])
        state = store.load()
        if not state or state.get("status") != "fallback_sending" or state.get("run_id") != os.environ.get("GITHUB_RUN_ID") or state.get("run_attempt") != os.environ.get("GITHUB_RUN_ATTEMPT", "1"):
            return
        success = str(http_status).isdigit() and 200 <= int(http_status) < 300
        state.update(status="fallback_sent" if success else "needs_reconciliation", stage="discord_acknowledged" if success else "discord_unconfirmed")
        store.save(state)
        write_json(directory / (result["key"] + ".json"), state)
    except Exception:
        print("::warning::Discord fallback acknowledgement unconfirmed; reconcile manually.", file=sys.stderr)


def delivery_http():
    """Compatibility status for existing diary notification-state handling."""
    try:
        directory = Path(os.environ.get("NOTIFY_STATE_DIR", ".notification-state"))
        result = json.loads((directory / "last-result.json").read_text())
        return 204 if result.get("status") in {"sent", "already_sent"} else 503
    except Exception:
        return 503


def audit_delivery():
    if os.environ.get("NOTIFICATION_MODE") != "slack":
        return 0
    if os.environ.get("NOTIFY_DELIVERY_ERROR") == "true":
        print("::error::Primary notification delivery needs reconciliation; business work retained.")
        return 1
    directory = Path(os.environ.get("NOTIFY_STATE_DIR", ".notification-state"))
    for path in directory.glob("*.json"):
        if path.name != "last-result.json" and not re.fullmatch(r"[0-9a-f]{64}\.json", path.name):
            continue
        data = json.loads(path.read_text())
        # Marker tracks blocked/preflight outcomes without a persisted claim.
        valid = {"sent", "already_sent"} if path.name == "last-result.json" else {"sent", "fallback_sent"}
        if path.name == "last-result.json" and data.get("status") == "known_rejected":
            state_path = directory / (data.get("key", "") + ".json")
            if state_path.exists() and json.loads(state_path.read_text()).get("status") == "fallback_sent":
                continue
        if data.get("status") not in valid:
            print("::error::Notification delivery pending reconciliation; business work retained.")
            return 1
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--category", choices=["reports", "alerts"], default="reports")
    parser.add_argument("--event", default="notification")
    parser.add_argument("--file")
    parser.add_argument("--discord-gate", action="store_true")
    parser.add_argument("--discord-ack-status")
    parser.add_argument("--delivery-http", action="store_true")
    parser.add_argument("--audit", action="store_true")
    args = parser.parse_args()
    if args.discord_gate:
        return 0 if discord_gate() else 10
    if args.discord_ack_status is not None:
        discord_ack(args.discord_ack_status); return 0
    if args.delivery_http:
        print(delivery_http()); return 0
    if args.audit:
        return audit_delivery()
    try:
        result = mirror(json.load(sys.stdin), args.category, args.event, args.file)
        print(json.dumps(result))
    except Exception:
        # Fail open to the existing Discord send. Do not print payload/credential.
        print("::warning::Slack shadow adapter failed; Discord retained.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
