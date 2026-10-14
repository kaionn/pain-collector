"""Offline regression for topic-level dedup, including the #271/#273 incident."""
from unittest.mock import Mock

import pytest

from src import notify, scoring, discord_notify

URL = "https://girlschannel.net/topics/6299340/"
OLD_PAIN = "育児に疲れ果てても、今日・明日すぐ子どもを預けられる一時保育やファミサポの空きを探す手段がわからない。電話で一件ずつ問い合わせる手間もあり、結局一人で抱え込んでしまう。"
NEW_PAIN = "ワンオペ育児で心身ともに限界でも、一時保育やファミサポなど頼れる先の空き状況や手続きを調べる余力がなく、休む手段にたどり着けない。"


@pytest.mark.parametrize("suffix", ["", "/", "?page=2", "/?page=2#comment", "#comment"])
def test_topic_url_variants(suffix):
    assert notify._extract_product_key(URL.rstrip("/") + suffix) == "girlschannel:6299340"


@pytest.mark.parametrize("url", [
    "https://girlschannel.net.evil.test/topics/6299340/",
    "https://evil.test/girlschannel.net/topics/6299340/",
    "https://girlschannel.net@evil.test/topics/6299340/",
    "https://evil.test/?url=https://girlschannel.net/topics/6299340/",
    "https://www.girlschannel.net/topics/6299340/",
    "https://girlschannel.net/topics/6299340/extra",
    "https://girlschannel.net/topics/6299340x/",
    "https://girlschannel.net/topics/１２３/",
    "https://girlschannel.net/topics/",
    "ftp://girlschannel.net/topics/6299340/",
    "https://user@girlschannel.net/topics/6299340/",
    "https://girlschannel.net:8443/topics/6299340/",
    "https://[broken/topics/6299340/",
])
def test_invalid_topic_urls(url):
    assert notify._extract_product_key(url) is None


def test_different_topics():
    issue = {"number": 271, "body": f"## ソース\n[topic]({URL})"}
    assert notify._find_duplicate_by_product("girlschannel:6299341", [issue]) is None


@pytest.fixture
def offline(monkeypatch):
    mocks = {}
    for module, name in [
        (notify, "_fetch_open_issues"), (notify, "_comment_duplicate"),
        (notify, "_create_issue"), (notify.pain_gate, "classify"),
        (scoring, "score_and_update_issue"), (discord_notify, "notify_daily_digest"),
    ]:
        mocks[name] = Mock()
        monkeypatch.setattr(module, name, mocks[name])
    monkeypatch.setattr(notify.subprocess, "run", Mock(side_effect=AssertionError("external command forbidden")))
    monkeypatch.setattr(notify.llm_client, "chat", Mock(side_effect=AssertionError("LLM forbidden")))
    monkeypatch.setattr(notify.llm_client, "embed", Mock(side_effect=AssertionError("embedding forbidden")))
    monkeypatch.delenv("PAIN_USE_EMBEDDINGS", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    return mocks


@pytest.mark.parametrize("body", [f"## ソース\n[topic]({URL})", "<!-- product:girlschannel:6299340 -->"])
def test_incident_recurrence_comments_without_creation_or_scoring(offline, body):
    issue = {"number": 271, "title": f"[子育て・育児] {OLD_PAIN[:80]}", "body": body}
    # Existing text-only dedup misses this real paraphrase with no LLM credentials.
    assert notify._find_duplicate(NEW_PAIN, [issue]) is None
    offline["_fetch_open_issues"].return_value = [issue]
    pain = {"pain": NEW_PAIN, "source_url": URL, "severity": 5}
    notify.send_top_pains([pain], "2026-10-12")
    offline["_comment_duplicate"].assert_called_once_with(271, pain, "2026-10-12")
    for name in ["_create_issue", "classify", "score_and_update_issue", "notify_daily_digest"]:
        offline[name].assert_not_called()


def test_same_run_recurrence_and_distinct_pain_grouping(offline):
    offline["_fetch_open_issues"].return_value = []
    offline["classify"].return_value = {"actionable": True, "audience": "consumer"}
    offline["_create_issue"].return_value = {
        "number": 300, "title": OLD_PAIN, "body": "<!-- product:girlschannel:6299340 -->",
    }
    pains = [
        {"pain": OLD_PAIN, "source_url": URL, "severity": 5},
        {"pain": NEW_PAIN, "source_url": URL + "?page=2", "severity": 5},
        {"pain": "夜泣きの睡眠記録を家族で共有したい", "source_url": URL, "severity": 5},
    ]
    notify.send_top_pains(pains, "2026-10-12")
    offline["_create_issue"].assert_called_once()
    assert offline["_comment_duplicate"].call_count == 2
    assert offline["_comment_duplicate"].call_args_list[1].args == (300, pains[2], "2026-10-12")


def test_created_issue_carries_topic_marker(monkeypatch):
    from subprocess import CompletedProcess
    run = Mock(return_value=CompletedProcess([], 0, "https://github.com/kaionn/pain-collector/issues/300\n", ""))
    monkeypatch.setattr(notify.subprocess, "run", run)
    monkeypatch.setattr(notify, "_add_to_project", Mock())
    monkeypatch.setattr(scoring, "score_and_update_issue", Mock())
    result = notify._create_issue({"pain": OLD_PAIN, "source_url": URL}, "2026-10-12", notify_discord=False)
    assert "<!-- product:girlschannel:6299340 -->" in result["body"]
    assert notify._extract_product_key_from_body(result["body"]) == "girlschannel:6299340"
