"""カテゴリ横断分析: カテゴリ成長率、新興テーマ検出、ソース別品質分析."""

import json
import logging
import os
from collections import Counter
from datetime import date, timedelta

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_pains_for_period(start: date, end: date) -> list[dict]:
    """指定期間の daily/*.md からペインを収集する."""
    pains = []
    current = start
    while current <= end:
        daily_path = os.path.join(BASE_DIR, "daily", f"{current.isoformat()}.md")
        if os.path.exists(daily_path):
            try:
                with open(daily_path, encoding="utf-8") as f:
                    current_category = ""
                    for line in f:
                        if line.startswith("## "):
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


def _load_raw_stats_for_period(start: date, end: date) -> dict[str, Counter]:
    """指定期間の raw データからソース別統計を集計する."""
    source_stats: dict[str, Counter] = {}
    current = start
    while current <= end:
        raw_path = os.path.join(BASE_DIR, "raw", f"{current.isoformat()}.json")
        if os.path.exists(raw_path):
            try:
                with open(raw_path, encoding="utf-8") as f:
                    data = json.load(f)
                for source in ("reddit", "hatena", "zenn", "hackernews", "note"):
                    if source not in source_stats:
                        source_stats[source] = Counter()
                    source_stats[source]["posts"] += len(data.get(source, []))
            except (json.JSONDecodeError, OSError):
                pass
        current += timedelta(days=1)
    return source_stats


def analyze(target_date: date) -> str:
    """カテゴリ横断分析レポートを生成する."""
    # 今月と先月のデータを比較
    this_month_start = target_date.replace(day=1)
    last_month_end = this_month_start - timedelta(days=1)
    last_month_start = last_month_end.replace(day=1)

    current_pains = _load_pains_for_period(this_month_start, target_date)
    previous_pains = _load_pains_for_period(last_month_start, last_month_end)

    current_cats = Counter(p.get("category", "その他") for p in current_pains)
    previous_cats = Counter(p.get("category", "その他") for p in previous_pains)

    lines = [
        f"# カテゴリ横断分析: {target_date.isoformat()}\n",
    ]

    # カテゴリ成長率
    lines.append("## カテゴリ成長率（前月比）\n")
    lines.append("| カテゴリ | 今月 | 先月 | 成長率 |")
    lines.append("|----------|------|------|--------|")

    all_cats = set(list(current_cats.keys()) + list(previous_cats.keys()))
    growth_data = []
    for cat in sorted(all_cats):
        curr = current_cats.get(cat, 0)
        prev = previous_cats.get(cat, 0)
        if prev > 0:
            growth = (curr - prev) / prev * 100
        elif curr > 0:
            growth = 100.0
        else:
            growth = 0.0
        growth_data.append((cat, curr, prev, growth))

    growth_data.sort(key=lambda x: x[3], reverse=True)
    for cat, curr, prev, growth in growth_data:
        arrow = "📈" if growth > 20 else "📉" if growth < -20 else "➡️"
        lines.append(f"| {cat} | {curr} | {prev} | {arrow} {growth:+.0f}% |")
    lines.append("")

    # 新興テーマ検出（今月のみに出現するカテゴリ）
    new_cats = set(current_cats.keys()) - set(previous_cats.keys())
    if new_cats:
        lines.append("## 新興テーマ\n")
        for cat in new_cats:
            lines.append(f"- {cat}: {current_cats[cat]} 件（先月は 0 件）")
        lines.append("")

    # ソース別品質分析
    current_source_stats = _load_raw_stats_for_period(this_month_start, target_date)
    if current_source_stats:
        lines.append("## ソース別収集量\n")
        lines.append("| ソース | 投稿数 |")
        lines.append("|--------|--------|")
        for source in sorted(current_source_stats.keys()):
            posts = current_source_stats[source]["posts"]
            lines.append(f"| {source} | {posts} |")
        lines.append("")

    return "\n".join(lines)


def run(target_date: date) -> None:
    """カテゴリ横断分析を実行して保存する."""
    report = analyze(target_date)

    output_dir = os.path.join(BASE_DIR, "monthly")
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, f"{target_date.strftime('%Y-%m')}-cross-analysis.md")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(report)

    logger.info(f"レポートを保存: {output_path}")
