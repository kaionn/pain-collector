"""高ポテンシャルなペインに対してディープダイブレポートを自動生成する.

market_signal が "whitespace" または "underserved" かつ深刻度 4 以上の
ペインを対象に、競合分析・ペルソナ・MVP 仕様・GTM 戦略を含む詳細レポートを
Markdown で生成して deep_dive/ ディレクトリに保存する。

API コストを抑えるため、1日あたり最大 1 件のみ処理する。
"""

import os
import re
import subprocess

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DEEP_DIVE_PROMPT = """\
あなたはプロダクト戦略アナリストです。
以下のユーザーペイン（課題）に対して、個人開発者が MVP を作るための詳細な分析レポートを
Markdown 形式で作成してください。

## 出力する Markdown のセクション構成（必ずこの順序・見出しで出力）

### 競合ランドスケープ分析

主要な競合プロダクトを 3〜5 件挙げ、各プロダクトの強み・弱み・価格帯を表形式でまとめてください。
競合が存在しない場合はその理由と市場の空白を説明してください。

### ターゲットユーザーペルソナ

以下の項目を含む詳細なペルソナを 1〜2 名記述してください。
- 名前・年齢・職業
- 1日の過ごし方とこのペインに直面する具体的なシーン
- 技術リテラシー・デバイス環境
- 現在の対処法とその不満点
- このプロダクトに期待すること

### MVP 仕様

個人開発者が 2 週間で実装できるスコープを以下の形式で記述してください。

**必須機能（Week 1）**
- 機能リスト（箇条書き）

**追加機能（Week 2）**
- 機能リスト（箇条書き）

**推奨技術スタック**
- フロントエンド:
- バックエンド:
- データストア:
- インフラ/デプロイ:

**2 週間開発スケジュール**
Day 1〜14 の具体的なタスクをリストアップしてください。

### Go-to-Market 戦略

**初期獲得チャネル（Launch 直後）**
最初の 100 ユーザーを獲得するための具体的なアクションを 3〜5 個挙げてください。

**価格モデル**
推奨する価格設定と根拠を記述してください（無料プラン・有料プランの構成も含む）。

**差別化ポイント**
既存ソリューションとの明確な違いと、なぜユーザーがこのプロダクトを選ぶかを説明してください。

---

出力は上記 4 つのセクションのみとし、前置きや後書きは不要です。
Markdown のコードブロック（```）で全体を囲まないでください。
"""


def should_deep_dive(pain: dict) -> bool:
    """深刻度と市場シグナルからディープダイブ対象か判定する.

    Args:
        pain: ペインデータの辞書。market_signal と severity キーを参照する。

    Returns:
        market_signal が "whitespace" または "underserved" かつ
        severity が 4 以上の場合に True。
    """
    signal = pain.get("market_signal", "")
    severity = pain.get("severity", 0)
    return signal in ("whitespace", "underserved") and severity >= 4


def _make_slug(text: str) -> str:
    """ペインテキストをファイル名に使えるスラグに変換する.

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


def _call_llm(system_prompt: str, user_prompt: str) -> str:
    """LLM を呼び出してテキストを生成する.

    GitHub Actions 環境では GITHUB_TOKEN を使って GitHub Models (GPT-4o-mini) を呼び出す。
    ローカル環境では Claude Code CLI にフォールバックする。

    Args:
        system_prompt: システムプロンプト。
        user_prompt: ユーザープロンプト（分析対象のペイン情報）。

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


def run(pains: list[dict], date_str: str) -> None:
    """高ポテンシャルなペインのディープダイブレポートを生成して保存する.

    should_deep_dive() でフィルタリングし、severity × wtp_score で
    スコアリングして上位 1 件のみレポートを生成する。
    生成したレポートは deep_dive/{date_str}-{slug}.md に保存する。

    Args:
        pains: market_check.enrich_pains() で処理済みのペインリスト。
        date_str: レポートの日付文字列（例: "2026-03-18"）。
    """
    wtp_score: dict[str, int] = {"high": 4, "medium": 3, "low": 2, "free": 1}

    # フィルタリング
    candidates = [p for p in pains if should_deep_dive(p)]

    if not candidates:
        print("[DeepDive] 対象となるペインがありません（market_signal=whitespace/underserved かつ severity>=4 の条件を満たすペインなし）")
        return

    # スコアリング: severity × wtp_score で降順ソートして上位 1 件を取得
    candidates.sort(
        key=lambda p: p.get("severity", 0) * wtp_score.get(p.get("willingness_to_pay", "free"), 1),
        reverse=True,
    )
    target = candidates[0]

    pain_text = target.get("pain", "")
    category = target.get("category", "その他")
    severity = target.get("severity", 0)
    wtp = target.get("willingness_to_pay", "free")
    signal = target.get("market_signal", "")
    target_user = target.get("target_user", "")
    app_idea = target.get("app_idea", "")
    existing = target.get("existing_solutions") or "なし"
    market_apps = target.get("market_apps", [])

    print(f"[DeepDive] 対象ペイン: {pain_text}")
    print(f"[DeepDive] 深刻度: {severity}/5 / 市場シグナル: {signal}")

    # 競合アプリ情報をテキスト化
    market_apps_text = ""
    if market_apps:
        app_lines = "\n".join(
            f"  - {a['name']}: ★{a['rating']} ({a['reviews']}件レビュー) {a['price']}"
            for a in market_apps
        )
        market_apps_text = f"\n既存 App Store 競合:\n{app_lines}"

    user_prompt = f"""\
## 分析対象のペイン

- **ペイン**: {pain_text}
- **カテゴリ**: {category}
- **深刻度**: {severity}/5
- **課金意欲**: {wtp}
- **市場シグナル**: {signal}
- **ターゲットユーザー**: {target_user}
- **アプリアイデア**: {app_idea}
- **既存ソリューション**: {existing}{market_apps_text}

上記のペインに対して、詳細なディープダイブレポートを作成してください。
"""

    print("[DeepDive] LLM でレポート生成中...")
    try:
        llm_content = _call_llm(DEEP_DIVE_PROMPT, user_prompt)
    except Exception as e:
        print(f"[DeepDive] LLM 呼び出しに失敗しました: {e}")
        return

    # ヘッダー + LLM 生成コンテンツを結合
    signal_label = {
        "whitespace": "🟢 ホワイトスペース（競合なし）",
        "underserved": "🟡 市場あり・満足度低い（チャンス）",
        "emerging": "🟡 新興市場",
        "competitive": "🔴 競合が強い",
    }.get(signal, signal)

    report = f"""# Deep Dive: {pain_text}

| 項目 | 値 |
|---|---|
| カテゴリ | {category} |
| 深刻度 | {severity}/5 |
| 課金意欲 | {wtp} |
| 市場シグナル | {signal_label} |
| 対象ユーザー | {target_user} |

---

{llm_content}
"""

    # ファイル保存
    slug = _make_slug(pain_text)
    output_dir = os.path.join(BASE_DIR, "deep_dive")
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, f"{date_str}-{slug}.md")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(report)

    print(f"[DeepDive] レポートを保存しました: {output_path}")
