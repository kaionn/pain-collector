"""Deep Dive レポートまたは Issue から技術 Spec（実装計画）を自動生成する.

出力フォーマットは specs/SCHEMA.md に準拠した YAML Front Matter + Markdown body。
生成後は spec_validator で構造検証し、失敗時は最大 2 回までリトライする。
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

from src import llm_client

from . import generate_product_name
from . import spec_validator

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

MAX_VALIDATION_RETRIES = 2

SCHEMA_VERSION = 1

DEFAULT_DEPLOYMENT_TARGET = "vercel"

SPEC_PROMPT = """\
あなたはシニアソフトウェアアーキテクトなのだ。
入力された Deep Dive レポートまたは Issue 本文をもとに、
個人開発者が即座に実装を開始できる Technical Spec を以下のフォーマットで生成してください。

## 出力フォーマット（厳守）

最初に YAML Front Matter（`---` で囲む）、その後に Markdown body を続ける。

```
---
schema_version: 1
product_name: {product_name}
source_issue: {source_issue}
title: <Issue の人間向けタイトル>
tech_stack:
  frontend: <例: "Next.js 14 (App Router)">
  backend: <例: "Next.js API Routes" or "なし">
  database: <例: "SQLite" / "Supabase" / "localStorage" / "なし">
  infrastructure: <例: "Vercel" / "Cloudflare Pages">
data_model:
  - entity: <エンティティ名>
    fields: [<field1>, <field2>, ...]
    relations: [<relation1>, ...]   # 任意
api_endpoints:
  - method: GET|POST|PUT|DELETE|PATCH
    path: /api/...
    description: <説明>
mvp_scope:
  - <実装する機能 1>
  - <実装する機能 2>
success_metrics:
  - kpi: <KPI 名>
    target: "<目標値>"
deployment_target: vercel|github-pages|cloudflare-pages
---

# Technical Spec: <title>

_Source: Issue #{source_issue}_

## 要件定義

ユーザーストーリーを 5-8 件:
- R1. 「<role> として、<action> したい、なぜなら <reason> だから」
- R2. ...

## 画面一覧

| パス | 画面名 | 主要コンポーネント |
|------|--------|-------------------|

## 補足

<差別化要素・既存サービスとの違い・実装上の注意点など>
```

## 制約

