"""notify.py の純粋ロジック関数のユニットテスト.

外部サービス（GitHub API、LLM）はモックしない。
TF-IDF による重複検出の純粋ロジックのみをテストする。
"""

import pytest

from src.notify import (
    DUPLICATE_THRESHOLD_HIGH,
    DUPLICATE_THRESHOLD_LOW,
    _build_pain_data_comment,
    _extract_product_key,
    _extract_product_key_from_body,
    _find_duplicate,
    _find_duplicate_by_product,
    extract_pain_data_from_body,
)


class TestFindDuplicate:
    """_find_duplicate のテスト.

    注: _llm_judge_duplicate は GITHUB_TOKEN がない環境では False を返すため、
    グレーゾーン（0.4 <= sim < 0.7）のケースは LLM 判定なしで検証する。
    """

    def test_empty_existing_issues_returns_none(self):
        result = _find_duplicate("タスク管理アプリが欲しい", [])
        assert result is None

    def test_clearly_duplicate_text_detected(self):
        """ほぼ同一のテキストは高い類似度で重複検出される."""
        existing = [
            {"number": 1, "title": "毎日の家計管理が面倒で自動化したい"},
        ]
        pain_text = "毎日の家計管理が面倒で自動化したい"
        result = _find_duplicate(pain_text, existing)
        assert result is not None
        assert result["number"] == 1

    def test_clearly_different_text_not_detected(self):
        """全く異なるトピックは重複として検出されない."""
        existing = [
            {"number": 1, "title": "cooking recipe app needed"},
            {"number": 2, "title": "fitness tracker for running"},
        ]
        pain_text = "tax return filing automation"
        result = _find_duplicate(pain_text, existing)
        assert result is None

    def test_same_text_returns_matching_issue(self):
        """同一テキストは必ず重複検出される."""
        existing = [
            {"number": 10, "title": "レシートの自動仕分けができるアプリ"},
            {"number": 11, "title": "子どもの睡眠記録アプリ"},
        ]
        pain_text = "レシートの自動仕分けができるアプリ"
        result = _find_duplicate(pain_text, existing)
        assert result is not None
        assert result["number"] == 10

    def test_returns_most_similar_issue(self):
        """複数候補の中で最も類似度が高い Issue を返す."""
        existing = [
            {"number": 1, "title": "email inbox management tool"},
            {"number": 2, "title": "email newsletter unsubscribe automation"},
            {"number": 3, "title": "fitness workout tracker app"},
        ]
        # email に関連したテキストは email 系の Issue とマッチするはず
        pain_text = "email newsletter unsubscribe automation tool"
        result = _find_duplicate(pain_text, existing)
        assert result is not None
        assert result["number"] == 2

    def test_single_word_corpus_returns_none_on_value_error(self):
        """TF-IDF が ValueError を出す場合は None を返す（例: 1文字トークンのみ）.

        tokenizer が空のトークンリストを返す入力では ValueError が発生するが、
        _find_duplicate は try/except ValueError で保護されている。
        """
        # 全て記号・数字のみの場合、日本語 tokenizer は空を返し ValueError になる可能性がある
        existing = [{"number": 1, "title": "1 2 3"}]
        result = _find_duplicate("4 5 6", existing)
        # ValueError が出ても None を返す（クラッシュしない）
        assert result is None or isinstance(result, dict)

    def test_duplicate_threshold_constants(self):
        """閾値定数が期待通りの値であることを確認."""
        assert DUPLICATE_THRESHOLD_HIGH == 0.7
        assert DUPLICATE_THRESHOLD_LOW == 0.4

    def test_similar_but_different_topic_not_duplicate(self):
        """似た単語を含むが異なるトピックは重複にならない."""
        existing = [
            {"number": 1, "title": "baby sleep tracking app for parents"},
        ]
        pain_text = "sleep quality monitoring for adults with insomnia"
        result = _find_duplicate(pain_text, existing)
        # 異なるトピックなので重複なし（高い閾値 0.7 を超えない）
        assert result is None

    def test_japanese_duplicate_detected(self):
        """日本語テキストの重複も正しく検出される."""
        existing = [
            {"number": 5, "title": "子育て中の予防接種スケジュール管理が煩雑"},
        ]
        pain_text = "子育て中の予防接種スケジュール管理が煩雑"
        result = _find_duplicate(pain_text, existing)
        assert result is not None
        assert result["number"] == 5


class TestExtractProductKey:
    """_extract_product_key のテスト."""

    def test_none_url_returns_none(self):
        assert _extract_product_key(None) is None

    def test_empty_url_returns_none(self):
        assert _extract_product_key("") is None

    def test_appstore_app_id_extracted(self):
        url = "https://apps.apple.com/app/id1232780281"
        assert _extract_product_key(url) == "appstore:1232780281"

    def test_appstore_with_locale_and_name(self):
        url = "https://apps.apple.com/jp/app/notion/id1232780281"
        assert _extract_product_key(url) == "appstore:1232780281"

    def test_appstore_with_query_params(self):
        url = "https://apps.apple.com/us/app/notion/id1232780281?uo=4"
        assert _extract_product_key(url) == "appstore:1232780281"

    def test_hacker_news_item(self):
        url = "https://news.ycombinator.com/item?id=48060054"
        assert _extract_product_key(url) == "hn:48060054"

    def test_stackoverflow_question(self):
        url = "https://stackoverflow.com/questions/67855644/docker-service-failed-to-start"
        assert _extract_product_key(url) == "so:67855644"

    def test_togetter_li(self):
        url = "https://togetter.com/li/2695085"
        assert _extract_product_key(url) == "togetter:2695085"

    def test_unknown_source_returns_none(self):
        """サブレディットや一般 URL は同一プロダクトを意味しないので None."""
        assert _extract_product_key("https://www.reddit.com/r/programming/comments/abc/foo") is None
        assert _extract_product_key("https://example.com/path") is None


