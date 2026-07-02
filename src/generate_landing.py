"""Deep Dive レポートまたは Spec から単一ページの HTML ランディングページを生成する.

LLM が Hero セクション・機能紹介・価格・ウェイトリストフォーム（mailto: リンク）を
含む HTML を生成して landing/ ディレクトリに保存する。
"""

import logging
import os
import re

from src import llm_client

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

LANDING_PROMPT = """\
あなたはプロダクトデザイナーとコピーライターを兼ねた専門家です。
以下の Deep Dive レポートまたは技術 Spec を入力として、
単一ページの HTML ランディングページを生成してください。

## 要件

- 完全な HTML ファイル（DOCTYPE から </html> まで）を出力すること
- インラインスタイル（<style> タグ）で見栄え良く仕上げること
- 外部 CSS ライブラリは使用しない（純粋な HTML + CSS のみ）
- レスポンシブデザイン（モバイル対応）
- 日本語コンテンツ

## 必須セクション（この順序で実装）

### 1. Hero セクション
- プロダクト名（キャッチーなネーミング）
- キャッチコピー（ペインを解決することを端的に表現、20 文字以内）
- サブコピー（具体的な価値提案、40〜60 文字）
- CTA ボタン（ウェイトリスト登録へのアンカーリンク）
- グラデーション背景またはモダンなビジュアル

### 2. 課題セクション
- ユーザーが現在直面している 3 つの具体的な課題
- 共感を呼ぶ文体で記述

### 3. 機能セクション
- 主要機能を 3〜4 個
- 各機能に絵文字アイコン・タイトル・説明文（30〜50 文字）

### 4. 価格セクション
- フリープランと有料プランの 2 プラン構成
- 各プランの主な機能リスト
- 有料プランの推奨バッジ

### 5. ウェイトリストフォーム（id="waitlist"）
- メールアドレス入力フィールド（type="email"）
- 「登録する」ボタン（action は `mailto:waitlist@example.com` に設定）
- 登録後のベネフィット（先行アクセス・早期割引など）

### 6. フッター
- プロダクト名とコピーライト

## スタイルガイドライン

- フォント: システムフォント（-apple-system, sans-serif）
- カラー: モダンなグラデーション（例: #667eea → #764ba2）
- 余白: 十分な padding/margin でスッキリとした印象
- ボタン: 角丸・シャドウ付きでクリッカブルに見せる

---

出力は完全な HTML コードのみ。前置きや後書き、コードブロック（```）は不要。
"""


def _call_llm(system_prompt: str, user_prompt: str) -> str:
    """LLM を呼び出して HTML を生成する.

    GitHub Actions 環境では GITHUB_TOKEN を使って GitHub Models (GPT-4o-mini) を呼び出す。
    ローカル環境では Claude Code CLI にフォールバックする。

    Args:
        system_prompt: システムプロンプト。
        user_prompt: ユーザープロンプト（Deep Dive または Spec の内容）。

    Returns:
        LLM が生成した HTML テキスト。

    Raises:
        RuntimeError: LLM の呼び出しに失敗した場合。
    """
    return llm_client.chat(user_prompt, system=system_prompt, temperature=0.5)


def _extract_html(raw: str) -> str:
    """LLM 出力からコードブロックを除去して HTML を取り出す.

    Args:
        raw: LLM の生出力。

    Returns:
        クリーンアップされた HTML 文字列。
    """
    # ```html ... ``` ブロックを除去
    html_match = re.search(r"```(?:html)?\s*(<!DOCTYPE[\s\S]+?)</?\s*```", raw, re.IGNORECASE)
    if html_match:
        return html_match.group(1).strip()

    # DOCTYPE から始まる場合はそのまま返す
    doctype_match = re.search(r"(<!DOCTYPE[\s\S]+)", raw, re.IGNORECASE)
    if doctype_match:
        return doctype_match.group(1).strip()

    return raw.strip()


def generate_landing(deep_dive_path: str) -> str | None:
    """Deep Dive レポートまたは Spec からランディングページ HTML を生成して保存する.

    Args:
        deep_dive_path: 入力となる Deep Dive レポートまたは Spec ファイルのパス。

    Returns:
        生成した HTML ファイルのパス。失敗した場合は None。
    """
    if not os.path.exists(deep_dive_path):
        logger.warning(f"入力ファイルが見つかりません: {deep_dive_path}")
        return None

    with open(deep_dive_path, encoding="utf-8") as f:
        content = f.read()

    # ファイル名から日付とスラグを取得
    basename = os.path.basename(deep_dive_path)
    name_without_ext = re.sub(r"\.(md|html)$", "", basename)

    # 日付プレフィックスを取得
    date_match = re.match(r"^(\d{4}-\d{2}-\d{2})-(.+)$", name_without_ext)
    if date_match:
        date_str = date_match.group(1)
        slug_part = date_match.group(2)
    else:
        date_str = "unknown"
        slug_part = name_without_ext[:30]

    # spec / deep-dive サフィックスを除去
    slug = re.sub(r"-(spec|deep-dive)$", "", slug_part)

    landing_dir = os.path.join(BASE_DIR, "landing")
    os.makedirs(landing_dir, exist_ok=True)

    output_path = os.path.join(landing_dir, f"{date_str}-{slug}.html")
    if os.path.exists(output_path):
        logger.info(f"ランディングページ既存: {output_path}")
        return output_path

    # タイトルを取得（Deep Dive か Spec かを自動判定）
    title_match = re.search(r"^# (?:Deep Dive|Technical Spec): (.+)$", content, re.MULTILINE)
    title = title_match.group(1) if title_match else slug_part.replace("-", " ")

    logger.info(f"ランディングページ生成中: {title}")

    user_prompt = f"以下のレポートを元にランディングページを生成してください:\n\n{content}"

    try:
        raw_html = _call_llm(LANDING_PROMPT, user_prompt)
    except Exception as e:
        logger.error(f"LLM 呼び出しに失敗しました: {e}")
        return None

    html_content = _extract_html(raw_html)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    logger.info(f"ランディングページを保存: {output_path}")
    return output_path
