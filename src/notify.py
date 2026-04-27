"""GitHub Issues でペインを個別 Issue として作成する（重複チェック付き）."""

import datetime
import json
import logging
import os
import subprocess

from sklearn.metrics.pairwise import cosine_similarity

logger = logging.getLogger(__name__)

from src.tokenizer import create_tfidf_vectorizer

PRODUCT_TYPE_LABELS = {
    "モバイルアプリ": "📱モバイルアプリ",
    "Webサービス": "🌐Webサービス",
    "ブラウザ拡張": "🧩ブラウザ拡張",
    "CLI・開発ツール": "⌨️CLI・開発ツール",
    "API・SaaS": "☁️API・SaaS",
}

WTP_LABELS = {
    "high": "💰high",
    "medium": "💰medium",
    "low": "💰low",
    "free": "💰free",
}

DUPLICATE_THRESHOLD_HIGH = 0.7  # 確実に重複
DUPLICATE_THRESHOLD_LOW = 0.4   # グレーゾーン（LLM で二次判定）

# rejected (NOT_PLANNED / rejected label) issue をどこまで遡るか
REJECTED_LOOKBACK_DAYS = 180
REJECTED_FETCH_LIMIT = 500
SKIPPED_PAINS_PATH = "raw/skipped_pains.jsonl"
DEDUP_METRICS_PATH = "data/dedup_metrics.json"


