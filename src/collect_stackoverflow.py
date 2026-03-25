"""Stack Overflow から未解決のペイン系質問を収集する."""

import logging
import re
import zlib

from src.http_utils import create_retry_session

logger = logging.getLogger(__name__)

API_BASE = "https://api.stackexchange.com/2.3"

TAGS = [
    "javascript", "python", "react", "typescript",
    "node.js", "css", "docker", "kubernetes",
]

PAIN_KEYWORDS = re.compile(
    r"\b(wish|annoying|hate|frustrating|why can'?t|sick of|tired of|"
    r"struggle|pain point|broken|useless|awful|terrible|worst|"
    r"impossible|inconvenient|waste of time|how to fix|not working|"
    r"error|bug|issue|problem)\b",
    re.IGNORECASE,
)

_session = create_retry_session()


def _strip_html(text: str) -> str:
    """HTML タグを除去する."""
    return re.sub(r"<[^>]+>", "", text)


def _fetch_questions(tag: str) -> list[dict]:
    """指定タグの質問を取得する（回答なし・閲覧数多い）."""
    url = (
        f"{API_BASE}/questions"
        f"?order=desc&sort=activity&site=stackoverflow"
        f"&tagged={tag}&pagesize=30&filter=withbody"
    )
    try:
        resp = _session.get(url, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        return data.get("items", [])
    except Exception as e:
        logger.warning(f"tag={tag} の取得に失敗: {e}")
        return []


def collect() -> list[dict]:
    """Stack Overflow から未解決ペイン系質問を収集する."""
    seen_ids: set[int] = set()
    all_posts: list[dict] = []

    for tag in TAGS:
        questions = _fetch_questions(tag)

        for q in questions:
            qid = q.get("question_id", 0)
            if qid in seen_ids:
                continue
            seen_ids.add(qid)

            # 未回答 or 未承認かつ閲覧多い = 未解決ペインのシグナル
            answer_count = q.get("answer_count", 0)
            view_count = q.get("view_count", 0)
            if answer_count > 0 and view_count < 100:
                continue

            title = q.get("title", "")
            body = _strip_html(q.get("body", ""))[:1000]
            combined = f"{title} {body}"

            if not PAIN_KEYWORDS.search(combined):
                continue

            all_posts.append({
                "source": "stackoverflow",
                "title": title,
                "url": q.get("link", ""),
                "body": body,
                "score": q.get("score", 0),
                "view_count": view_count,
                "answer_count": answer_count,
            })

    logger.info(f"{len(all_posts)} 件のペイン質問を取得")
    return all_posts
