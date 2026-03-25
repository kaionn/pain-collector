"""extract_pains.py の純粋ロジック関数のユニットテスト."""

import pytest

from src.extract_pains import _attach_engagement, _format_posts, _parse_json_response


class TestParseJsonResponse:
    """_parse_json_response のテスト."""

    def test_plain_json_array(self):
        content = '[{"pain": "テスト", "category": "その他"}]'
        result = _parse_json_response(content)
        assert result == [{"pain": "テスト", "category": "その他"}]

    def test_json_array_with_multiple_items(self):
        content = '[{"pain": "A"}, {"pain": "B"}, {"pain": "C"}]'
        result = _parse_json_response(content)
        assert len(result) == 3
        assert result[0]["pain"] == "A"
        assert result[2]["pain"] == "C"

    def test_json_in_markdown_code_block(self):
        content = '```json\n[{"pain": "コードブロック内"}]\n```'
        result = _parse_json_response(content)
        assert result == [{"pain": "コードブロック内"}]

    def test_json_in_plain_code_block(self):
        content = '```\n[{"pain": "バッククォートなし言語指定"}]\n```'
        result = _parse_json_response(content)
        assert result == [{"pain": "バッククォートなし言語指定"}]

    def test_json_with_leading_trailing_text(self):
        """JSON 配列の前後に余分なテキストがある場合."""
        content = 'はい、以下です:\n[{"pain": "余分なテキスト"}]\n以上です。'
        result = _parse_json_response(content)
        assert result == [{"pain": "余分なテキスト"}]

    def test_empty_array(self):
        content = "[]"
        result = _parse_json_response(content)
        assert result == []

    def test_empty_array_in_code_block(self):
        content = "```json\n[]\n```"
        result = _parse_json_response(content)
        assert result == []

    def test_invalid_json_raises(self):
        with pytest.raises(Exception):
            _parse_json_response("これは JSON ではない")

    def test_invalid_json_in_code_block_raises(self):
        with pytest.raises(Exception):
            _parse_json_response("```\n{invalid json\n```")

    def test_whitespace_stripped(self):
        content = '  \n  [{"pain": "空白あり"}]  \n  '
        result = _parse_json_response(content)
        assert result == [{"pain": "空白あり"}]


class TestFormatPosts:
    """_format_posts のテスト."""

    def test_basic_post_with_all_fields(self):
        posts = [
            {
                "source": "reddit",
                "title": "テストタイトル",
                "url": "https://example.com/1",
                "body": "本文テキスト",
                "score": 100,
                "num_comments": 20,
                "bookmarks": 5,
            }
        ]
        result = _format_posts(posts)
        assert "[reddit] テストタイトル" in result
        assert "URL: https://example.com/1" in result
        assert "Engagement: score=100, comments=20, bookmarks=5" in result
        assert "本文テキスト" in result

    def test_post_with_no_engagement(self):
        posts = [
            {
                "source": "hatena",
                "title": "エンゲージメントなし",
                "url": "https://example.com/2",
                "body": "本文",
            }
        ]
        result = _format_posts(posts)
        assert "Engagement: N/A" in result

    def test_post_with_only_score(self):
        posts = [
            {
                "source": "hackernews",
                "title": "スコアのみ",
                "url": "https://example.com/3",
                "body": "本文",
                "score": 42,
            }
        ]
        result = _format_posts(posts)
        assert "Engagement: score=42" in result
        assert "comments=" not in result
        assert "bookmarks=" not in result

    def test_post_with_summary_instead_of_body(self):
        """body がない場合 summary を使う."""
        posts = [
            {
                "source": "zenn",
                "title": "サマリーテスト",
                "url": "https://example.com/4",
                "summary": "サマリーテキスト",
            }
        ]
        result = _format_posts(posts)
        assert "サマリーテキスト" in result

    def test_multiple_posts_separated_by_separator(self):
        posts = [
            {"source": "reddit", "title": "投稿1", "url": "https://a.com", "body": "本文1"},
            {"source": "hatena", "title": "投稿2", "url": "https://b.com", "body": "本文2"},
        ]
        result = _format_posts(posts)
        assert "投稿1" in result
        assert "投稿2" in result
        assert "---" in result

    def test_empty_posts_returns_empty_string(self):
        result = _format_posts([])
        assert result == ""

    def test_missing_fields_use_defaults(self):
        """フィールドがない場合はデフォルト値（空文字）を使う."""
        posts = [{}]
        result = _format_posts(posts)
        assert "[unknown]" in result
        assert "Engagement: N/A" in result