def _fetch_open_issues() -> list[dict]:
    """open 状態の Issue タイトル一覧を取得する."""
    try:
        result = subprocess.run(
            [
                "gh", "issue", "list",
                "--label", "pain-report",
                "--state", "open",
                "--json", "number,title",
                "--limit", "200",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            return json.loads(result.stdout)
    except Exception:
        pass
    return []


def _filter_rejected_issues(issues: list[dict]) -> list[dict]:
    """closed Issue リストから「再起票 NG」扱いするものを抽出する.

    判定条件:
    - closedAt が直近 REJECTED_LOOKBACK_DAYS 日以内
    - stateReason == "NOT_PLANNED" または rejected ラベル付き
    """
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(
        days=REJECTED_LOOKBACK_DAYS
    )
    rejected: list[dict] = []
    for iss in issues:
        closed_at_str = iss.get("closedAt")
        if not closed_at_str:
            continue
        try:
            closed_at = datetime.datetime.fromisoformat(
                closed_at_str.replace("Z", "+00:00")
            )
        except (ValueError, AttributeError):
            continue
        if closed_at < cutoff:
            continue
        state_reason = iss.get("stateReason", "")
        labels = [
            (lb.get("name", "") if isinstance(lb, dict) else lb)
            for lb in iss.get("labels", []) or []
        ]
        if state_reason == "NOT_PLANNED" or "rejected" in labels:
            rejected.append(iss)
    return rejected


def _fetch_rejected_issues() -> list[dict]:
    """closed (NOT_PLANNED) または rejected ラベル付きの pain-report Issue を返す."""
    try:
        result = subprocess.run(
            [
                "gh", "issue", "list",
                "--label", "pain-report",
                "--state", "closed",
                "--json", "number,title,closedAt,stateReason,labels",
                "--limit", str(REJECTED_FETCH_LIMIT),
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            return []
        issues = json.loads(result.stdout)
    except Exception:
        return []
    return _filter_rejected_issues(issues)


def _record_skipped_pain(
    pain: dict,
    matched_issue: dict,
    date_str: str,
    path: str | None = None,
) -> None:
    """rejected match でスキップしたペインを jsonl に記録する."""
    target_path = path or SKIPPED_PAINS_PATH
    record = {
        "date": date_str,
        "pain": pain.get("pain", ""),
        "matched_issue_number": matched_issue.get("number"),
        "matched_issue_title": matched_issue.get("title", ""),
        "source_url": pain.get("source_url", ""),
        "source_title": pain.get("source_title", ""),
    }
    try:
        parent = os.path.dirname(target_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(target_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        logger.info(
            f"スキップ記録: #{matched_issue.get('number')} と類似 → {target_path}"
        )
    except Exception as e:
        logger.warning(f"スキップ記録失敗: {e}")


def _record_dedup_metrics(
    date_str: str,
    stats: dict,
    path: str | None = None,
) -> None:
    """日次の dedup 集計（open/rejected match 件数 + 新規起票件数）を記録する.

    既存の data/dedup_metrics.json を読み込み、date_str をキーに上書きする。
    1 日複数回実行された場合は最後の呼び出しの値で更新される。
    """
    target_path = path or DEDUP_METRICS_PATH
    try:
        if os.path.exists(target_path):
            with open(target_path, encoding="utf-8") as f:
                data = json.load(f)
                if not isinstance(data, dict):
                    data = {}
        else:
            data = {}
    except Exception:
        data = {}

    data[date_str] = {
        "open_match": int(stats.get("open_match", 0)),
        "rejected_match": int(stats.get("rejected_match", 0)),
        "new_issues": int(stats.get("new_issues", 0)),
    }

    try:
        parent = os.path.dirname(target_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(target_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
        logger.info(
            f"dedup metrics 記録: {date_str} → {data[date_str]} ({target_path})"
        )
    except Exception as e:
        logger.warning(f"dedup metrics 記録失敗: {e}")


def _llm_judge_duplicate(pain_text: str, existing_title: str) -> bool:
    """LLM でグレーゾーンの重複を二次判定する."""
    import os

    prompt = (
        "以下の2つのペインが実質的に同じ課題を指しているか判定してください。\n"
        "同じ課題なら YES、異なる課題なら NO とだけ答えてください。\n\n"
        f"ペイン A: {pain_text}\n"
        f"ペイン B: {existing_title}\n"
    )

    token = os.environ.get("GITHUB_TOKEN", "")
    if token:
        try:
            from openai import OpenAI

            client = OpenAI(
                base_url="https://models.github.ai/inference",
                api_key=token,
            )
            response = client.chat.completions.create(
                model="openai/gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
                max_tokens=10,
            )
            answer = (response.choices[0].message.content or "").strip().upper()
            return answer.startswith("YES")
        except Exception as e:
            logger.warning(f"LLM 二次判定失敗: {e}")
    return False


def _find_duplicate(pain_text: str, existing_issues: list[dict]) -> dict | None:
    """既存 Issue の中から重複を検出する（2 段階判定）.

    1. TF-IDF cosine similarity >= 0.7 → 確実に重複
    2. 0.4 <= similarity < 0.7 → LLM で二次判定
    """
    if not existing_issues:
        return None

    titles = [issue["title"] for issue in existing_issues]
    corpus = titles + [pain_text]

    try:
        tfidf = create_tfidf_vectorizer().fit_transform(corpus)
        sims = cosine_similarity(tfidf[-1:], tfidf[:-1]).flatten()

        max_idx = sims.argmax()
        max_sim = sims[max_idx]

        if max_sim >= DUPLICATE_THRESHOLD_HIGH:
            return existing_issues[max_idx]

        if max_sim >= DUPLICATE_THRESHOLD_LOW:
            logger.info(f"グレーゾーン (sim={max_sim:.2f}) → LLM 二次判定")
            if _llm_judge_duplicate(pain_text, titles[max_idx]):
                return existing_issues[max_idx]
    except ValueError:
        pass

    return None


def send_top_pains(pains: list[dict], date_str: str, top_n: int = 3) -> dict:
    """深刻度が高いペイン TOP N を個別の GitHub Issue として作成する.

    重複判定は open Issue + 直近 REJECTED_LOOKBACK_DAYS 日に rejected (NOT_PLANNED
    または rejected ラベル) で close された Issue の両方を対象に行う。
    rejected match した場合は新規起票せず raw/skipped_pains.jsonl に記録のみ残す。

    戻り値: {"open_match": int, "rejected_match": int, "new_issues": int}
    """
    stats = {"open_match": 0, "rejected_match": 0, "new_issues": 0}
    if not pains:
        return stats

    open_issues = _fetch_open_issues()
    rejected_issues = _fetch_rejected_issues()
    logger.info(
        f"既存 open Issue: {len(open_issues)} 件 / rejected Issue: {len(rejected_issues)} 件"
    )

    combined: list[dict] = []
    for iss in open_issues:
        combined.append({**iss, "_match_kind": "open"})
    for iss in rejected_issues:
        combined.append({**iss, "_match_kind": "rejected"})

    sorted_pains = sorted(pains, key=lambda x: x.get("severity", 0), reverse=True)
    top = sorted_pains[:top_n]

    for pain in top:
        pain_text = pain.get("pain", "")
        duplicate = _find_duplicate(pain_text, combined)

        if duplicate is None:
            issue = _create_issue(pain, date_str)
            if issue:
                combined.append({**issue, "_match_kind": "open"})
                stats["new_issues"] += 1
            continue

        kind = duplicate.get("_match_kind", "open")
        if kind == "rejected":
            logger.info(
                f"再起票スキップ: #{duplicate['number']} (rejected) "
                f"{duplicate['title'][:50]}"
            )
            _record_skipped_pain(pain, duplicate, date_str)
            stats["rejected_match"] += 1
        else:
            logger.info(
                f"重複検出 → #{duplicate['number']} {duplicate['title'][:50]}"
            )
            _comment_duplicate(duplicate["number"], pain, date_str)
            stats["open_match"] += 1

    _record_dedup_metrics(date_str, stats)

    if stats["rejected_match"] > 0:
        try:
            from . import discord_notify
            discord_notify.notify_dedup_summary(stats, date_str)
        except Exception as e:
            logger.warning(f"Discord dedup サマリー通知失敗: {e}")

    return stats


def _comment_duplicate(issue_number: int, pain: dict, date_str: str) -> None:
    """既存 Issue に重複ペインの情報をコメントとして追加する."""
    pain_text = pain.get("pain", "")
    source_title = pain.get("source_title", "")
    source_url = pain.get("source_url", "")

    comment = f"📅 {date_str} に同様のペインを再検出:\n\n> {pain_text}\n"
    if source_url:
        comment += f"\nソース: [{source_title}]({source_url})"

    try:
        subprocess.run(
            ["gh", "issue", "comment", str(issue_number), "--body", comment],
            capture_output=True,
            text=True,
            timeout=30,
        )
        logger.info(f"#{issue_number} にコメント追加")
    except Exception as e:
        logger.warning(f"コメント追加失敗: {e}")


def _create_issue(pain: dict, date_str: str) -> dict | None:
    """1 件のペインから GitHub Issue を作成する. 成功時は {number, title} を返す."""
    severity = pain.get("severity", 0)
    stars = "★" * severity + "☆" * (5 - severity)
    category = pain.get("category", "")
    pain_text = pain.get("pain", "")
    product_type = pain.get("product_type", "")
    target_user = pain.get("target_user", "")
    wtp = pain.get("willingness_to_pay", "")
    frequency = pain.get("frequency", "")
    existing = pain.get("existing_solutions")
    idea = pain.get("app_idea", "")
    source_title = pain.get("source_title", "")
    source_url = pain.get("source_url", "")

    # Issue 本文
    lines = [
        f"## ペイン\n",
        f"{pain_text}\n",
        f"## 詳細\n",
        f"| 項目 | 値 |",
        f"|---|---|",
        f"| 深刻度 | {stars} ({severity}/5) |",
        f"| 対象ユーザー | {target_user} |",
        f"| 頻度 | {frequency} |",
        f"| 課金意欲 | {wtp} |",
        f"| プロダクト | {product_type} |",
        "",
        f"## アイデア\n",
        f"{idea}\n",
        f"## 既存ソリューション\n",
    ]

    if existing:
        lines.append(f"{existing}\n")
    else:
        lines.append("なし（チャンス！）\n")

    # 市場データ
    market_signal = pain.get("market_signal")
    market_apps = pain.get("market_apps", [])
    if market_signal:
        signal_label = {
            "whitespace": "🟢 ホワイトスペース（競合なし）",
            "underserved": "🟡 市場あり・満足度低い（チャンス）",
            "emerging": "🟡 新興市場",
            "competitive": "🔴 競合が強い",
        }.get(market_signal, market_signal)
        lines.append(f"## 市場シグナル\n")
        lines.append(f"{signal_label}\n")
        if market_apps:
            for app in market_apps[:3]:
                lines.append(
                    f"- [{app['name']}]({app['url']}) "
                    f"⭐{app['rating']} ({app['reviews']}件) {app['price']}"
                )
            lines.append("")

    # エンゲージメント情報
    engagement = pain.get("source_engagement", {})
    if engagement:
        engagement_parts = []
        label_map = {
            "score": "👍 スコア",
            "num_comments": "💬 コメント",
            "bookmarks": "🔖 ブックマーク",
            "view_count": "👀 閲覧",
            "answer_count": "✅ 回答",
        }
        for key, label in label_map.items():
            if key in engagement:
                engagement_parts.append(f"{label}: {engagement[key]}")
        if engagement_parts:
            lines.append(f"## エンゲージメント\n")
            lines.append(" / ".join(engagement_parts) + "\n")

    if source_url:
        lines.append(f"## ソース\n")
        lines.append(f"[{source_title}]({source_url})\n")

    lines.append(f"---\n📅 {date_str}\n")
    from . import gh_client
    lines.append(gh_client.HELP_BLOCK)

    body = "\n".join(lines)
    title = f"[{category}] {pain_text[:80]}"

    # ラベルを組み立て
    labels = ["pain-report"]

    if category:
        labels.append(category)

    pt_label = PRODUCT_TYPE_LABELS.get(product_type)
    if pt_label:
        labels.append(pt_label)

    wtp_label = WTP_LABELS.get(wtp)
    if wtp_label:
        labels.append(wtp_label)

    if severity >= 3:
        labels.append(f"🔥severity-{severity}")

    if not existing:
        labels.append("🎯既存なし")

    if market_signal == "whitespace":
        labels.append("🟢whitespace")
    elif market_signal == "underserved":
        labels.append("🟡underserved")

    # gh issue create
    cmd = [
        "gh", "issue", "create",
        "--title", title,
        "--body", body,
    ]
    for label in labels:
        cmd.extend(["--label", label])

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

        if result.returncode == 0:
            issue_url = result.stdout.strip()
            logger.info(f"Issue 作成: {issue_url}")

            # Issue 番号を抽出
            issue_number = int(issue_url.rstrip("/").split("/")[-1])

            # Project に自動追加 (GraphQL API)
            _add_to_project(issue_url, issue_number)

            # スコアリング
            try:
                from . import scoring
                scoring.score_and_update_issue(pain, issue_number)
            except Exception as e:
                logger.warning(f"スコアリング失敗（続行）: {e}")

            # Discord 通知
            try:
                from . import discord_notify
                discord_notify.notify_issue_created(pain, issue_number, issue_url)
            except Exception as e:
                logger.warning(f"Discord 通知失敗（続行）: {e}")

            return {"number": issue_number, "title": title}
        else:
            logger.error(f"Issue 作成失敗: {result.stderr[:200]}")
    except Exception as e:
        logger.error(f"Issue 作成失敗: {e}")

    return None


# Project V2 ID (kaionn/projects/1)
_PROJECT_ID = "PVT_kwHOBZbkF84BR2G2"


def _add_to_project(issue_url: str, issue_number: int) -> None:
    """GraphQL API で Issue を Project に追加する。"""
    import json

    # Issue の node ID を取得
    node_result = subprocess.run(
        [
            "gh", "api", "graphql",
            "-f", f'query=query {{ resource(url: "{issue_url}") {{ ... on Issue {{ id }} }} }}',
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if node_result.returncode != 0:
        logger.warning(f"Issue node ID 取得失敗: {node_result.stderr[:200]}")
        return

    try:
        node_id = json.loads(node_result.stdout)["data"]["resource"]["id"]
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        logger.warning(f"Issue node ID パース失敗: {e}")
        return

    # Project に追加
    add_result = subprocess.run(
        [
            "gh", "api", "graphql",
            "-f", f'query=mutation {{ addProjectV2ItemById(input: {{projectId: "{_PROJECT_ID}", contentId: "{node_id}"}}) {{ item {{ id }} }} }}',
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if add_result.returncode == 0:
        logger.info(f"Project に追加: #{issue_number}")
    else:
        logger.warning(f"Project 追加失敗: {add_result.stderr[:200]}")
