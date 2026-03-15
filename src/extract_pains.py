"""LLM でペイン抽出・構造化する.

- GitHub Actions: GitHub Models (GPT-4o-mini)
- ローカル: Claude Code CLI
"""

import json
import os
import subprocess
from collections.abc import Callable

BATCH_SIZE = 20

SYSTEM_PROMPT = """\
あなたはユーザーの日常的な不満や困りごと（ペイン）を抽出するアナリストです。

与えられた SNS 投稿やブックマークエントリから、アプリやサービスのアイデアの種になりそうな
「小さなペイン」を抽出してください。

各投稿には Engagement（スコア、コメント数、ブックマーク数）が付与されています。
エンゲージメントが高い投稿のペインは、より多くの人が共感している可能性が高いため重視してください。

以下の JSON 配列形式で出力してください（Markdown のコードブロックは不要）:

[
  {
    "pain": "ペインの要約（1-2文）",
    "category": "子育て・育児 | 食事・料理 | お金・家計 | 仕事・キャリア | 人間関係 | 健康・体調 | 住まい・暮らし | 移動・通勤 | 学習・スキル | テクノロジー | 生き方・価値観 | 趣味・娯楽 | その他",
    "product_type": "モバイルアプリ | Webサービス | ブラウザ拡張 | CLI・開発ツール | ハードウェア・IoT | API・SaaS | その他",
    "target_user": "このペインを抱えている人のペルソナ（例: 子育て中の共働き夫婦、フリーランスエンジニア、大学生）",
    "frequency": "daily | weekly | monthly | one-time",
    "willingness_to_pay": "free | low | medium | high",
    "severity": 1-5の整数（5が最も深刻）,
    "existing_solutions": "既知の解決策があれば記載、なければ null",
    "app_idea": "このペインを解決するプロダクトのアイデア（1文）",
    "source_title": "元の投稿タイトル",
    "source_url": "元の投稿URL"
  }
]

product_type の判断基準:
- モバイルアプリ: 外出先・移動中に使う、カメラ/GPS/通知が重要
- Webサービス: ブラウザで完結、データ管理・ダッシュボード系
- ブラウザ拡張: 既存Webサイトの体験を改善・拡張
- CLI・開発ツール: 開発者向け、ターミナルやエディタで使う
- ハードウェア・IoT: 物理デバイスやセンサーが必要
- API・SaaS: 他サービスに組み込む、B2B向け
- その他: 上記に当てはまらない

willingness_to_pay の判断基準:
- free: 無料でしか使わない層（学生、カジュアルユーザー）
- low: 数百円/月なら払う（個人の便利ツール）
- medium: 数千円/月でも払う（業務効率化、専門ツール）
- high: 数万円/月でも払う（企業向け、業務に不可欠）

ルール:
- ペインが見つからない投稿はスキップする
- 1つの投稿から複数のペインを抽出してもよい
- 具体的で actionable なペインを優先する
- 抽象的すぎる不満（「人生がつらい」等）はスキップする
- 宣伝投稿（"I built", "check out my app", 自作アプリの紹介）はスキップする
- 単なるエピソード（面白い話、バズったネタ、ニュース報道）はスキップする
- 解決策が自明すぎるもの（「ググればわかる」レベル）はスキップする
- JSON 配列のみを出力する。説明文やコードブロック記法は不要
"""


def extract(posts: list[dict]) -> list[dict]:
    """投稿リストからペインを抽出する."""
    if not posts:
        print("[LLM] 投稿が0件のためスキップ")
        return []

    token = os.environ.get("GITHUB_TOKEN", "")
    if token:
        return _extract_in_batches(posts, _call_github_models(token), "GitHub Models")
    else:
        return _extract_in_batches(posts, _call_claude, "Claude Code")


def _extract_in_batches(
    posts: list[dict],
    call_fn: Callable[[str], str],
    label: str,
) -> list[dict]:
    """バッチごとに LLM を呼び出してペインを抽出する共通ループ."""
    all_pains = []

    for i in range(0, len(posts), BATCH_SIZE):
        batch = posts[i : i + BATCH_SIZE]
        batch_text = _format_posts(batch)
        batch_num = i // BATCH_SIZE + 1

        try:
            content = call_fn(batch_text)
            pains = _parse_json_response(content)
            all_pains.extend(pains)
            print(f"[{label}] バッチ {batch_num}: {len(pains)} 件のペインを抽出")
        except Exception as e:
            print(f"[{label}] バッチ {batch_num} の処理に失敗: {e}")
            continue

    print(f"[{label}] 合計: {len(all_pains)} 件のペインを抽出")
    return all_pains


def _call_github_models(token: str) -> Callable[[str], str]:
    """GitHub Models API を呼び出すコールバックを返す."""
    from openai import OpenAI

    client = OpenAI(
        base_url="https://models.github.ai/inference",
        api_key=token,
    )

    def call(batch_text: str) -> str:
        response = client.chat.completions.create(
            model="openai/gpt-4o-mini",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": f"以下の投稿からペインを抽出してください:\n\n{batch_text}",
                },
            ],
            temperature=0.3,
        )
        return response.choices[0].message.content or "[]"

    return call


def _call_claude(batch_text: str) -> str:
    """Claude Code CLI を呼び出してペイン抽出する."""
    prompt = (
        f"{SYSTEM_PROMPT}\n\n"
        f"以下の投稿からペインを抽出してください:\n\n{batch_text}"
    )

    result = subprocess.run(
        ["claude", "-p", prompt, "--output-format", "text"],
        capture_output=True,
        text=True,
        timeout=180,
    )

    if result.returncode != 0:
        raise RuntimeError(result.stderr[:200])

    return result.stdout.strip()


def _parse_json_response(content: str) -> list[dict]:
    """LLM レスポンスから JSON 配列をパースする."""
    content = content.strip()
    # コードブロック除去
    if content.startswith("```"):
        content = content.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    # JSON 配列部分だけ抽出
    start = content.find("[")
    end = content.rfind("]")
    if start != -1 and end != -1:
        content = content[start : end + 1]
    return json.loads(content)


def _format_posts(posts: list[dict]) -> str:
    """投稿リストをテキスト形式にフォーマットする."""
    lines = []
    for p in posts:
        source = p.get("source", "unknown")
        title = p.get("title", "")
        url = p.get("url", "")
        body = p.get("body", p.get("summary", ""))

        # エンゲージメント情報
        engagement_parts = []
        if "score" in p:
            engagement_parts.append(f"score={p['score']}")
        if "num_comments" in p:
            engagement_parts.append(f"comments={p['num_comments']}")
        if "bookmarks" in p:
            engagement_parts.append(f"bookmarks={p['bookmarks']}")
        engagement = ", ".join(engagement_parts) if engagement_parts else "N/A"

        lines.append(
            f"---\n[{source}] {title}\n"
            f"URL: {url}\n"
            f"Engagement: {engagement}\n"
            f"{body}\n"
        )

    return "\n".join(lines)
