"""スコア上位の Todo Issue から MVP 候補を選定し picks/ に保存する.

選定後、各 Issue に通知コメントを投稿し pipeline_state.json を更新する。
Spec / Deep Dive が未生成の候補に対しては自動生成を試みる。
"""

import json
import logging
import os
import re
import subprocess
from datetime import datetime, timezone, timedelta

from sklearn.metrics.pairwise import cosine_similarity

from .tokenizer import create_tfidf_vectorizer

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JST = timezone(timedelta(hours=9))
PIPELINE_STATE_PATH = os.path.join(BASE_DIR, "data", "pipeline_state.json")

PICK_PROMPT = """\
あなたはプロダクト戦略アドバイザーです。

以下は個人開発の MVP 候補としてスコアが高いペイン（課題）のリストです。
これらを分析し、今すぐ着手すべきトップ 3 を選定してください。

各候補について **必ず以下の JSON 形式** で出力してください（Markdown 不要）:

```json
[
  {
    "number": <Issue番号>,
    "reason": "<なぜこれを選んだか（1-2文）>",
    "mvp_scope": ["<機能1>", "<機能2>", "<機能3>"],
    "dev_period": "<想定開発期間>",
    "acquisition": "<最初のユーザー獲得方法>"
  }
]
```

JSON のみを出力してください。前置きや後書きは不要です。
"""


