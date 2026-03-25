"""Spec ファイルから Claude Code セッション起動用シェルスクリプトを生成する.

generate_spec.py が生成した spec ファイルを入力として、
Claude Code セッションを起動するシェルスクリプトを triggers/ ディレクトリに保存する。
"""

import logging
import os
import re
import stat

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _make_slug(text: str) -> str:
    """テキストをファイル名用スラグに変換する.

    Args:
        text: スラグ化する元テキスト。

    Returns:
        先頭 30 文字を取り、英数字・日本語以外をハイフンに置換し
        前後のハイフンを除去した文字列。
    """
    truncated = text[:30]
    slug = re.sub(r"[^\w\u3000-\u9fff\u30a0-\u30ff\u3040-\u309f]", "-", truncated)
    slug = re.sub(r"-{2,}", "-", slug)
    return slug.strip("-")


def generate_trigger(spec_path: str) -> str | None:
    """Spec ファイルから Claude Code 起動シェルスクリプトを生成して保存する.

    生成されるスクリプトは以下を実行する:
    1. プロジェクト名のディレクトリを作成
    2. spec ファイルをコピー
    3. `claude -p` でスペックを入力として Claude Code セッションを起動

    Args:
        spec_path: 入力となる spec ファイルのパス。

    Returns:
        生成したシェルスクリプトのパス。失敗した場合は None。
    """
    if not os.path.exists(spec_path):
        logger.warning(f"Spec ファイルが見つかりません: {spec_path}")
        return None

    # ファイル名からメタ情報を取得
    basename = os.path.basename(spec_path)
    # 例: 2026-03-22-some-slug-spec.md
    name_without_ext = basename.replace(".md", "")

    # 日付を抽出 (YYYY-MM-DD)
    date_match = re.match(r"^(\d{4}-\d{2}-\d{2})-(.+)$", name_without_ext)
    if date_match:
        date_str = date_match.group(1)
        slug_part = date_match.group(2)
    else:
        date_str = "unknown"
        slug_part = _make_slug(name_without_ext)

    # spec サフィックスを除去してプロジェクト名を生成
    project_slug = slug_part.removesuffix("-spec")

    triggers_dir = os.path.join(BASE_DIR, "triggers")
    os.makedirs(triggers_dir, exist_ok=True)

    script_filename = f"{date_str}-{project_slug}.sh"
    script_path = os.path.join(triggers_dir, script_filename)

    if os.path.exists(script_path):
        logger.info(f"トリガースクリプト既存: {script_path}")
        return script_path

    abs_spec_path = os.path.abspath(spec_path)
    project_dir = os.path.join(BASE_DIR, "builds", f"{date_str}-{project_slug}")

    script_content = f"""#!/usr/bin/env bash
# Auto-generated trigger script
# Spec: {abs_spec_path}
# Generated: {date_str}

set -euo pipefail

PROJECT_DIR="{project_dir}"
SPEC_PATH="{abs_spec_path}"

echo "Building: {project_slug}"
echo "Project dir: $PROJECT_DIR"

mkdir -p "$PROJECT_DIR"
cp "$SPEC_PATH" "$PROJECT_DIR/spec.md"

cd "$PROJECT_DIR"
claude -p "$(cat spec.md)"
"""

    with open(script_path, "w", encoding="utf-8") as f:
        f.write(script_content)

    # 実行権限を付与
    current_mode = os.stat(script_path).st_mode
    os.chmod(script_path, current_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    logger.info(f"トリガースクリプトを保存: {script_path}")
    return script_path


def run_after_spec(date_str: str) -> None:
    """指定日の spec ファイルを検索してトリガースクリプトを生成する.

    Args:
        date_str: 対象日の文字列（例: "2026-03-22"）。
    """
    specs_dir = os.path.join(BASE_DIR, "specs")
    if not os.path.isdir(specs_dir):
        logger.info("specs ディレクトリが存在しません")
        return

    target_files = [
        f for f in os.listdir(specs_dir)
        if f.startswith(date_str) and f.endswith(".md")
    ]

    if not target_files:
        logger.info(f"{date_str} の spec ファイルがありません")
        return

    for fname in target_files:
        spec_path = os.path.join(specs_dir, fname)
        generate_trigger(spec_path)
