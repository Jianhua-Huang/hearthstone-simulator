"""UTF-8 CLI for the headless rules prototype and independent card-data tools."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from .catalog import CardCatalog, CatalogError, DEFAULT_DATA_PATH, format_card


def positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("必须填写正整数。") from exc
    if parsed < 1:
        raise argparse.ArgumentTypeError("必须填写正整数。")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m hs_sim",
        description="传统炉石纯逻辑机制原型，以及独立的客户端卡牌数据查询工具。",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    target = commands.add_parser('target', help='校验并显示目标版本与代表卡覆盖清单')
    target.add_argument('--manifest', type=Path)
    search = commands.add_parser("search", help="按中文名、英文名或卡牌 ID 搜索")
    search.add_argument("query", help="搜索词，例如：火球术")
    search.add_argument("--limit", type=positive_int, default=10, help="最多显示条数，默认 10")
    card = commands.add_parser("card", help="按完整卡牌 ID 查询一张卡牌")
    card.add_argument("card_id", help="完整卡牌 ID，例如：CS2_029")
    for command in (search, card):
        command.add_argument("--data", type=Path, default=DEFAULT_DATA_PATH, help="抽取生成的 cards.json 路径")
    from .engine.cli import add_commands
    add_commands(commands, positive_int)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == 'target':
        import json
        from .targets import load_baseline, summarize_baseline
        try:
            baseline = load_baseline(args.manifest) if args.manifest else load_baseline()
            print(json.dumps(summarize_baseline(baseline), ensure_ascii=False, indent=2))
            return 0
        except (ValueError, OSError) as exc:
            print(f'错误：{exc}', file=sys.stderr)
            return 2
    if args.command in ('demo', 'simulate', 'replay', 'match'):
        from .engine.cli import run_command
        try:
            return run_command(args)
        except (ValueError, TypeError, OSError) as exc:
            print(f"错误：{exc}", file=sys.stderr)
            return 2
    try:
        catalog = CardCatalog.from_file(args.data)
        if args.command == "search":
            records = catalog.search(args.query, args.limit)
        else:
            record = catalog.get(args.card_id)
            records = [record] if record is not None else []
    except (CatalogError, ValueError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2

    print("数据查询：以下为客户端原始卡牌数据，不代表已实现这些卡牌的战斗效果。")
    if not records:
        print("未找到匹配卡牌。")
        return 1
    print("\n\n".join(format_card(record) for record in records))
    if args.command == "search":
        print(f"\n显示 {len(records)} 条（上限 {args.limit}）。")
    return 0


def _configure_console() -> None:
    # Python's redirected Windows streams may otherwise use a legacy code page.
    # Keep this at the process entry point, so importing main does not alter IO.
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


if __name__ == "__main__":
    _configure_console()
    raise SystemExit(main())
