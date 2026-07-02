"""LLM でペイン抽出・構造化する.

- GitHub Actions: GitHub Models (GPT-4o-mini)
- ローカル: Claude Code CLI
"""

import json
import logging
import os
from collections.abc import Callable

from src import llm_client

logger = logging.getLogger(__name__)

BATCH_SIZE = 20

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 生活相談系ソース。一般のペイン抽出プロンプトでは「料理の腕に自信がない」等の
# 抽象的な悩みが弾かれてしまうため、専用プロンプトで拾い直す。
LIFESTYLE_SOURCES = {"komachi", "mamastar", "girlschannel", "chiebukuro"}

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
    "category": "子育て・育児 | 食事・料理 | お金・家計 | 仕事・キャリア | 人間関係 | 健康・体調 | 住まい・暮らし | 移動・通勤 | 学習・スキル | テクノロジー | 生き方・価値観 | 趣味・娯楽 | その他（この中から必ず1つだけ選ぶこと。複数該当する場合は最も近い1つを選ぶ）",
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

収益シグナルの重視:
- 「お金を払ってでも解決したい」「課金してもいい」等の表現がある投稿は severity を高めに設定し willingness_to_pay を "high" にすること
- アプリレビュー（低評価）は既にお金を払ったユーザーの声であり revenue_potential が高いペインと判断すること
- 繰り返し発生する日常ペイン（daily frequency）はサブスク型収益に向いているため優先すること
- [MONETIZATION_SIGNAL] タグが付いた投稿は課金意欲が明示されているため willingness_to_pay を "high" に設定すること

ルール:
- ペインが見つからない投稿はスキップする
- 1つの投稿から複数のペインを抽出してもよい
- 具体的で actionable なペインを優先する
- 個人開発者が1〜2週間で MVP を作れるスケール感のペインを優先する
- 以下のような大きすぎるペインはスキップする:
  - プラットフォーム全体の問題（iOS のバグ、Google のポリシー変更等）
  - 法規制・政策レベルの問題（AI 規制、プライバシー法等）
  - 大企業しか解決できない問題（インフラ、ハードウェア製造等）
  - 社会構造的な問題（格差、教育制度等）
- 以下のようなニュース・時事ネタはスキップする:
  - 国際政治・外交・軍事・安全保障に関するニュース（戦争、領土問題、外交会談等）
  - 企業の不祥事・炎上・トラブル報道（高額請求問題、サービス障害報道等）
  - 犯罪・事件・裁判の報道（詐欺事件、訴訟ニュース等）
  - 政治的な意見・主張・政策議論
  - 自然災害・疫病に関するニュース
- 以下のような非 actionable な投稿はスキップする:
  - 抽象的すぎる不満（「人生がつらい」「料理の腕に自信がない」等）
  - エンタメ・カルチャーの感想や批評（映画、ゲーム、マンガ、本の感想）
  - 哲学的・思想的な議論
  - 個人の一回限りのトラブル体験談（飲食店のミス、配送トラブル等、プロダクトで解決できないもの）
- 宣伝投稿（"I built", "check out my app", 自作アプリの紹介）はスキップする
- 単なるエピソード（面白い話、バズったネタ、ニュース報道）はスキップする
- 解決策が自明すぎるもの（「ググればわかる」レベル）はスキップする
- JSON 配列のみを出力する。説明文やコードブロック記法は不要
"""

LIFESTYLE_SYSTEM_PROMPT = """\
あなたは家庭・育児・人間関係・お金・健康など、日常生活の困りごと（ペイン）を抽出する
ライフスタイル系アナリストです。投稿元は発言小町・ママスタ・ガールズちゃんねる・知恵袋など
一般生活者の相談・愚痴サイトです。

以下の点を強く意識してください:
- 投稿者の多くは非エンジニアです。テクノロジー系のペインに無理に変換しないでください。
- 生活シーンに根ざした「ちょっとした不便」も積極的に拾ってください
  （例: 子どもの送迎調整、夫婦の家計分担、義実家との連絡、献立決め、近所付き合い、推し活の管理）
- 抽象的に見えても、生活シーン+対象を具体化できるなら抽出してください
  （例: 「料理がしんどい」→「平日夜の献立決めに毎日 30 分悩んでいる」）
- 「テクノロジー」カテゴリは避け、できる限り 子育て・育児 / 食事・料理 / お金・家計 /
  人間関係 / 住まい・暮らし / 健康・体調 / 移動・通勤 / 仕事・キャリア / 趣味・娯楽 のいずれかに分類してください。
- product_type は「モバイルアプリ」「Webサービス」を優先し、「CLI・開発ツール」は基本選ばないでください。

出力形式・フィールドは標準プロンプトと同じです。以下の JSON 配列のみを返してください:

