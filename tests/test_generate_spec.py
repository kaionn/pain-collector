"""generate_spec.py のテスト.

LLM 呼び出し（``_call_llm``）と product_name 生成は monkeypatch でモックし、
schema 準拠出力・リトライ・legacy fallback の挙動を検証する。
"""

from __future__ import annotations

import os
import textwrap

import pytest

from src import generate_spec


VALID_SPEC_OUTPUT = textwrap.dedent("""\
    ---
    schema_version: 1
    product_name: recipe-helper
    source_issue: 97
    title: 自炊レシピ提案アプリ
    tech_stack:
      frontend: Next.js 14
      backend: Next.js API Routes
      database: SQLite
      infrastructure: Vercel
    data_model:
      - entity: Recipe
        fields: [id, title, ingredients]
    api_endpoints:
      - method: GET
        path: /api/recipes
        description: レシピ一覧
    mvp_scope:
      - レシピ一覧表示
    success_metrics:
      - kpi: MAU
        target: "1000"
    deployment_target: vercel
    ---

    # Technical Spec: 自炊レシピ提案アプリ

    ## 要件定義
    - R1. ...
""")


INVALID_SPEC_OUTPUT = textwrap.dedent("""\
    ---
    schema_version: 1
    product_name: recipe-helper
    source_issue: 97
    title: foo
    tech_stack:
      frontend: Next.js
      backend: なし
      database: localStorage
      infrastructure: Vercel
    data_model: []
    api_endpoints: []
    mvp_scope: []
    success_metrics: []
    deployment_target: vercel
    ---
""")


@pytest.fixture
def mock_product_name(monkeypatch):
    monkeypatch.setattr(
        generate_spec.generate_product_name,
        "generate",
        lambda title, issue_number, **kwargs: "recipe-helper",
    )


@pytest.fixture
def tmp_specs_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(generate_spec, "BASE_DIR", str(tmp_path))
    (tmp_path / "specs").mkdir()
    return tmp_path


def test_strip_code_fence_removes_markdown_fence():
    text = "```markdown\n---\nfoo: bar\n---\n```"
    assert generate_spec._strip_code_fence(text) == "---\nfoo: bar\n---"


def test_strip_code_fence_passthrough_when_no_fence():
    text = "---\nfoo: bar\n---"
    assert generate_spec._strip_code_fence(text) == "---\nfoo: bar\n---"


def test_extract_issue_number_from_filename():
    assert generate_spec._extract_issue_number_from_filename(
        "/x/deep_dive/issue-97-foo.md"
    ) == 97


def test_extract_issue_number_from_filename_returns_none():
    assert generate_spec._extract_issue_number_from_filename(
        "/x/deep_dive/2026-03-21-foo.md"
    ) is None


def test_generate_spec_from_issue_writes_valid_spec(
    monkeypatch, mock_product_name, tmp_specs_dir
):
    calls = []

    def fake_llm(system_prompt, user_prompt):
        calls.append((system_prompt, user_prompt))
        return VALID_SPEC_OUTPUT

    monkeypatch.setattr(generate_spec, "_call_llm", fake_llm)

    spec_path = generate_spec.generate_spec_from_issue(97, "自炊レシピ提案アプリ", "本文")

    assert spec_path is not None
    assert os.path.exists(spec_path)
    assert len(calls) == 1  # 1 回で成功 = リトライなし

    with open(spec_path, encoding="utf-8") as f:
        content = f.read()
    assert content.startswith("---")
    assert "product_name: recipe-helper" in content


def test_generate_spec_retries_on_validation_failure(
    monkeypatch, mock_product_name, tmp_specs_dir
):
    """初回 invalid → 2 回目 valid の挙動."""
    responses = [INVALID_SPEC_OUTPUT, VALID_SPEC_OUTPUT]
    call_count = {"n": 0}

    def fake_llm(system_prompt, user_prompt):
        idx = call_count["n"]
        call_count["n"] += 1
        return responses[idx]

    monkeypatch.setattr(generate_spec, "_call_llm", fake_llm)

    spec_path = generate_spec.generate_spec_from_issue(97, "foo", "body")

    assert spec_path is not None
    assert call_count["n"] == 2  # 1 回リトライして成功


def test_generate_spec_returns_none_after_max_retries(
    monkeypatch, mock_product_name, tmp_specs_dir
):
    """全回 invalid なら None を返す."""
    monkeypatch.setattr(generate_spec, "_call_llm", lambda s, u: INVALID_SPEC_OUTPUT)

    spec_path = generate_spec.generate_spec_from_issue(97, "foo", "body")

    assert spec_path is None


def test_generate_spec_from_deep_dive_extracts_issue_number_from_filename(
    monkeypatch, mock_product_name, tmp_specs_dir
):
    deep_dive_dir = tmp_specs_dir / "deep_dive"
    deep_dive_dir.mkdir()
    deep_dive_path = deep_dive_dir / "issue-97-recipe.md"
    deep_dive_path.write_text("# Deep Dive: 自炊レシピ\n\n本文", encoding="utf-8")

    monkeypatch.setattr(generate_spec, "_call_llm", lambda s, u: VALID_SPEC_OUTPUT)

    spec_path = generate_spec.generate_spec_from_deep_dive(str(deep_dive_path))

    assert spec_path is not None
    assert os.path.exists(spec_path)


def test_generate_spec_from_deep_dive_returns_none_when_no_issue_number(
    monkeypatch, mock_product_name, tmp_specs_dir
):
    deep_dive_dir = tmp_specs_dir / "deep_dive"
    deep_dive_dir.mkdir()
    deep_dive_path = deep_dive_dir / "2026-03-21-foo.md"
    deep_dive_path.write_text("# Deep Dive: foo", encoding="utf-8")

    monkeypatch.setattr(generate_spec, "_call_llm", lambda s, u: VALID_SPEC_OUTPUT)

    spec_path = generate_spec.generate_spec_from_deep_dive(str(deep_dive_path))

    assert spec_path is None


def test_generate_spec_from_deep_dive_uses_explicit_issue_number(
    monkeypatch, mock_product_name, tmp_specs_dir
):
    """明示渡しなら filename からの抽出に失敗しても OK."""
    deep_dive_dir = tmp_specs_dir / "deep_dive"
    deep_dive_dir.mkdir()
    deep_dive_path = deep_dive_dir / "2026-03-21-foo.md"
    deep_dive_path.write_text("# Deep Dive: foo", encoding="utf-8")

    monkeypatch.setattr(generate_spec, "_call_llm", lambda s, u: VALID_SPEC_OUTPUT)

    spec_path = generate_spec.generate_spec_from_deep_dive(
        str(deep_dive_path),
        issue_number=42,
        title="明示タイトル",
    )

    assert spec_path is not None
