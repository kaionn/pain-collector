"""collector_registry.py のユニットテスト."""

from src.collector_registry import (
    CollectorEntry,
    all_collectors,
    register_collector,
    validate_post,
)

# 全 collect_* モジュールを import して @register_collector の副作用を発火させる
from src import (  # noqa: F401
    collect_appstore,
    collect_bluesky,
    collect_chiebukuro,
    collect_devto,
    collect_girlschannel,
    collect_googleplay,
    collect_hatena,
    collect_hn,
    collect_komachi,
    collect_mamastar,
    collect_note,
    collect_producthunt,
    collect_reddit,
    collect_stackoverflow,
    collect_zenn,
)

EXPECTED_KEYS = {
    "reddit",
    "hatena",
    "zenn",
    "hackernews",
    "note",
    "devto",
    "stackoverflow",
    "bluesky",
    "appstore",
    "googleplay",
    "chiebukuro",
    "girlschannel",
    "producthunt",
    "komachi",
    "mamastar",
}


class TestAllCollectorsIntegration:
    """main.py との整合性を守るための、実コレクタ登録を対象にしたテスト."""

    def test_registered_keys_match_expected_15(self):
        keys = {entry.key for entry in all_collectors()}
        assert keys == EXPECTED_KEYS

    def test_only_reddit_supports_backfill(self):
        backfill_keys = {entry.key for entry in all_collectors() if entry.supports_backfill}
        assert backfill_keys == {"reddit"}

    def test_entries_are_unique_per_key(self):
        keys = [entry.key for entry in all_collectors()]
        assert len(keys) == len(set(keys))


class TestRegisterCollectorDecorator:
    """register_collector 自体の登録・順序・backfill フラグの単体テスト."""

    def test_registers_function_and_preserves_call_behavior(self):
        import src.collector_registry as registry_module

        original = list(registry_module._REGISTRY)
        try:
            registry_module._REGISTRY.clear()

            @register_collector(key="dummy", display_name="Dummy")
            def collect() -> list[dict]:
                return [{"title": "hello"}]

            entries = all_collectors()
            assert len(entries) == 1
            assert entries[0] == CollectorEntry(
                key="dummy", display_name="Dummy", fn=collect, supports_backfill=False
            )
            assert collect() == [{"title": "hello"}]
        finally:
            registry_module._REGISTRY.clear()
            registry_module._REGISTRY.extend(original)

    def test_preserves_registration_order(self):
        import src.collector_registry as registry_module

        original = list(registry_module._REGISTRY)
        try:
            registry_module._REGISTRY.clear()

            @register_collector(key="first", display_name="First")
            def collect_first() -> list[dict]:
                return []

            @register_collector(key="second", display_name="Second")
            def collect_second() -> list[dict]:
                return []

            keys = [entry.key for entry in all_collectors()]
            assert keys == ["first", "second"]
        finally:
            registry_module._REGISTRY.clear()
            registry_module._REGISTRY.extend(original)

    def test_supports_backfill_flag_defaults_false(self):
        import src.collector_registry as registry_module

        original = list(registry_module._REGISTRY)
        try:
            registry_module._REGISTRY.clear()

            @register_collector(key="dummy", display_name="Dummy")
            def collect() -> list[dict]:
                return []

            assert all_collectors()[0].supports_backfill is False
        finally:
            registry_module._REGISTRY.clear()
            registry_module._REGISTRY.extend(original)

    def test_supports_backfill_flag_can_be_true(self):
        import src.collector_registry as registry_module

        original = list(registry_module._REGISTRY)
        try:
            registry_module._REGISTRY.clear()

            @register_collector(key="dummy", display_name="Dummy", supports_backfill=True)
            def collect(backfill: bool = False) -> list[dict]:
                return []

            assert all_collectors()[0].supports_backfill is True
        finally:
            registry_module._REGISTRY.clear()
            registry_module._REGISTRY.extend(original)


class TestValidatePost:
    def test_valid_post_with_title(self):
        post = {"title": "困った", "source": "reddit"}
        assert validate_post(post, "reddit") == post

    def test_valid_post_with_body_only(self):
        post = {"title": "", "body": "困っている内容", "source": "reddit"}
        assert validate_post(post, "reddit") == post

    def test_valid_post_with_summary_only(self):
        post = {"title": "", "summary": "困っている内容"}
        result = validate_post(post, "hatena")
        assert result is not None
        assert result["summary"] == "困っている内容"

    def test_rejects_empty_title_and_body(self):
        post = {"title": "", "body": ""}
        assert validate_post(post, "reddit") is None

    def test_rejects_whitespace_only_title_and_body(self):
        post = {"title": "   ", "body": "\n"}
        assert validate_post(post, "reddit") is None

    def test_rejects_missing_title_and_body_keys(self):
        post = {"score": 10}
        assert validate_post(post, "reddit") is None

    def test_fills_missing_source_with_key(self):
        post = {"title": "困った"}
        result = validate_post(post, "hatena")
        assert result is not None
        assert result["source"] == "hatena"

    def test_does_not_overwrite_existing_source(self):
        post = {"title": "困った", "source": "custom"}
        result = validate_post(post, "hatena")
        assert result is not None
        assert result["source"] == "custom"

    def test_does_not_mutate_original_dict(self):
        post = {"title": "困った"}
        validate_post(post, "hatena")
        assert "source" not in post
