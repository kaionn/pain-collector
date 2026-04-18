"""Spec validator のテスト."""

from __future__ import annotations

import textwrap

import pytest

from src.spec_validator import (
    extract_front_matter,
    validate_front_matter,
    validate_spec_text,
)


VALID_FRONT_MATTER = {
    "schema_version": 1,
    "product_name": "recipe-helper",
    "source_issue": 97,
    "title": "自炊レシピ提案アプリ",
    "tech_stack": {
        "frontend": "Next.js 14",
        "backend": "Next.js API Routes",
        "database": "SQLite",
        "infrastructure": "Vercel",
    },
    "data_model": [
        {
            "entity": "Recipe",
            "fields": ["id", "title", "ingredients"],
            "relations": ["User (N:1)"],
        }
    ],
    "api_endpoints": [
        {"method": "GET", "path": "/api/recipes", "description": "レシピ一覧"}
    ],
    "mvp_scope": ["レシピ一覧表示", "レシピ作成"],
    "success_metrics": [{"kpi": "MAU", "target": "1000"}],
    "deployment_target": "vercel",
}


def _make_spec(front_matter_yaml: str, body: str = "# Spec\n") -> str:
    return f"---\n{front_matter_yaml}\n---\n{body}"


def test_extract_front_matter_returns_dict():
    spec = _make_spec("schema_version: 1\nproduct_name: foo")
    result = extract_front_matter(spec)
    assert result == {"schema_version": 1, "product_name": "foo"}


def test_extract_front_matter_returns_none_for_legacy():
    spec = "# Technical Spec: foo\n\nlegacy body without front matter"
    assert extract_front_matter(spec) is None


def test_validate_front_matter_passes_for_valid_input():
    errors = validate_front_matter(VALID_FRONT_MATTER)
    assert errors == []


def test_validate_front_matter_detects_missing_required_field():
    invalid = {**VALID_FRONT_MATTER}
    del invalid["product_name"]
    errors = validate_front_matter(invalid)
    assert any("product_name" in err for err in errors)


def test_validate_front_matter_detects_invalid_product_name_pattern():
    invalid = {**VALID_FRONT_MATTER, "product_name": "Invalid_Name"}
    errors = validate_front_matter(invalid)
    assert any("product_name" in err for err in errors)


def test_validate_front_matter_detects_invalid_deployment_target():
    invalid = {**VALID_FRONT_MATTER, "deployment_target": "heroku"}
    errors = validate_front_matter(invalid)
    assert any("deployment_target" in err for err in errors)


def test_validate_front_matter_detects_invalid_api_method():
    invalid = {
        **VALID_FRONT_MATTER,
        "api_endpoints": [
            {"method": "FETCH", "path": "/api/x", "description": "x"}
        ],
    }
    errors = validate_front_matter(invalid)
    assert any("api_endpoints" in err for err in errors)


def test_validate_front_matter_allows_empty_api_endpoints():
    """フロントエンドのみのアプリは API endpoints が空配列でも OK."""
    valid = {**VALID_FRONT_MATTER, "api_endpoints": []}
    errors = validate_front_matter(valid)
    assert errors == []


def test_validate_spec_text_legacy_is_treated_as_ok():
    legacy_spec = "# Technical Spec: legacy\n\nno front matter"
    result = validate_spec_text(legacy_spec)
    assert result.legacy is True
    assert result.ok is True
    assert result.front_matter is None


def test_validate_spec_text_full_valid_spec():
    spec = textwrap.dedent("""\
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
    """)
    result = validate_spec_text(spec)
    assert result.ok is True
    assert result.legacy is False
    assert result.front_matter is not None
    assert result.front_matter["product_name"] == "recipe-helper"


def test_validate_spec_text_invalid_returns_errors():
    spec = textwrap.dedent("""\
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
    result = validate_spec_text(spec)
    assert result.ok is False
    assert any("data_model" in err for err in result.errors)
    assert any("mvp_scope" in err for err in result.errors)
    assert any("success_metrics" in err for err in result.errors)


@pytest.mark.parametrize(
    "name",
    ["a", "aa", "Foo", "with_underscore", "trailing-", "-leading", "tooooooooooooooooooooooooooooooooooooooooooooooo-long"],
)
def test_validate_front_matter_rejects_bad_product_names(name: str):
    invalid = {**VALID_FRONT_MATTER, "product_name": name}
    errors = validate_front_matter(invalid)
    assert any("product_name" in err for err in errors)
