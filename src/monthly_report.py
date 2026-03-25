"""月次レポート: カテゴリ別推移、市場シグナル分布、Top 10 ペインを生成する."""

import json
import logging
import os
from collections import Counter
from datetime import date, timedelta

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_month_pains(target_date: date) -> list[dict]:
    """対象月の daily/*.md から抽出済みペインを収集する."""
    pains = []
    first_day = target_date.replace(day=1)

    # 前月のデータを読む
    if target_date.day == 1:
        # 月初に実行される想定なので前月を対象にする
        last_month = first_day - timedelta(days=1)
        first_day = last_month.replace(day=1)
        last_day = last_month
    else:
        last_day = target_date

    current = first_day
    while current <= last_day:
        daily_path = os.path.join(BASE_DIR, "daily", f"{current.isoformat()}.md")
        if os.path.exists(daily_path):
            try:
                with open(daily_path, encoding="utf-8") as f:
                    current_category = ""
                    for line in f:
                        if line.startswith("## "):
                            # "## 💻 テクノロジー" → "テクノロジー"
                            parts = line[3:].strip().split(" ", 1)
                            current_category = parts[1] if len(parts) > 1 else parts[0]
                        elif line.startswith("### "):
                            pain_text = line[4:].strip()
                            if pain_text:
                                pains.append({
                                    "pain": pain_text,
                                    "date": current.isoformat(),
                                    "category": current_category,
                                })
            except OSError:
                pass
        current += timedelta(days=1)

    return pains


def _load_month_raw_data(target_date: date) -> dict:
    """対象月の raw データから統計を集計する."""
    stats = {"total_posts": 0, "by_source": Counter(), "days_with_data": 0}
    first_day = target_date.replace(day=1)

    if target_date.day == 1:
        last_month = first_day - timedelta(days=1)
        first_day = last_month.replace(day=1)
        last_day = last_month
    else:
        last_day = target_date

    current = first_day
    while current <= last_day:
        raw_path = os.path.join(BASE_DIR, "raw", f"{current.isoformat()}.json")
        if os.path.exists(raw_path):
            try:
                with open(raw_path, encoding="utf-8") as f:
                    data = json.load(f)
                stats["days_with_data"] += 1
                for source in ("reddit", "hatena", "zenn", "hackernews", "note"):
                    count = len(data.get(source, []))
                    stats["by_source"][source] += count
                    stats["total_posts"] += count
            except (json.JSONDecodeError, OSError):
                pass
        current += timedelta(days=1)

    return stats


def _count_issues_by_label(label_prefix: str) -> Counter:
    """Issue をラベルプレフィックスで集計する."""
    import subprocess

    counter: Counter = Counter()
    try:
        result = subprocess.run(
            [
                "gh", "issue", "list",
                "--label", "pain-report",
                "--state", "all",
                "--json", "labels",
                "--limit", "500",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            issues = json.loads(result.stdout)
            for issue in issues:
                for label in issue.get("labels", []):
                    name = label.get("name", "")
                    if name.startswith(label_prefix) or (not label_prefix and name not in ("pain-report",)):
                        counter[name] += 1
    except Exception:
        pass
    return counter


def generate_report(target_date: date) -> str:
    """月次レポートを生成する."""
    if target_date.day == 1:
        last_month = (target_date - timedelta(days=1))
        month_label = last_month.strftime("%Y-%m")
    else:
        month_label = target_date.strftime("%Y-%m")

    pains = _load_month_pains(target_date)
    stats = _load_month_raw_data(target_date)

    lines = [
        f"# Monthly Report: {month_label}\n",
        f"## サマリー\n",
        f"- 収集日数: {stats['days_with_data']} 日",
        f"- 収集投稿数: {stats['total_posts']} 件",
        f"- 抽出ペイン数: {len(pains)} 件\n",
    ]

    # ソース別収集数
    lines.append("## ソース別収集数\n")
    lines.append("| ソース | 件数 |")
    lines.append("|--------|------|")
    for source, count in stats["by_source"].most_common():
        lines.append(f"| {source} | {count} |")
    lines.append("")

    # カテゴリ別推移
    cat_counter: Counter = Counter()
    for p in pains:
        cat_counter[p.get("category", "その他")] += 1

    if cat_counter:
        lines.append("## カテゴリ別ペイン分布\n")
        lines.append("| カテゴリ | 件数 | 割合 |")
        lines.append("|----------|------|------|")
        total = sum(cat_counter.values())
        for cat, count in cat_counter.most_common():
            pct = count / total * 100 if total else 0
            bar = "█" * round(pct / 5) + "░" * (20 - round(pct / 5))
            lines.append(f"| {cat} | {count} | {bar} {pct:.0f}% |")
        lines.append("")

    # 市場シグナル分布
    signal_counter = _count_issues_by_label("🟢")
    signal_counter += _count_issues_by_label("🟡")

    if signal_counter:
        lines.append("## 市場シグナル分布\n")
        for signal, count in signal_counter.most_common():
            lines.append(f"- {signal}: {count} 件")
        lines.append("")

    # Top 10 ペイン（出現頻度）
    pain_counter: Counter = Counter()
    for p in pains:
        pain_counter[p["pain"]] += 1

    if pain_counter:
        lines.append("## Top 10 ペイン\n")
        lines.append("| # | ペイン | 出現数 |")
        lines.append("|---|--------|--------|")
        for i, (pain, count) in enumerate(pain_counter.most_common(10), 1):
            lines.append(f"| {i} | {pain[:60]} | {count} |")
        lines.append("")

    return "\n".join(lines)


def run(target_date: date) -> None:
    """月次レポートを生成して保存する."""
    report = generate_report(target_date)

    if target_date.day == 1:
        last_month = (target_date - timedelta(days=1))
        month_label = last_month.strftime("%Y-%m")
    else:
        month_label = target_date.strftime("%Y-%m")

    output_dir = os.path.join(BASE_DIR, "monthly")
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, f"{month_label}.md")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(report)

    logger.info(f"レポートを保存: {output_path}")
