"""競合プロダクトの詳細ティアダウンレポートを自動生成する.

market_check で取得した market_apps を持つペインを対象に、
各競合を UX・機能・パフォーマンス・価格・サポート・コミュニティの
6 軸で 1〜5 点評価した詳細レポートを competitive/ ディレクトリに保存する。
"""

import logging
import os
import re
import subprocess

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

TEARDOWN_PROMPT = """\
あなたはプロダクト競合アナリストです。
以下のユーザーペインと既存競合アプリの情報を入力として、
詳細な競合ティアダウン（teardown）レポートを Markdown 形式で作成してください。

## スコアリング基準

各競合を以下の 6 軸で 1〜5 点で評価してください:
- **UX**: ユーザーインターフェースとユーザー体験の質
- **Features**: 機能の充実度と差別化
- **Performance**: アプリの速度・安定性
- **Pricing**: 価格設定のユーザーフレンドリー度
- **Support**: サポートの質と応答速度
- **Community**: コミュニティの活発さとエコシステム

## 出力する Markdown のセクション構成（必ずこの順序・見出しで出力）

### スコア比較表

| 競合名 | UX | Features | Performance | Pricing | Support | Community | 合計 |
|--------|-----|----------|-------------|---------|---------|-----------|------|
（各競合のスコアを記入）

### 各競合の詳細分析

各競合について以下を記述:
- **強み**: 優れている点を 2〜3 個
- **弱み**: 不足している点・ユーザーの不満を 2〜3 個
- **価格帯**: 具体的な価格プランと特徴
- **ターゲット層**: 主な利用者層

### 市場ギャップ分析

既存競合が満たせていない領域を特定し、新規参入の機会を説明してください。

### 推奨ポジショニング

新規プロダクトが差別化できるポジションを 1〜2 文で端的に提案してください。

---

出力は上記 4 つのセクションのみ。前置きや後書きは不要。
Markdown のコードブロック（```）で全体を囲まないでください。
"""


def _call_llm(system_prompt: str, user_prompt: str) -> str:
    """LLM を呼び出してテキストを生成する.

    GitHub Actions 環境では GITHUB_TOKEN を使って GitHub Models (GPT-4o-mini) を呼び出す。
    ローカル環境では Claude Code CLI にフォールバックする。

    Args:
        system_prompt: システムプロンプト。
        user_prompt: ユーザープロンプト（分析対象の競合情報）。

    Returns:
        LLM が生成したテキスト。

    Raises:
        RuntimeError: LLM の呼び出しに失敗した場合。
    """
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

    # ローカル: Claude Code CLI にフォールバック
    combined_prompt = f"{system_prompt}\n\n{user_prompt}"
    result = subprocess.run(
        ["claude", "-p", combined_prompt, "--output-format", "text"],
        capture_output=True,
        text=True,
        timeout=180,
    )

    if result.returncode != 0:
        raise RuntimeError(result.stderr[:200])

    return result.stdout.strip()


def _make_slug(text: str) -> str:
    """テキストをファイル名用スラグに変換する.

    Args:
        text: スラグ化する元テキスト。

    Returns:
        先頭 30 文字を取り、英数字・日本語以外をハイフンに置換し
        前後のハイフンを除去した文字列。
    """
    truncated = text[:30]
    slug = re.sub(r"[^\w\u3000-\u9fff\u30a0-\u30ff\u3040-\u309f]", "-", truncated)
    slug = re.sub(r"-{2,}", "-", slug)
    return slug.strip("-")


def generate_teardown(pain: dict, date_str: str) -> str | None:
    """ペインの競合ティアダウンレポートを生成して保存する.

    market_apps が存在するペインを対象に、各競合の 6 軸スコアリングと
    市場ギャップ分析を含む詳細レポートを生成する。

    Args:
        pain: market_check.enrich_pains() で処理済みのペイン辞書。
              market_apps キーに競合アプリのリストが含まれることが前提。
        date_str: レポートの日付文字列（例: "2026-03-22"）。

    Returns:
        生成したレポートファイルのパス。失敗または対象外の場合は None。
    """
    pain_text = pain.get("pain", "")
    market_apps = pain.get("market_apps", [])

    if not market_apps:
        logger.info(f"市場データなし、スキップ: {pain_text[:40]}")
        return None

    slug = _make_slug(pain_text)
    competitive_dir = os.path.join(BASE_DIR, "competitive")
    os.makedirs(competitive_dir, exist_ok=True)

    output_path = os.path.join(competitive_dir, f"{date_str}-{slug}.md")
    if os.path.exists(output_path):
        logger.info(f"ティアダウンレポート既存: {output_path}")
        return output_path

    category = pain.get("category", "その他")
    severity = pain.get("severity", 0)
    wtp = pain.get("willingness_to_pay", "free")
    signal = pain.get("market_signal", "")

    # 競合アプリ情報をテキスト化
    app_lines = "\n".join(
        f"  - {a['name']}: ★{a.get('rating', 'N/A')} ({a.get('reviews', 0)}件レビュー) {a.get('price', '不明')}"
        for a in market_apps
    )

    # 競合弱点情報（あれば）
    competitor_pains_text = ""
    competitor_pains = pain.get("competitor_pains", [])
    if competitor_pains:
        cp_lines = "\n".join(
            f"  - [{cp.get('competitor_name', '')}] {cp.get('pain', '')}"
            for cp in competitor_pains
        )
        competitor_pains_text = f"\n\n競合アプリの低評価レビューから抽出した弱点:\n{cp_lines}"

    user_prompt = f"""\
## 分析対象のペインと競合情報

- **ペイン**: {pain_text}
- **カテゴリ**: {category}
- **深刻度**: {severity}/5
- **課金意欲**: {wtp}
- **市場シグナル**: {signal}

### 既存競合アプリ (App Store / Google Play):
{app_lines}{competitor_pains_text}

上記の情報を元に、詳細な競合ティアダウンレポートを作成してください。
"""

    logger.info(f"競合ティアダウン生成中: {pain_text[:40]}")

    try:
        llm_content = _call_llm(TEARDOWN_PROMPT, user_prompt)
    except Exception as e:
        logger.error(f"LLM 呼び出しに失敗しました: {e}")
        return None

    signal_label = {
        "whitespace": "🟢 ホワイトスペース（競合なし）",
        "underserved": "🟡 市場あり・満足度低い（チャンス）",
        "emerging": "🟡 新興市場",
        "competitive": "🔴 競合が強い",
    }.get(signal, signal)

    report = f"""# Competitive Teardown: {pain_text}

| 項目 | 値 |
|---|---|
| カテゴリ | {category} |
| 深刻度 | {severity}/5 |
| 課金意欲 | {wtp} |
| 市場シグナル | {signal_label} |
| 分析対象競合数 | {len(market_apps)} 件 |

---

{llm_content}
"""

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(report)

    logger.info(f"ティアダウンレポートを保存: {output_path}")
    return output_path
