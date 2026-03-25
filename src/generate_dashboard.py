"""GitHub Pages ダッシュボード: Chart.js CDN の静的 HTML を生成する."""

import json
import logging
import os
import subprocess
from collections import Counter

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _collect_dashboard_data() -> dict:
    """ダッシュボード用のデータを収集する."""
    data = {
        "categories": {},
        "market_signals": {},
        "scores": {},
        "total_issues": 0,
        "open_issues": 0,
    }

    try:
        result = subprocess.run(
            [
                "gh", "issue", "list",
                "--label", "pain-report",
                "--state", "all",
                "--json", "number,title,labels,state,createdAt",
                "--limit", "500",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            return data

        issues = json.loads(result.stdout)
        data["total_issues"] = len(issues)

        cat_counter: Counter = Counter()
        signal_counter: Counter = Counter()
        score_counter: Counter = Counter()

        for issue in issues:
            if issue.get("state") == "OPEN":
                data["open_issues"] += 1

            for label in issue.get("labels", []):
                name = label.get("name", "")
                if name.startswith("🟢") or name.startswith("🟡"):
                    signal_counter[name] += 1
                elif name.startswith("🏆") or name.startswith("🥇") or name.startswith("🥈") or name.startswith("🥉"):
                    score_counter[name] += 1
                elif name not in ("pain-report",) and not name.startswith(("📱", "🌐", "🧩", "⌨️", "☁️", "💰", "🔥", "🎯", "stale")):
                    cat_counter[name] += 1

        data["categories"] = dict(cat_counter.most_common())
        data["market_signals"] = dict(signal_counter.most_common())
        data["scores"] = dict(score_counter.most_common())

    except Exception as e:
        logger.warning(f"データ収集失敗: {e}")

    return data


def _generate_html(data: dict) -> str:
    """Chart.js を使った静的 HTML を生成する."""
    cat_labels = json.dumps(list(data["categories"].keys()), ensure_ascii=False)
    cat_values = json.dumps(list(data["categories"].values()))
    signal_labels = json.dumps(list(data["market_signals"].keys()), ensure_ascii=False)
    signal_values = json.dumps(list(data["market_signals"].values()))
    score_labels = json.dumps(list(data["scores"].keys()), ensure_ascii=False)
    score_values = json.dumps(list(data["scores"].values()))

    return f"""\
<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Pain Collector Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<style>
  body {{ font-family: -apple-system, sans-serif; max-width: 1200px; margin: 0 auto; padding: 20px; background: #0d1117; color: #c9d1d9; }}
  h1 {{ color: #58a6ff; }}
  .stats {{ display: flex; gap: 20px; margin: 20px 0; }}
  .stat {{ background: #161b22; padding: 20px; border-radius: 8px; flex: 1; text-align: center; border: 1px solid #30363d; }}
  .stat-value {{ font-size: 2em; color: #58a6ff; }}
  .charts {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }}
  .chart-container {{ background: #161b22; padding: 20px; border-radius: 8px; border: 1px solid #30363d; }}
  canvas {{ max-height: 400px; }}
</style>
</head>
<body>
<h1>Pain Collector Dashboard</h1>

<div class="stats">
  <div class="stat">
    <div class="stat-value">{data['total_issues']}</div>
    <div>Total Issues</div>
  </div>
  <div class="stat">
    <div class="stat-value">{data['open_issues']}</div>
    <div>Open Issues</div>
  </div>
</div>

<div class="charts">
  <div class="chart-container">
    <h3>カテゴリ分布</h3>
    <canvas id="catChart"></canvas>
  </div>
  <div class="chart-container">
    <h3>市場シグナル</h3>
    <canvas id="signalChart"></canvas>
  </div>
  <div class="chart-container">
    <h3>スコア分布</h3>
    <canvas id="scoreChart"></canvas>
  </div>
</div>

<script>
const colors = ['#58a6ff','#3fb950','#d29922','#f85149','#bc8cff','#79c0ff','#56d364','#e3b341','#ff7b72','#d2a8ff'];

new Chart(document.getElementById('catChart'), {{
  type: 'doughnut',
  data: {{ labels: {cat_labels}, datasets: [{{ data: {cat_values}, backgroundColor: colors }}] }},
  options: {{ plugins: {{ legend: {{ labels: {{ color: '#c9d1d9' }} }} }} }}
}});

new Chart(document.getElementById('signalChart'), {{
  type: 'bar',
  data: {{ labels: {signal_labels}, datasets: [{{ label: '件数', data: {signal_values}, backgroundColor: ['#3fb950','#d29922','#f85149'] }}] }},
  options: {{ scales: {{ y: {{ ticks: {{ color: '#c9d1d9' }} }}, x: {{ ticks: {{ color: '#c9d1d9' }} }} }}, plugins: {{ legend: {{ display: false }} }} }}
}});

new Chart(document.getElementById('scoreChart'), {{
  type: 'bar',
  data: {{ labels: {score_labels}, datasets: [{{ label: '件数', data: {score_values}, backgroundColor: ['#d29922','#3fb950','#58a6ff','#8b949e'] }}] }},
  options: {{ scales: {{ y: {{ ticks: {{ color: '#c9d1d9' }} }}, x: {{ ticks: {{ color: '#c9d1d9' }} }} }}, plugins: {{ legend: {{ display: false }} }} }}
}});
</script>
</body>
</html>"""


def run() -> None:
    """ダッシュボードを生成して docs/ に保存する."""
    data = _collect_dashboard_data()

    # data.json
    docs_dir = os.path.join(BASE_DIR, "docs")
    os.makedirs(docs_dir, exist_ok=True)

    data_path = os.path.join(docs_dir, "data.json")
    with open(data_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    # index.html
    html = _generate_html(data)
    html_path = os.path.join(docs_dir, "index.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)

    logger.info(f"生成完了: {html_path}")