[
  {
    "pain": "ペインの要約（1-2文）",
    "category": "子育て・育児 | 食事・料理 | お金・家計 | 仕事・キャリア | 人間関係 | 健康・体調 | 住まい・暮らし | 移動・通勤 | 学習・スキル | 生き方・価値観 | 趣味・娯楽 | その他",
    "product_type": "モバイルアプリ | Webサービス | ブラウザ拡張 | API・SaaS | その他",
    "target_user": "ペルソナ",
    "frequency": "daily | weekly | monthly | one-time",
    "willingness_to_pay": "free | low | medium | high",
    "severity": 1-5の整数,
    "existing_solutions": "あれば記載、なければ null",
    "app_idea": "解決アイデア（1文）",
    "source_title": "元の投稿タイトル",
    "source_url": "元の投稿URL"
  }
]

ルール:
- 個人開発者が 1〜2 週間で MVP を作れるスケール感のペインを優先
- ニュース・時事ネタ・芸能ゴシップ・政治・事件報道はスキップ
- 単発の愚痴で再現性がない話題はスキップ
- 「離婚すべき？」「夫が嫌い」など対人感情のみで解決策が描けないものはスキップ
- ただし「義実家への連絡を毎週取らされて疲れる」など仕組みで軽減できるものは拾う
- 1 投稿から複数のペインを抽出してよい
- JSON 配列のみを出力する
"""


def _build_system_prompt(variant: str = "default") -> str:
    """フィードバックルールを反映した動的システムプロンプトを構築する."""
    if variant == "lifestyle":
        prompt = LIFESTYLE_SYSTEM_PROMPT
    else:
        prompt = SYSTEM_PROMPT

    rules_path = os.path.join(BASE_DIR, "feedback_rules.json")
    if not os.path.exists(rules_path):
        return prompt

    try:
        with open(rules_path, encoding="utf-8") as f:
            rules = json.load(f)
    except Exception:
        return prompt

    from src.feedback import get_active_patterns

    exclude_patterns = get_active_patterns(rules.get("exclude_patterns", []))
    priority_patterns = get_active_patterns(rules.get("priority_patterns", []))

    if exclude_patterns:
        prompt += "\n\n以下のパターンはフィードバックにより「ノイズ」と判定されたため、特に除外してください:\n"
        prompt += "\n".join(f"- {p}" for p in exclude_patterns)

    if priority_patterns:
        prompt += "\n\n以下のパターンはフィードバックにより「良い抽出」と評価されたため、優先してください:\n"
        prompt += "\n".join(f"- {p}" for p in priority_patterns)

    return prompt


def extract(posts: list[dict]) -> list[dict]:
    """投稿リストからペインを抽出する.

    生活相談系ソース（komachi/mamastar/girlschannel/chiebukuro）は
    ライフスタイル特化プロンプトで別バッチ処理し、テクノロジーへの偏りを抑える。
    """
    if not posts:
        logger.info("投稿が0件のためスキップ")
        return []

    base_label = "GitHub Models" if os.environ.get("GITHUB_TOKEN") else "Claude Code"

    lifestyle_posts = [p for p in posts if p.get("source") in LIFESTYLE_SOURCES]
    standard_posts = [p for p in posts if p.get("source") not in LIFESTYLE_SOURCES]

    pains: list[dict] = []

    if standard_posts:
        call_fn = _make_call_fn(variant="default")
        pains.extend(_extract_in_batches(standard_posts, call_fn, base_label))

    if lifestyle_posts:
        call_fn = _make_call_fn(variant="lifestyle")
        pains.extend(_extract_in_batches(lifestyle_posts, call_fn, f"{base_label}/lifestyle"))

    # 元投稿のエンゲージメント情報をペインに付与
    _attach_engagement(pains, posts)
    return pains


_SOURCE_LANGUAGE = {
    "reddit": "en",
    "hackernews": "en",
    "devto": "en",
    "stackoverflow": "en",
    "hatena": "ja",
    "zenn": "ja",
    "note": "ja",
    "chiebukuro": "ja",
    "girlschannel": "ja",
    "bluesky": "ja",
    "appstore": "ja",
    "googleplay": "ja",
    "komachi": "ja",
    "mamastar": "ja",
}


def _attach_engagement(pains: list[dict], posts: list[dict]) -> None:
    """元投稿のエンゲージメント情報と言語を付与する."""
    url_to_post = {p["url"]: p for p in posts if "url" in p}

    for pain in pains:
        source_url = pain.get("source_url", "")
        post = url_to_post.get(source_url)
        if not post:
            pain["source_engagement"] = {}
            pain["language"] = "ja"
            continue

        engagement = {}
        for key in ("score", "num_comments", "bookmarks", "view_count", "answer_count"):
            if key in post:
                engagement[key] = post[key]
        pain["source_engagement"] = engagement
        pain["language"] = _SOURCE_LANGUAGE.get(post.get("source", ""), "ja")


def _extract_in_batches(
    posts: list[dict],
    call_fn: Callable[[str], str],
    label: str,
) -> list[dict]:
    """バッチごとに LLM を呼び出してペインを抽出する共通ループ."""
    all_pains = []
    failed_posts: list[dict] = []
    retry_stats = {"total_retries": 0, "recovered": 0}

    for i in range(0, len(posts), BATCH_SIZE):
        batch = posts[i : i + BATCH_SIZE]
        batch_num = i // BATCH_SIZE + 1

        pains = _extract_batch_with_retry(
            batch, call_fn, label, f"バッチ {batch_num}", failed_posts, retry_stats,
        )
        all_pains.extend(pains)

    if retry_stats["total_retries"] > 0:
        logger.info(
            f"[{label}] リトライ統計: {retry_stats['total_retries']}回リトライ, "
            f"{retry_stats['recovered']}件復旧"
        )

    if failed_posts:
        _save_failed_posts(failed_posts)
        logger.warning(f"[{label}] {len(failed_posts)}件の投稿が最終的に失敗")

    logger.info(f"[{label}] 合計: {len(all_pains)} 件のペインを抽出")
    return all_pains


def _extract_batch_with_retry(
    batch: list[dict],
    call_fn: Callable[[str], str],
    label: str,
    batch_label: str,
    failed_posts: list[dict],
    retry_stats: dict,
) -> list[dict]:
    """バッチを処理し、失敗時は半分に分割してリトライする."""
    batch_text = _format_posts(batch)

    try:
        content = call_fn(batch_text)
        pains = _parse_json_response(content)
        logger.info(f"[{label}] {batch_label}: {len(pains)} 件のペインを抽出")
        return pains
    except Exception as e:
        logger.warning(f"[{label}] {batch_label} の処理に失敗 ({len(batch)}件): {e}")

    # 1件以下なら分割不可 → 最終失敗
    if len(batch) <= 1:
        failed_posts.extend(batch)
        return []

    # 半分に分割してリトライ
    mid = len(batch) // 2
    retry_stats["total_retries"] += 1
    logger.info(f"[{label}] {batch_label} を {mid}件 + {len(batch) - mid}件 に分割してリトライ")

    pains_a = _extract_batch_with_retry(
        batch[:mid], call_fn, label, f"{batch_label}a", failed_posts, retry_stats,
    )
    pains_b = _extract_batch_with_retry(
        batch[mid:], call_fn, label, f"{batch_label}b", failed_posts, retry_stats,
    )

    recovered = len(pains_a) + len(pains_b)
    retry_stats["recovered"] += recovered
    return pains_a + pains_b


def _save_failed_posts(posts: list[dict]) -> None:
    """最終的に失敗した投稿を保存する."""
    from datetime import datetime, timezone, timedelta

    jst = timezone(timedelta(hours=9))
    date_str = datetime.now(jst).date().isoformat()

    failed_dir = os.path.join(BASE_DIR, "raw", "failed")
    os.makedirs(failed_dir, exist_ok=True)

    path = os.path.join(failed_dir, f"{date_str}.json")

    # 既存ファイルがあればマージ
    existing = []
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                existing = json.load(f)
        except Exception:
            pass

    existing.extend(posts)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)

    logger.info(f"失敗投稿を保存: {path} ({len(posts)}件追加)")


def _make_call_fn(variant: str = "default") -> Callable[[str], str]:
    """LLM 呼び出しコールバックを返す（バックエンドは llm_client が自動選択）."""
    system_prompt = _build_system_prompt(variant)

    def call(batch_text: str) -> str:
        content = llm_client.chat(
            f"以下の投稿からペインを抽出してください:\n\n{batch_text}",
            system=system_prompt,
            temperature=0.3,
        )
        return content or "[]"

    return call


def _call_github_models(token: str, variant: str = "default") -> Callable[[str], str]:
    """LLM 呼び出しコールバックを返す（後方互換用エイリアス）.

    `token` はバックエンド選択に使わない。llm_client が呼び出し時点の
    `GITHUB_TOKEN` を見て自動判定するため、weekly_trends.py 等の既存の
    トークン有無チェックと結果が一致する。シグネチャのみ維持している。
    """
    return _make_call_fn(variant)


# 後方互換: weekly_trends 等は extract_pains._call_claude を関数として直接使う
def _call_claude(batch_text: str) -> str:
    """LLM 呼び出し（標準プロンプト・後方互換用）."""
    return _make_call_fn(variant="default")(batch_text)


def _call_claude_factory(variant: str = "default") -> Callable[[str], str]:
    """LLM 呼び出しコールバックを返す（後方互換用エイリアス）."""
    return _make_call_fn(variant)


def _parse_json_response(content: str) -> list[dict]:
    """LLM レスポンスから JSON 配列をパースする."""
    return llm_client.parse_json_response(content)


def _format_posts(posts: list[dict]) -> str:
    """投稿リストをテキスト形式にフォーマットする."""
    from src.pain_keywords_ja import contains_monetization_signal

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

        # 課金意欲シグナル検出
        monetization_tag = ""
        full_text = f"{title} {body}"
        if contains_monetization_signal(full_text):
            monetization_tag = "\n[MONETIZATION_SIGNAL] この投稿には課金意欲を示す表現が含まれています。willingness_to_pay を high に設定してください。"

        lines.append(
            f"---\n[{source}] {title}\n"
            f"URL: {url}\n"
            f"Engagement: {engagement}\n"
            f"{body}{monetization_tag}\n"
        )

    return "\n".join(lines)