- `product_name` は固定値 `{product_name}` を必ずそのまま使う（kebab-case、3-40 文字）
- `source_issue` は固定値 `{source_issue}` を必ずそのまま使う
- `data_model` と `mvp_scope` と `success_metrics` は最低 1 件
- `tech_stack.backend` 不要なら文字列 `"なし"`、`tech_stack.database` 不要なら `"localStorage"` か `"なし"`
- `deployment_target` はデフォルト `vercel`、静的サイトのみなら `github-pages` も可
- YAML 文字列に `:` を含む場合はダブルクォートで囲む
- 出力は Front Matter + body のみ。前置き・後書き・コードフェンスでの全体囲みは不要
"""


def _call_llm(system_prompt: str, user_prompt: str) -> str:
    """LLM を呼び出す."""
    return llm_client.chat(user_prompt, system=system_prompt, temperature=0.3)


def _strip_code_fence(text: str) -> str:
    """LLM が誤って全体をコードフェンスで囲んだ場合の除去."""
    stripped = text.strip()
    fence_match = re.match(r"^```(?:markdown|md)?\s*\n(.*?)\n```\s*$", stripped, re.DOTALL)
    if fence_match:
        return fence_match.group(1)
    return stripped


def _build_prompt(product_name: str, source_issue: int) -> str:
    return SPEC_PROMPT.format(
        product_name=product_name,
        source_issue=source_issue,
    )


def _generate_with_validation(
    user_prompt: str,
    product_name: str,
    source_issue: int,
) -> tuple[str | None, list[str]]:
    """LLM を呼び出して Spec を生成し、validator にかける.

    最大 MAX_VALIDATION_RETRIES 回までリトライする。
    """
    last_errors: list[str] = []
    base_prompt = _build_prompt(product_name, source_issue)

    for attempt in range(MAX_VALIDATION_RETRIES + 1):
        if attempt == 0:
            system_prompt = base_prompt
            current_user_prompt = user_prompt
        else:
            error_summary = "\n".join(f"- {err}" for err in last_errors)
            system_prompt = (
                f"{base_prompt}\n\n"
                f"## 前回の生成は以下のエラーで失敗しました。修正してください:\n{error_summary}"
            )
            current_user_prompt = user_prompt
            logger.warning(f"Spec 生成リトライ {attempt}/{MAX_VALIDATION_RETRIES}")

        try:
            raw = _call_llm(system_prompt, current_user_prompt)
        except Exception as exc:
            logger.error(f"LLM 呼び出し失敗 (attempt={attempt}): {exc}")
            last_errors = [f"LLM error: {exc}"]
            continue

        cleaned = _strip_code_fence(raw)
        result = spec_validator.validate_spec_text(cleaned)

        if result.legacy:
            last_errors = ["Front Matter が出力されていない"]
            continue

        if result.ok:
            return cleaned, []

        last_errors = result.errors

    return None, last_errors


def _extract_issue_number_from_filename(deep_dive_path: str) -> int | None:
    """Deep Dive ファイル名から issue_number を抽出する（不可能なら None）."""
    basename = os.path.basename(deep_dive_path)
    match = re.match(r"issue-(\d+)-", basename)
    if match:
        return int(match.group(1))
    return None


def _extract_title_from_deep_dive(content: str) -> str:
    title_match = re.search(r"^# Deep Dive: (.+)$", content, re.MULTILINE)
    return title_match.group(1) if title_match else "Unknown"


def _save_spec(spec_path: str, content: str) -> None:
    os.makedirs(os.path.dirname(spec_path), exist_ok=True)
    with open(spec_path, "w", encoding="utf-8") as f:
        f.write(content if content.endswith("\n") else content + "\n")


def _save_legacy_fallback(spec_path: str, raw: str, errors: list[str]) -> None:
    """Schema 準拠化に失敗した場合の legacy 保存."""
    error_lines = "\n".join(f"- {err}" for err in errors)
    fallback = (
        f"<!-- ⚠️ schema 検証に失敗したため legacy 形式で保存されています\n"
        f"errors:\n{error_lines}\n-->\n\n{raw}"
    )
    _save_spec(spec_path, fallback)


def generate_spec_from_deep_dive(
    deep_dive_path: str,
    issue_number: int | None = None,
    title: str | None = None,
) -> str | None:
    """Deep Dive レポートから技術 Spec を生成して保存する.

    issue_number / title が省略された場合はファイル名・本文から推定する。
    """
    if not os.path.exists(deep_dive_path):
        logger.warning(f"Deep Dive ファイルが見つかりません: {deep_dive_path}")
        return None

    with open(deep_dive_path, encoding="utf-8") as f:
        deep_dive_content = f.read()

    resolved_issue = issue_number or _extract_issue_number_from_filename(deep_dive_path)
    resolved_title = title or _extract_title_from_deep_dive(deep_dive_content)

    if resolved_issue is None:
        logger.error(
            f"Deep Dive から issue_number を抽出できません (path={deep_dive_path})。"
            "呼び出し元から issue_number を渡してください。"
        )
        return None

    product_name = generate_product_name.generate(resolved_title, resolved_issue)
    logger.info(f"Spec 生成: {resolved_title} (product_name={product_name})")

    user_prompt = (
        f"Issue #{resolved_issue} のタイトル: {resolved_title}\n"
        f"想定 product_name: {product_name}\n\n"
        f"以下の Deep Dive レポートから Spec を生成してください:\n\n{deep_dive_content}"
    )

    content, errors = _generate_with_validation(user_prompt, product_name, resolved_issue)

    basename = os.path.basename(deep_dive_path).replace(".md", "")
    spec_dir = os.path.join(BASE_DIR, "specs")
    spec_path = os.path.join(spec_dir, f"{basename}-spec.md")

    if content is not None:
        _save_spec(spec_path, content)
        logger.info(f"Spec を保存: {spec_path}")
        return spec_path

    logger.error(f"Spec 生成に失敗（{MAX_VALIDATION_RETRIES + 1} 回試行）: {errors}")
    return None


def generate_spec_from_issue(issue_number: int, title: str, body: str) -> str | None:
    """Issue のタイトル/本文から直接 Spec を生成して保存する.

    Deep Dive レポートが無い Issue に対する fallback。
    """
    product_name = generate_product_name.generate(title, issue_number)
    logger.info(f"Spec 生成 (Issue #{issue_number}): {title} (product_name={product_name})")

    user_prompt = (
        f"以下のペイン Issue から Spec を生成してください。\n"
        f"想定 product_name: {product_name}\n\n"
        f"# Issue #{issue_number}: {title}\n\n{body}"
    )

    content, errors = _generate_with_validation(user_prompt, product_name, issue_number)

    spec_dir = os.path.join(BASE_DIR, "specs")
    spec_path = os.path.join(spec_dir, f"issue-{issue_number}-spec.md")

    if content is not None:
        _save_spec(spec_path, content)
        logger.info(f"Spec を保存: {spec_path}")
        return spec_path

    logger.error(f"Spec 生成に失敗（{MAX_VALIDATION_RETRIES + 1} 回試行）: {errors}")
    return None


def run_for_latest(date_str: str) -> None:
    """指定日の Deep Dive レポートから Spec を生成する."""
    deep_dive_dir = os.path.join(BASE_DIR, "deep_dive")
    if not os.path.isdir(deep_dive_dir):
        logger.info("Deep Dive ディレクトリが存在しません")
        return

    target_files = [
        f for f in os.listdir(deep_dive_dir)
        if f.startswith(date_str) and f.endswith(".md")
    ]

    if not target_files:
        logger.info(f"{date_str} の Deep Dive レポートがありません")
        return

    for fname in target_files:
        deep_dive_path = os.path.join(deep_dive_dir, fname)
        spec_path = os.path.join(BASE_DIR, "specs", fname.replace(".md", "-spec.md"))

        if os.path.exists(spec_path):
            logger.info(f"Spec 既存: {spec_path}")
            continue

        generate_spec_from_deep_dive(deep_dive_path)
