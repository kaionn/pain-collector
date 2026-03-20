"""ポートフォリオ管理: Project V2 のステータスフローを追跡しスナップショットを保存する."""

import json
import os
import subprocess
from datetime import datetime, timezone, timedelta

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JST = timezone(timedelta(hours=9))

# ステータスフロー
STATUSES = ["Idea", "Validated", "Building", "Launched", "Archived"]


def _fetch_issues_by_status() -> dict[str, list[dict]]:
    """Issue をステータス別に分類する."""
    status_map: dict[str, list[dict]] = {s: [] for s in STATUSES}

    try:
        result = subprocess.run(
            [
                "gh", "issue", "list",
                "--label", "pain-report",
                "--state", "all",
                "--json", "number,title,labels,state",
                "--limit", "500",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            return status_map

        issues = json.loads(result.stdout)

        for issue in issues:
            labels = {l["name"] for l in issue.get("labels", [])}
            state = issue.get("state", "")

            if state == "CLOSED":
                status_map["Archived"].append(issue)
            elif "🏆score-S" in labels or "🥇score-A" in labels:
                status_map["Validated"].append(issue)
            else:
                status_map["Idea"].append(issue)

    except Exception as e:
        print(f"[Portfolio] Issue 取得失敗: {e}")

    return status_map


def generate_snapshot() -> str:
    """ポートフォリオスナップショットを生成する."""
    today = datetime.now(JST).date().isoformat()
    status_map = _fetch_issues_by_status()

    lines = [
        f"# Portfolio Snapshot: {today}\n",
    ]

    total = sum(len(v) for v in status_map.values())
    lines.append(f"合計: {total} 件\n")

    # ステータス別サマリー
    lines.append("## ステータス別\n")
    lines.append("| ステータス | 件数 |")
    lines.append("|------------|------|")
    for status in STATUSES:
        count = len(status_map[status])
        lines.append(f"| {status} | {count} |")
    lines.append("")

    # Validated（スコアが高い）の詳細
    validated = status_map.get("Validated", [])
    if validated:
        lines.append("## Validated（高スコア）\n")
        for issue in validated[:20]:
            lines.append(f"- #{issue['number']} {issue['title']}")
        lines.append("")

    # Idea の件数が多い場合はカテゴリ別に集計
    ideas = status_map.get("Idea", [])
    if ideas:
        lines.append(f"## Idea ({len(ideas)} 件)\n")
        cat_counter: dict[str, int] = {}
        for issue in ideas:
            labels = [l["name"] for l in issue.get("labels", [])]
            for label in labels:
                if label not in ("pain-report",) and not label.startswith(("📱", "🌐", "🧩", "⌨️", "☁️", "💰", "🔥", "🎯", "🟢", "🟡", "🏆", "🥇", "🥈", "🥉", "stale")):
                    cat_counter[label] = cat_counter.get(label, 0) + 1
        for cat, count in sorted(cat_counter.items(), key=lambda x: x[1], reverse=True)[:10]:
            lines.append(f"- {cat}: {count} 件")
        lines.append("")

    return "\n".join(lines)


def run() -> None:
    """ポートフォリオスナップショットを生成して保存する."""
    report = generate_snapshot()

    today = datetime.now(JST).date().isoformat()
    output_dir = os.path.join(BASE_DIR, "portfolio")
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, f"{today}.md")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(report)

    print(f"[Portfolio] スナップショットを保存: {output_path}")
