"""Owner-dispatched identity check and bounded synthetic notifications only."""
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import sys
import urllib.request
import zlib

try:
    from notify_bridge import mirror, write_json
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from notify_bridge import mirror, write_json

EXPECTED_TEAM = "T0C6EM7M70E"
EXPECTED_USER = "U0C6GSWNYH4"


def identity():
    token = os.environ.get("SLACK_BOT_TOKEN", "")
    if not token:
        raise RuntimeError("Slack secret is not configured")
    req = urllib.request.Request("https://slack.com/api/auth.test", data=b"{}", headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=15) as response:
        data = json.loads(response.read())
        scopes = sorted(s.strip() for s in response.headers.get("X-OAuth-Scopes", "").split(",") if s.strip())
    if data.get("ok") is not True or data.get("team_id") != EXPECTED_TEAM or data.get("user_id") != EXPECTED_USER:
        raise RuntimeError("Slack sender does not match the approved workspace/bot")
    if not {"chat:write", "files:write"}.issubset(set(scopes)):
        raise RuntimeError("Slack sender lacks the required message/file scopes")
    return {"status": "verified", "team_id": data["team_id"], "user_id": data["user_id"], "bot_id": data.get("bot_id"), "scopes": scopes}


def synthetic_png(path):
    """Generate a 320x180 synthetic color pattern; no private files are used."""
    width, height = 320, 180
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff)
    rows = b"".join(b"\x00" + b"".join(bytes((35, 78, 112) if (x // 40 + y // 30) % 2 else (92, 198, 181)) for x in range(width)) for y in range(height))
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


def main():
    directory = Path(os.environ.get("NOTIFY_STATE_DIR", ".notification-state"))
    directory.mkdir(parents=True, exist_ok=True)
    result_path = directory / "synthetic-result.json"
    test_id = os.environ.get("SLACK_TEST_ID", "")
    send = os.environ.get("SLACK_SEND_SYNTHETIC", "false") == "true"
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,60}", test_id):
        print("::error::A bounded alphanumeric test ID is required")
        return 1
    if result_path.exists():
        print("::error::This test ID already has a receipt; inspect it rather than retrying")
        return 1
    result = {"test_id": test_id, "identity": {"status": "unverified"}, "send_synthetic": send, "status": "started", "notifications": []}
    write_json(result_path, result)
    try:
        result["identity"] = identity()
        write_json(result_path, result)
        if send:
            if os.environ.get("GITHUB_RUN_ATTEMPT", "1") != "1":
                raise RuntimeError("Synthetic sends are blocked on reruns")
            os.environ["NOTIFICATION_MODE"] = "shadow"
            image = directory / "synthetic-migration-test.png"
            synthetic_png(image)
            text = {"content": f"[SYNTHETIC MIGRATION TEST {test_id}] Report text + generated color-pattern image. No private data. Discord remains active."}
            report = mirror(text, "reports", "synthetic:" + test_id, str(image))
            result["notifications"].append({"category": "reports", **report})
            write_json(result_path, result)
            if report["status"] != "sent":
                raise RuntimeError("Report/image delivery is incomplete; inspect receipt before retrying")
            duplicate = mirror(text, "reports", "synthetic:" + test_id, str(image))
            result["within_run_duplicate_check"] = duplicate["status"]
            if duplicate["status"] != "already_sent":
                raise RuntimeError("Within-run deduplication did not acknowledge prior delivery")
            alert = mirror({"content": f"[SYNTHETIC MIGRATION TEST {test_id}] Alert transport check only. This is not a real failure. No private data."}, "alerts", "synthetic:" + test_id)
            result["notifications"].append({"category": "alerts", **alert})
            write_json(result_path, result)
            if alert["status"] != "sent":
                raise RuntimeError("Alert delivery is incomplete; inspect receipt before retrying")
        result["status"] = "api_accepted" if send else "identity_verified"
        write_json(result_path, result)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except Exception:
        # Never print exception bodies or auth headers. Receipt only contains safe metadata.
        result["status"] = "needs_review"
        write_json(result_path, result)
        print("::error::Slack verification incomplete; inspect safe receipt. No automatic resend.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
