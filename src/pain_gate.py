"""Issue 化直前の actionability ゲート.

抽出 LLM のプロンプトに skip ルールがあるが恒常的にリークするため、
Issue 化直前（日次 top_n 件のみ）に二段目の専用 LLM 判定でフィルタする。
"""

import json
import logging

from src import llm_client

logger = logging.getLogger(__name__)

# rule_based_audience: developer 扱いする product_type
_DEVELOPER_PRODUCT_TYPES = {"CLI・開発ツール", "API・SaaS"}

GATE_PROMPT = """\
あなたは個人開発者が1〜2週間で作る新規MVPの種として、このペインが妥当かを判定します。

以下の4つの基準のいずれかに該当する場合は reject（actionable=false）としてください:

1. 特定の既存アプリ・サービスの不具合や運営へのクレーム
   （例: PayPayがログインできない、Slackのアップデートでデータ消失、メルペイが突然使えない）
   他社アプリ内部の問題は第三者の新規プロダクトで解決できません。
2. 社会問題・政策・制度レベルの課題
   （例: 地方公務員の採用難、経済格差、トイレの数の不均衡）
3. 技術サポートQ&A（特定環境の設定ミス・使い方の質問）
   （例: AWS LambdaでDB接続が切れる、Kubernetes APIにタイムアウトする）
   StackOverflow的な質問はプロダクト機会ではありません。
4. プロダクトで解決できない感情・状況
   （例: 自傷行為の悩み、家族関係の辛さ）
   メンタルヘルス等のセンシティブ領域は扱いません。

重要な区別: 開発者の反復的なワークフローのペイン
（例: 「毎回のリリースノート作成が面倒」）はツール機会なのでactionable=true、
audience="developer"としてください。一方、特定環境のトラブルシューティングは
基準3に該当しreject対象です。

audienceの定義:
- developer: エンジニア・開発チームが使うもの
- consumer: 一般生活者が使うもの

以下のJSON形式のみで出力してください（説明文は不要）:
{"actionable": true|false, "reject_reason": "reject時のみ、該当する基準を1文で", "audience": "developer"|"consumer"}
"""

_VALID_AUDIENCES = ("developer", "consumer")


def rule_based_audience(pain: dict) -> str:
    """product_type ベースの決定的 audience 判定.

    'CLI・開発ツール' / 'API・SaaS' は developer、それ以外は consumer とする。
    """
    product_type = pain.get("product_type", "")
    if product_type in _DEVELOPER_PRODUCT_TYPES:
        return "developer"
    return "consumer"


def classify(pain: dict) -> dict:
    """ペインの actionability と対象層を LLM で判定する.

    LLM 呼び出しやパースに失敗した場合は fail-open（actionable=True）とし、
    ゲート故障でパイプライン全体を止めない。
    """
    payload = {
        "pain": pain.get("pain", ""),
        "category": pain.get("category", ""),
        "product_type": pain.get("product_type", ""),
        "target_user": pain.get("target_user", ""),
        "app_idea": pain.get("app_idea", ""),
    }
    user_content = json.dumps(payload, ensure_ascii=False)

    try:
        response = llm_client.chat(user_content, system=GATE_PROMPT, temperature=0.0)
        verdict = llm_client.parse_json_object(response)

        actionable = bool(verdict.get("actionable", True))
        audience = verdict.get("audience")
        if audience not in _VALID_AUDIENCES:
            audience = rule_based_audience(pain)

        reject_reason = verdict.get("reject_reason") if not actionable else None

        return {"actionable": actionable, "reject_reason": reject_reason, "audience": audience}
    except Exception as e:
        logger.warning(f"actionability ゲート判定失敗（fail-open）: {e}")
        return {"actionable": True, "reject_reason": None, "audience": rule_based_audience(pain)}
