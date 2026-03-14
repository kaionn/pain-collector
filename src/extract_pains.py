"""GitHub Models (GPT-4o-mini) でペイン抽出・構造化する."""

import json
import os

from openai import OpenAI

SYSTEM_PROMPT = """\
あなたはユーザーの日常的な不満や困りごと（ペイン）を抽出するアナリストです。

与えられた SNS 投稿やブックマークエントリから、アプリやサービスのアイデアの種になりそうな
「小さなペイン」を抽出してください。

以下の JSON 配列形式で出力してください（Markdown のコードブロックは不要）:

[
  {
    "pain": "ペインの要約（1-2文）",
    "category": "仕事 | 生活 | 移動 | コミュニケーション | 健康 | 学習 | お金 | その他",
    "product_type": "モバイルアプリ | Webサービス | ブラウザ拡張 | CLI・開発ツール | ハードウェア・IoT | API・SaaS | その他",
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

ルール:
- ペインが見つからない投稿はスキップする
- 1つの投稿から複数のペインを抽出してもよい
- 具体的で actionable なペインを優先する
- 抽象的すぎる不満（「人生がつらい」等）はスキップする
"""


def extract(posts: list[dict]) -> list[dict]:
    """投稿リストからペインを抽出する."""
    if not posts:
        print("[LLM] 投稿が0件のためスキップ")
        return []

    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        print("[LLM] GITHUB_TOKEN が未設定、スキップ")
        return []

    client = OpenAI(
        base_url="https://models.github.ai/inference",
        api_key=token,
    )

    # バッチサイズごとに処理（トークン制限回避）
    batch_size = 20
    all_pains = []

    for i in range(0, len(posts), batch_size):
        batch = posts[i : i + batch_size]
        batch_text = _format_posts(batch)

        try:
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

            content = response.choices[0].message.content or "[]"
            # JSON 部分を抽出（コードブロック対応）
            content = content.strip()
            if content.startswith("```"):
                content = content.split("\n", 1)[1].rsplit("```", 1)[0]

            pains = json.loads(content)
            all_pains.extend(pains)
            print(f"[LLM] バッチ {i // batch_size + 1}: {len(pains)} 件のペインを抽出")

        except (json.JSONDecodeError, Exception) as e:
            print(f"[LLM] バッチ {i // batch_size + 1} の処理に失敗: {e}")
            continue

    print(f"[LLM] 合計: {len(all_pains)} 件のペインを抽出")
    return all_pains


def _format_posts(posts: list[dict]) -> str:
    """投稿リストをテキスト形式にフォーマットする."""
    lines = []
    for p in posts:
        source = p.get("source", "unknown")
        title = p.get("title", "")
        url = p.get("url", "")
        body = p.get("body", p.get("summary", ""))

        lines.append(f"---\n[{source}] {title}\nURL: {url}\n{body}\n")

    return "\n".join(lines)