def _load_pipeline_state() -> dict:
    """pipeline_state.json を読み込む."""
    if not os.path.exists(PIPELINE_STATE_PATH):
        return {}
    try:
        with open(PIPELINE_STATE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save_pipeline_state(state: dict) -> None:
    """pipeline_state.json を保存する."""
    os.makedirs(os.path.dirname(PIPELINE_STATE_PATH), exist_ok=True)
    with open(PIPELINE_STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def _load_past_picks() -> set[int]:
    """pipeline_state.json から過去の選定済み Issue 番号を取得する.

    pipeline_state.json が存在しない場合は picks/ ディレクトリから
    正規表現で Issue 番号を抽出するフォールバックを使用する。
    """
    state = _load_pipeline_state()
    if state.get("picked"):
        return {item["issue_number"] for item in state["picked"]}

    # フォールバック: picks/ ディレクトリから抽出
    picks_dir = os.path.join(BASE_DIR, "picks")
    picked: set[int] = set()
    if not os.path.isdir(picks_dir):
        return picked
    for fname in os.listdir(picks_dir):
        if not fname.endswith(".md"):
            continue
        try:
            with open(os.path.join(picks_dir, fname), encoding="utf-8") as f:
                for line in f:
                    for match in re.findall(r"#(\d+)", line):
                        picked.add(int(match))
        except OSError:
            continue
    return picked


def _load_deep_dive_titles() -> dict[str, str]:
    """deep_dive/ ディレクトリからファイル名とタイトルの対応を取得する.

    Returns:
        {タイトル: ファイルパス} の辞書
    """
    dd_dir = os.path.join(BASE_DIR, "deep_dive")
    titles: dict[str, str] = {}
    if not os.path.isdir(dd_dir):
        return titles
    for fname in os.listdir(dd_dir):
        if not fname.endswith(".md"):
            continue
        fpath = os.path.join(dd_dir, fname)
        try:
            with open(fpath, encoding="utf-8") as f:
                for line in f:
                    m = re.match(r"^# Deep Dive: (.+)$", line)
                    if m:
                        titles[m.group(1).strip()] = fpath
                        break
        except OSError:
            continue
    return titles


def _find_related_files(issue_number: int, issue_title: str) -> dict:
    """Issue に紐づく Deep Dive と Spec ファイルを検索する.

    1. pipeline_state.json に記録があればそこから取得
    2. なければ TF-IDF cosine similarity でタイトルマッチング
    """
    # 1. pipeline_state.json から検索
    state = _load_pipeline_state()
    for item in state.get("picked", []):
        if item["issue_number"] == issue_number:
            dd = item.get("deep_dive")
            spec = item.get("spec")
            if dd or spec:
                status = "spec-ready" if spec else ("analyzed" if dd else "idea")
                return {"deep_dive": dd, "spec": spec, "status": status}

    # 2. TF-IDF でタイトルマッチング
    dd_titles = _load_deep_dive_titles()
    if not dd_titles:
        return {"deep_dive": None, "spec": None, "status": "idea"}

    try:
        corpus = list(dd_titles.keys()) + [issue_title]
        tfidf = create_tfidf_vectorizer().fit_transform(corpus)
        sims = cosine_similarity(tfidf[-1:], tfidf[:-1]).flatten()
        max_idx = int(sims.argmax())
        max_sim = float(sims[max_idx])

        if max_sim >= 0.3:
            dd_title = list(dd_titles.keys())[max_idx]
            dd_path = dd_titles[dd_title]
            logger.info(f"Issue #{issue_number} ↔ Deep Dive マッチ (類似度 {max_sim:.2f}): {dd_title}")

            # 対応する Spec を検索
            basename = os.path.basename(dd_path).replace(".md", "")
            spec_path = os.path.join(BASE_DIR, "specs", f"{basename}-spec.md")
            spec = spec_path if os.path.exists(spec_path) else None

            status = "spec-ready" if spec else "analyzed"
            return {"deep_dive": dd_path, "spec": spec, "status": status}
    except ValueError:
        pass

    return {"deep_dive": None, "spec": None, "status": "idea"}


def _ensure_spec_exists(issue: dict) -> str | None:
    """Spec が存在しなければ生成する.

    Returns:
        生成した（または既存の）Spec ファイルパス。失敗時は None。
    """
    if issue.get("spec"):
        return issue["spec"]

    from . import generate_spec, deep_dive

    if issue.get("deep_dive"):
        logger.info(f"Issue #{issue['number']}: Deep Dive から Spec を生成中...")
        return generate_spec.generate_spec_from_deep_dive(
            issue["deep_dive"],
            issue_number=issue.get("number"),
            title=issue.get("title"),
        )

    # Deep Dive もない場合は生成をスキップ（pains データがないため）
    logger.info(f"Issue #{issue['number']}: Deep Dive が存在しないため Spec 生成をスキップ")
    return None


def _fetch_scored_issues() -> list[dict]:
    """スコアラベル付きの open Issue を取得する."""
    score_labels = ["🏆score-S", "🥇score-A", "🥈score-B"]
    all_issues: list[dict] = []

    for label in score_labels:
        try:
            result = subprocess.run(
                [
                    "gh", "issue", "list",
                    "--label", label,
                    "--state", "open",
                    "--json", "number,title,body,labels",
                    "--limit", "20",
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode == 0:
                issues = json.loads(result.stdout)
                for issue in issues:
                    issue["score_label"] = label
                all_issues.extend(issues)
        except Exception:
            continue

    return all_issues


def _call_llm(prompt: str) -> str:
    """LLM を呼び出す."""
    token = os.environ.get("GITHUB_TOKEN", "")

    if token:
        from openai import OpenAI

        client = OpenAI(
            base_url="https://models.github.ai/inference",
            api_key=token,
        )
        response = client.chat.completions.create(
            model="openai/gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
        )
        return response.choices[0].message.content or ""

    result = subprocess.run(
        ["claude", "-p", prompt, "--output-format", "text"],
        capture_output=True,
        text=True,
        timeout=180,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr[:200])
    return result.stdout.strip()


def _parse_llm_picks(content: str, candidates: list[dict]) -> list[dict]:
    """LLM の出力から選定結果を JSON としてパースする.

    JSON パースに失敗した場合は候補の上位 3 件をフォールバックとして返す。
    """
    # ```json ... ``` ブロックを抽出
    json_match = re.search(r"```json\s*(.*?)\s*```", content, re.DOTALL)
    text = json_match.group(1) if json_match else content

    # JSON 配列を探す
    bracket_match = re.search(r"\[.*\]", text, re.DOTALL)
    if bracket_match:
        try:
            picks = json.loads(bracket_match.group(0))
            if isinstance(picks, list) and picks:
                return picks
        except json.JSONDecodeError:
            pass

    logger.warning("LLM 出力の JSON パースに失敗。上位 3 件をフォールバック選定")
    return [
        {
            "number": c["number"],
            "reason": "スコア上位のため自動選定",
            "mvp_scope": [],
            "dev_period": "不明",
            "acquisition": "不明",
        }
        for c in candidates[:3]
    ]


def _generate_report(picked: list[dict], total_candidates: int, today: str) -> str:
    """選定レポートの Markdown を生成する."""
    rank_emoji = ["🥇", "🥈", "🥉"]
    lines = [
        f"# MVP 候補選定: {today}\n",
        f"候補数: {total_candidates} 件 → 選定: {len(picked)} 件\n",
    ]

    for i, item in enumerate(picked):
        emoji = rank_emoji[i] if i < len(rank_emoji) else f"{i + 1}."
        number = item["number"]
        title = item.get("title", "")
        score_label = item.get("score_label", "")
        reason = item.get("reason", "")
        mvp_scope = item.get("mvp_scope", [])
        dev_period = item.get("dev_period", "")
        acquisition = item.get("acquisition", "")

        dd = item.get("deep_dive")
        spec = item.get("spec")
        status = item.get("status", "idea")

        dd_mark = f"✅ {os.path.basename(dd)}" if dd else "❌ 未生成"
        spec_mark = f"✅ {os.path.basename(spec)}" if spec else "❌ 未生成"

        lines.append(f"## {emoji} #{number} {title}\n")
        lines.append(f"- スコア: {score_label}")
        lines.append(f"- Deep Dive: {dd_mark}")
        lines.append(f"- Spec: {spec_mark}")
        lines.append(f"- ステータス: {status}")
        lines.append(f"- 選定理由: {reason}")

        if mvp_scope:
            lines.append("- MVP スコープ:")
            for feat in mvp_scope:
                lines.append(f"  - {feat}")

        lines.append(f"- 想定開発期間: {dev_period}")
        lines.append(f"- ユーザー獲得: {acquisition}")
        lines.append("")

    lines.append("---")
    lines.append("👉 承認するには、対象 Issue に `/approve` とコメントしてください。")
    lines.append("")

    return "\n".join(lines)


def _notify_picked_issues(picked: list[dict], today: str) -> None:
    """選定された各 Issue にコメントを投稿する."""
    rank_labels = ["🥇", "🥈", "🥉"]

    for i, item in enumerate(picked):
        number = item["number"]
        rank = rank_labels[i] if i < len(rank_labels) else f"#{i + 1}"
        spec = item.get("spec")
        spec_status = "✅ Spec 生成済み" if spec else "⚠️ Spec 未生成"

        comment = (
            f"## {rank} MVP 候補に選定されました\n\n"
            f"選定日: {today}\n"
            f"選定レポート: picks/{today}.md\n"
            f"{spec_status}\n\n"
            f"**次のステップ:**\n"
            f"- Spec が生成済み → `/approve` とコメントすると自動実装が開始されます\n"
            f"- Spec が未生成 → Deep Dive 完了後に自動生成されます\n\n"
            f"選定理由:\n{item.get('reason', '')}\n"
        )

        try:
            subprocess.run(
                ["gh", "issue", "comment", str(number), "--body", comment],
                capture_output=True,
                text=True,
                timeout=30,
            )
            logger.info(f"Issue #{number} に通知コメントを投稿")
        except Exception as e:
            logger.warning(f"Issue #{number} へのコメント投稿失敗: {e}")


def _update_pipeline_state(picked: list[dict], today: str) -> None:
    """pipeline_state.json に選定結果を追記する."""
    state = _load_pipeline_state()
    state.setdefault("picked", [])

    for item in picked:
        state["picked"].append({
            "issue_number": item["number"],
            "picked_at": datetime.now(JST).isoformat(),
            "spec": item.get("spec"),
            "deep_dive": item.get("deep_dive"),
            "product_name": None,
            "status": "awaiting_approval",
        })

    _save_pipeline_state(state)
    logger.info(f"pipeline_state.json を更新（{len(picked)} 件追加）")


def run() -> None:
    """MVP 候補を選定してレポートを保存する."""
    issues = _fetch_scored_issues()

    if not issues:
        logger.info("スコア付き Issue がありません")
        return

    # スコア順にソート（S > A > B）
    score_order = {"🏆score-S": 0, "🥇score-A": 1, "🥈score-B": 2}
    issues.sort(key=lambda x: score_order.get(x.get("score_label", ""), 3))

    # 過去の選定済み Issue を除外
    past_picks = _load_past_picks()
    issues = [i for i in issues if i["number"] not in past_picks]

    if not issues:
        logger.info("未選定のスコア付き Issue がありません")
        return

    # 上位 10 件を LLM に渡す
    top = issues[:10]
    issue_texts = []
    for issue in top:
        title = issue["title"]
        body = issue.get("body", "")
        label = issue.get("score_label", "")
        issue_texts.append(f"### #{issue['number']} {title}\nスコア: {label}\n{body}\n")

    combined = "\n".join(issue_texts)
    prompt = f"{PICK_PROMPT}\n\n--- 候補一覧 ---\n\n{combined}"

    logger.info(f"{len(top)} 件の候補を分析中...")

    try:
        content = _call_llm(prompt)
    except Exception as e:
        logger.error(f"LLM 呼び出し失敗: {e}")
        return

    # LLM 出力をパース
    llm_picks = _parse_llm_picks(content, top)

    today = datetime.now(JST).date().isoformat()

    # 選定結果に関連ファイル情報を付与
    issue_map = {i["number"]: i for i in top}
    picked: list[dict] = []

    for pick in llm_picks[:3]:
        number = pick["number"]
        issue = issue_map.get(number, {})
        title = issue.get("title", "")

        # Deep Dive / Spec の紐付け
        related = _find_related_files(number, title)

        entry = {
            "number": number,
            "title": title,
            "score_label": issue.get("score_label", ""),
            "reason": pick.get("reason", ""),
            "mvp_scope": pick.get("mvp_scope", []),
            "dev_period": pick.get("dev_period", ""),
            "acquisition": pick.get("acquisition", ""),
            "deep_dive": related["deep_dive"],
            "spec": related["spec"],
            "status": related["status"],
        }

        # Spec が未生成なら自動生成を試みる
        if not entry["spec"] and entry["deep_dive"]:
            generated_spec = _ensure_spec_exists(entry)
            if generated_spec:
                entry["spec"] = generated_spec
                entry["status"] = "spec-ready"

        picked.append(entry)

    # レポート生成・保存
    report = _generate_report(picked, len(top), today)
    output_dir = os.path.join(BASE_DIR, "picks")
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, f"{today}.md")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(report)
    logger.info(f"レポートを保存: {output_path}")

    # pipeline_state.json 更新
    _update_pipeline_state(picked, today)

    # 各 Issue に通知コメント投稿
    _notify_picked_issues(picked, today)

    # Discord 通知
    try:
        from . import discord_notify
        repo_url = "https://github.com/kaionn/pain-collector"
        discord_notify.notify_mvp_picked(picked, today, repo_url)
    except Exception as e:
        logger.warning(f"Discord 通知失敗（続行）: {e}")
