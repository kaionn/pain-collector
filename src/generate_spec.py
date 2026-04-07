"""Deep Dive レポートから技術 Spec（実装計画）を自動生成する."""

import logging
import os
import re
import subprocess

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SPEC_PROMPT = """\
あなたはシニアソフトウェアアーキテクトです。
以下の Deep Dive レポートを入力として、個人開発者が即座に実装を開始できる
技術 Spec を Markdown 形式で生成してください。

## 出力する Markdown のセクション構成（必ずこの順序・見出しで出力）

### 要件定義
- R1. {ユーザーストーリー形式: 「〜として、〜したい、なぜなら〜」}
- R2. ...（5-8 件）

### 技術スタック
Deep Dive の推奨スタックを具体化:
- フロントエンド:
- バックエンド:
- DB:
- インフラ/デプロイ:

### データモデル
主要エンティティとリレーションをテーブル形式で記述:
| エンティティ | 主要フィールド | リレーション |

### API エンドポイント
| メソッド | パス | 説明 |
|----------|------|------|

### 画面一覧
| パス | 画面名 | 主要コンポーネント |
|------|--------|-------------------|

### MVP スコープ（Week 1-2）
チェックボックス形式のタスクリスト:
- [ ] Day 1-2: ...
- [ ] Day 3-4: ...
- ...

### 成功指標
- KPI 1: {指標名} - {目標値}
- KPI 2: ...

---

出力は上記セクションのみ。前置きや後書きは不要。
Markdown のコードブロック（```）で全体を囲まないでください。
"""


def _call_llm(system_prompt: str, user_prompt: str) -> str:
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
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.3,
        )
        return response.choices[0].message.content or ""

    combined = f"{system_prompt}\n\n{user_prompt}"
    result = subprocess.run(
        ["claude", "-p", combined, "--output-format", "text"],
        capture_output=True,
        text=True,
        timeout=180,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr[:200])
    return result.stdout.strip()


def _make_slug(text: str) -> str:
    """テキストをファイル名用スラグに変換する."""
    truncated = text[:30]
    slug = re.sub(r"[^\w\u3000-\u9fff\u30a0-\u30ff\u3040-\u309f]", "-", truncated)
    slug = re.sub(r"-{2,}", "-", slug)
    return slug.strip("-")


def generate_spec_from_deep_dive(deep_dive_path: str) -> str | None:
    """Deep Dive レポートから技術 Spec を生成して保存する."""
    if not os.path.exists(deep_dive_path):
        logger.warning(f"Deep Dive ファイルが見つかりません: {deep_dive_path}")
        return None

    with open(deep_dive_path, encoding="utf-8") as f:
        deep_dive_content = f.read()

    # タイトルを抽出
    title_match = re.search(r"^# Deep Dive: (.+)$", deep_dive_content, re.MULTILINE)
    title = title_match.group(1) if title_match else "Unknown"

    logger.info(f"Spec 生成: {title}")

    user_prompt = f"以下の Deep Dive レポートから技術 Spec を生成してください:\n\n{deep_dive_content}"

    try:
        spec_content = _call_llm(SPEC_PROMPT, user_prompt)
    except Exception as e:
        logger.error(f"Spec 生成失敗: {e}")
        return None

    # ファイル名を Deep Dive と同じ命名規則で生成
    basename = os.path.basename(deep_dive_path).replace(".md", "")
    spec_dir = os.path.join(BASE_DIR, "specs")
    os.makedirs(spec_dir, exist_ok=True)
    spec_path = os.path.join(spec_dir, f"{basename}-spec.md")

    report = f"# Technical Spec: {title}\n\n{spec_content}"

    with open(spec_path, "w", encoding="utf-8") as f:
        f.write(report)

    logger.info(f"Spec を保存: {spec_path}")
    return spec_path


def generate_spec_from_issue(issue_number: int, title: str, body: str) -> str | None:
    """Issue のタイトル/本文から直接 Spec を生成して保存する.

    Deep Dive レポートが無い Issue に対して、軽量な Spec を生成するための fallback。
    """
    logger.info(f"Spec 生成 (Issue #{issue_number}): {title}")

    user_prompt = (
        f"以下のペイン Issue から技術 Spec を生成してください。\n\n"
        f"# Issue #{issue_number}: {title}\n\n{body}"
    )

    try:
        spec_content = _call_llm(SPEC_PROMPT, user_prompt)
    except Exception as e:
        logger.error(f"Spec 生成失敗: {e}")
        return None

    spec_dir = os.path.join(BASE_DIR, "specs")
    os.makedirs(spec_dir, exist_ok=True)
    spec_path = os.path.join(spec_dir, f"issue-{issue_number}-spec.md")

    report = f"# Technical Spec: {title}\n\n_Source: Issue #{issue_number}_\n\n{spec_content}"

    with open(spec_path, "w", encoding="utf-8") as f:
        f.write(report)

    logger.info(f"Spec を保存: {spec_path}")
    return spec_path


def run_for_latest(date_str: str) -> None:
    """指定日の Deep Dive レポートから Spec を生成する."""
    deep_dive_dir = os.path.join(BASE_DIR, "deep_dive")
    if not os.path.isdir(deep_dive_dir):
        logger.info("Deep Dive ディレクトリが存在しません")
        return

    # 指定日のレポートを検索
    target_files = [
        f for f in os.listdir(deep_dive_dir)
        if f.startswith(date_str) and f.endswith(".md")
    ]

    if not target_files:
        logger.info(f"{date_str} の Deep Dive レポートがありません")
        return

    for fname in target_files:
        deep_dive_path = os.path.join(deep_dive_dir, fname)
        spec_path = os.path.join(BASE_DIR, "specs", fname.replace(".md", "-spec.md"))

        if os.path.exists(spec_path):
            logger.info(f"Spec 既存: {spec_path}")
            continue

        generate_spec_from_deep_dive(deep_dive_path)