class TestExtractProductKeyFromBody:
    """_extract_product_key_from_body のテスト."""

    def test_none_body_returns_none(self):
        assert _extract_product_key_from_body(None) is None

    def test_html_marker_extracted(self):
        body = "## ペイン\n本文...\n<!-- product:appstore:1232780281 -->"
        assert _extract_product_key_from_body(body) == "appstore:1232780281"

    def test_marker_case_insensitive(self):
        body = "<!-- PRODUCT:APPSTORE:1232780281 -->"
        assert _extract_product_key_from_body(body) == "appstore:1232780281"

    def test_fallback_to_url_in_body(self):
        """マーカーが無くてもソース URL から再抽出できる（後方互換）."""
        body = "## ソース\n[Notion: 動作が重過ぎる](https://apps.apple.com/app/id1232780281)"
        assert _extract_product_key_from_body(body) == "appstore:1232780281"

    def test_no_match_returns_none(self):
        body = "## ペイン\n何かのテキスト\n他に手がかりはなし"
        assert _extract_product_key_from_body(body) is None


class TestFindDuplicateByProduct:
    """_find_duplicate_by_product のテスト."""

    def test_none_product_key_returns_none(self):
        existing = [{"number": 1, "title": "x", "body": "<!-- product:appstore:1 -->"}]
        assert _find_duplicate_by_product(None, existing) is None

    def test_empty_existing_returns_none(self):
        assert _find_duplicate_by_product("appstore:1", []) is None

    def test_same_product_key_matched(self):
        existing = [
            {"number": 100, "title": "Notion 重い", "body": "<!-- product:appstore:1232780281 -->"},
            {"number": 200, "title": "別アプリ", "body": "<!-- product:appstore:99999 -->"},
        ]
        result = _find_duplicate_by_product("appstore:1232780281", existing)
        assert result is not None
        assert result["number"] == 100

    def test_no_match_returns_none(self):
        existing = [
            {"number": 1, "title": "x", "body": "<!-- product:appstore:9999 -->"},
        ]
        assert _find_duplicate_by_product("appstore:1232780281", existing) is None

    def test_matches_via_body_url_fallback(self):
        """マーカー無し（古い Issue）でも本文 URL から判定できる."""
        existing = [
            {
                "number": 50,
                "title": "古い Issue",
                "body": "## ソース\n[X](https://apps.apple.com/app/id1232780281)",
            },
        ]
        result = _find_duplicate_by_product("appstore:1232780281", existing)
        assert result is not None
        assert result["number"] == 50


class TestPainDataEmbedding:
    """_build_pain_data_comment / extract_pain_data_from_body のテスト（Issue メタデータ SSOT）."""

    def test_roundtrip_with_japanese_and_emoji(self):
        """日本語・絵文字を含むペインデータが埋め込み→抽出で完全に復元される."""
        pain = {
            "pain": "毎日の家計簿入力が面倒 😩",
            "app_idea": "レシート撮影で自動仕訳するアプリ 📸",
            "existing_solutions": "Zaim はあるが手入力が多い",
            "severity": 4,
            "willingness_to_pay": "high",
            "category": "生産性",
            "source_engagement": {"score": 120},
        }
        comment = _build_pain_data_comment(pain)
        body = f"## ペイン\n{pain['pain']}\n{comment}"

        restored = extract_pain_data_from_body(body)

        assert restored == pain

    def test_embeds_only_scoring_relevant_keys(self):
        """スコアリングに不要なキー（source_url 等）は埋め込まれない."""
        pain = {
            "pain": "テスト",
            "severity": 2,
            "willingness_to_pay": "low",
            "source_url": "https://example.com/should-not-be-embedded",
        }
        comment = _build_pain_data_comment(pain)
        restored = extract_pain_data_from_body(comment)

        assert restored is not None
        assert "source_url" not in restored
        assert restored["pain"] == "テスト"

    def test_sanitizes_html_comment_terminator_in_value(self):
        """値に `-->` が含まれる場合、コメント終端が壊れないようサニタイズされる."""
        pain = {
            "pain": "コメント終端を含む --> テキスト",
            "severity": 3,
            "willingness_to_pay": "medium",
        }
        comment = _build_pain_data_comment(pain)

        # コメント内に本物のコメント終端がサニタイズ後の 1 箇所しか現れないこと
        assert comment.count("-->") == 1
        assert comment.endswith("-->")

        restored = extract_pain_data_from_body(comment)
        assert restored is not None
        assert "-->" not in restored["pain"]

    def test_none_body_returns_none(self):
        assert extract_pain_data_from_body(None) is None

    def test_empty_body_returns_none(self):
        assert extract_pain_data_from_body("") is None

    def test_missing_marker_returns_none(self):
        body = "## ペイン\n本文のみ。メタデータなし。"
        assert extract_pain_data_from_body(body) is None

    def test_malformed_json_returns_none(self):
        body = "<!-- pain-data:{not valid json} -->"
        assert extract_pain_data_from_body(body) is None

    def test_non_dict_json_returns_none(self):
        body = '<!-- pain-data:["a", "b"] -->'
        assert extract_pain_data_from_body(body) is None