class TestAttachEngagement:
    """_attach_engagement のテスト."""

    def test_url_match_attaches_engagement(self):
        pains = [{"source_url": "https://example.com/post1"}]
        posts = [
            {
                "url": "https://example.com/post1",
                "score": 100,
                "num_comments": 20,
                "source": "reddit",
            }
        ]
        _attach_engagement(pains, posts)
        assert pains[0]["source_engagement"] == {"score": 100, "num_comments": 20}
        assert pains[0]["language"] == "en"

    def test_missing_url_sets_empty_engagement(self):
        """URL が一致しない場合は空のエンゲージメントとデフォルト言語."""
        pains = [{"source_url": "https://not-found.com"}]
        posts = [{"url": "https://example.com/post1", "source": "reddit"}]
        _attach_engagement(pains, posts)
        assert pains[0]["source_engagement"] == {}
        assert pains[0]["language"] == "ja"

    def test_no_source_url_in_pain(self):
        """ペインに source_url がない場合."""
        pains = [{}]
        posts = [{"url": "https://example.com/post1", "source": "reddit"}]
        _attach_engagement(pains, posts)
        assert pains[0]["source_engagement"] == {}
        assert pains[0]["language"] == "ja"

    def test_language_assignment_english_sources(self):
        """英語ソースの言語割り当てを検証する."""
        english_sources = ["reddit", "hackernews", "devto", "stackoverflow"]
        for source in english_sources:
            pains = [{"source_url": "https://example.com/post"}]
            posts = [{"url": "https://example.com/post", "source": source}]
            _attach_engagement(pains, posts)
            assert pains[0]["language"] == "en", f"{source} should be 'en'"

    def test_language_assignment_japanese_sources(self):
        """日本語ソースの言語割り当てを検証する."""
        japanese_sources = ["hatena", "zenn", "note", "chiebukuro", "girlschannel", "bluesky", "appstore", "googleplay"]
        for source in japanese_sources:
            pains = [{"source_url": "https://example.com/post"}]
            posts = [{"url": "https://example.com/post", "source": source}]
            _attach_engagement(pains, posts)
            assert pains[0]["language"] == "ja", f"{source} should be 'ja'"

    def test_unknown_source_defaults_to_ja(self):
        pains = [{"source_url": "https://example.com/post"}]
        posts = [{"url": "https://example.com/post", "source": "unknown_source"}]
        _attach_engagement(pains, posts)
        assert pains[0]["language"] == "ja"

    def test_only_known_engagement_keys_attached(self):
        """score, num_comments, bookmarks, view_count, answer_count のみ付与される."""
        pains = [{"source_url": "https://example.com/post"}]
        posts = [
            {
                "url": "https://example.com/post",
                "score": 50,
                "num_comments": 10,
                "bookmarks": 3,
                "view_count": 1000,
                "answer_count": 2,
                "irrelevant_field": "should_not_appear",
                "source": "reddit",
            }
        ]
        _attach_engagement(pains, posts)
        eng = pains[0]["source_engagement"]
        assert "score" in eng
        assert "num_comments" in eng
        assert "bookmarks" in eng
        assert "view_count" in eng
        assert "answer_count" in eng
        assert "irrelevant_field" not in eng

    def test_multiple_pains_all_get_engagement(self):
        pains = [
            {"source_url": "https://example.com/a"},
            {"source_url": "https://example.com/b"},
        ]
        posts = [
            {"url": "https://example.com/a", "score": 10, "source": "reddit"},
            {"url": "https://example.com/b", "score": 20, "source": "hatena"},
        ]
        _attach_engagement(pains, posts)
        assert pains[0]["source_engagement"]["score"] == 10
        assert pains[0]["language"] == "en"
        assert pains[1]["source_engagement"]["score"] == 20
        assert pains[1]["language"] == "ja"

    def test_post_without_url_is_ignored(self):
        """url フィールドのない投稿は URL マップに含まれない."""
        pains = [{"source_url": "https://example.com/post"}]
        posts = [{"score": 999, "source": "reddit"}]  # url なし
        _attach_engagement(pains, posts)
        assert pains[0]["source_engagement"] == {}
