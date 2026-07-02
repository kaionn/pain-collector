"""approve.yml 内のインライン Python チェック処理をコマンド化したもの.

各サブコマンドは stdout に単一の値（文字列）だけを出力する。ワークフロー側は
`$(...)` でこの値をキャプチャする前提のため、出力フォーマットは変更しない
（旧 `python3 -c "..."` の移植先）。
"""

from __future__ import annotations

import argparse
import json
import logging
import os

logger = logging.getLogger(__name__)


def _load_state(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _find_picked(state: dict, issue_number: int) -> dict | None:
    for item in state.get("picked", []):
        if item.get("issue_number") == issue_number:
            return item
    return None


def picked_check(state_path: str, issue_number: int) -> str:
    """picked & spec の存在チェック.

    ``NO_STATE`` / ``NOT_PICKED`` / ``NO_SPEC`` / ``<spec_path>`` のいずれかを返す。
    """
    if not os.path.exists(state_path):
        return "NO_STATE"
    state = _load_state(state_path)
    item = _find_picked(state, issue_number)
    if item is None:
        return "NOT_PICKED"
    return item.get("spec") or "NO_SPEC"


def resolve_product_name(state_path: str, issue_number: int) -> str:
    """既存 state に保存された product_name を返す（無ければ空文字）."""
    state = _load_state(state_path)
    item = _find_picked(state, issue_number)
    if item is None:
        return ""
    return item.get("product_name") or ""


def update_state(state_path: str, issue_number: int, status: str, product_name: str) -> None:
    """picked エントリの status / product_name を更新して state を書き戻す.

    state ファイルが存在しない場合は何もしない。
    """
    if not os.path.exists(state_path):
        return
    state = _load_state(state_path)
    for item in state.get("picked", []):
        if item.get("issue_number") == issue_number:
            item["status"] = status
            item["product_name"] = product_name
            break
    with open(state_path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def deep_dive_path(state_path: str, issue_number: int) -> str:
    """picked エントリの deep_dive パスを返す（無ければ空文字）."""
    if not os.path.exists(state_path):
        return ""
    state = _load_state(state_path)
    item = _find_picked(state, issue_number)
    if item is None:
        return ""
    return item.get("deep_dive") or ""


def _build_cli_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--state", default="data/pipeline_state.json", help="pipeline_state.json のパス")
    common.add_argument("--issue-number", required=True, type=int, help="対象 Issue 番号")

    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("picked-check", parents=[common], help="picked & spec の存在チェック")
    sub.add_parser("resolve-product-name", parents=[common], help="既存 product_name の取得")
    sub.add_parser("deep-dive-path", parents=[common], help="deep_dive パスの取得")

    p_update = sub.add_parser("update-state", parents=[common], help="status / product_name を更新")
    p_update.add_argument("--status", required=True)
    p_update.add_argument("--product-name", required=True)

    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "WARNING"),
        format="%(levelname)s: %(message)s",
    )
    parser = _build_cli_parser()
    args = parser.parse_args(argv)

    if args.command == "picked-check":
        print(picked_check(args.state, args.issue_number))
    elif args.command == "resolve-product-name":
        print(resolve_product_name(args.state, args.issue_number))
    elif args.command == "deep-dive-path":
        print(deep_dive_path(args.state, args.issue_number))
    elif args.command == "update-state":
        update_state(args.state, args.issue_number, args.status, args.product_name)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
