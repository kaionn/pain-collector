"""Spec ファイルの Front Matter を JSON Schema で検証する."""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEMA_PATH = os.path.join(BASE_DIR, "specs", "schema.json")

_FRONT_MATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    front_matter: dict[str, Any] | None
    errors: list[str]
    legacy: bool  # Front Matter を持たない旧形式 Spec


def _parse_yaml(text: str) -> dict[str, Any]:
    """Front Matter の YAML を解析する.

    PyYAML がなくても最低限動くよう、依存を増やさない方針。
    ただし複雑な YAML は対応できないため、将来的に PyYAML を requirements に追加する可能性がある。
    """
    try:
        import yaml  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "PyYAML が必要なのだ。`pip install pyyaml` を実行してほしいのだ。"
        ) from exc

    parsed = yaml.safe_load(text)
    if not isinstance(parsed, dict):
        raise ValueError("Front Matter がオブジェクト形式ではありません")
    return parsed


def extract_front_matter(spec_text: str) -> dict[str, Any] | None:
    """Markdown ファイルから YAML Front Matter を抽出する.

    Front Matter がない場合は None を返す。
    """
    match = _FRONT_MATTER_RE.match(spec_text)
    if not match:
        return None
    return _parse_yaml(match.group(1))


def load_schema(schema_path: str | None = None) -> dict[str, Any]:
    """JSON Schema をロードする."""
    path = schema_path or SCHEMA_PATH
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def validate_front_matter(
    front_matter: dict[str, Any],
    schema_path: str | None = None,
) -> list[str]:
    """Front Matter を JSON Schema で検証し、エラーメッセージのリストを返す."""
    try:
        from jsonschema import Draft7Validator  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "jsonschema が必要なのだ。`pip install jsonschema` を実行してほしいのだ。"
        ) from exc

    schema = load_schema(schema_path)
    validator = Draft7Validator(schema)
    errors = sorted(validator.iter_errors(front_matter), key=lambda e: list(e.absolute_path))
    return [f"{'.'.join(str(p) for p in err.absolute_path) or '<root>'}: {err.message}" for err in errors]


def validate_spec_text(spec_text: str, schema_path: str | None = None) -> ValidationResult:
    """Spec ファイルの内容を検証する."""
    front_matter = extract_front_matter(spec_text)
    if front_matter is None:
        return ValidationResult(ok=True, front_matter=None, errors=[], legacy=True)

    errors = validate_front_matter(front_matter, schema_path)
    return ValidationResult(
        ok=not errors,
        front_matter=front_matter,
        errors=errors,
        legacy=False,
    )


def validate_spec_file(spec_path: str, schema_path: str | None = None) -> ValidationResult:
    """Spec ファイルを読み込んで検証する."""
    with open(spec_path, encoding="utf-8") as f:
        return validate_spec_text(f.read(), schema_path)


def main() -> int:
    """CLI エントリポイント: `python -m src.spec_validator <path>`."""
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Validate pain-collector Spec files.")
    parser.add_argument("path", help="Spec ファイルのパス")
    parser.add_argument(
        "--schema",
        default=None,
        help="JSON Schema のパス (デフォルト: specs/schema.json)",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Front Matter がない legacy Spec も失敗扱いにする",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    result = validate_spec_file(args.path, args.schema)

    if result.legacy:
        if args.strict:
            print(f"FAIL ({args.path}): Front Matter がありません (legacy Spec)", file=sys.stderr)
            return 1
        print(f"WARN ({args.path}): Front Matter がない legacy Spec です")
        return 0

    if result.ok:
        print(f"OK ({args.path}): Spec は schema に準拠しています")
        return 0

    print(f"FAIL ({args.path}): 以下のエラーがあります", file=sys.stderr)
    for err in result.errors:
        print(f"  - {err}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
