"""Command line for the paper research system."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from crypto_intel.briefing import build_brief
from crypto_intel.engine import backtest, run_once
from crypto_intel.market import group_by_symbol, load_candles
from crypto_intel.models import ExecutionMode
from crypto_intel.posture import Role, allow, attest_source, feed_status, mode_status
from crypto_intel.scenarios import render_markdown, run_scenarios
from crypto_intel.security import AuditLog


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="crypto-intel", description="Paper-only crypto information system")
    sub = parser.add_subparsers(dest="command", required=True)
    scan = sub.add_parser("scan", help="score the latest bar of each synthetic series")
    scan.add_argument("fixture")
    demo = sub.add_parser("demo", help="scan plus a paper backtest of the first series")
    demo.add_argument("fixture")
    bt = sub.add_parser("backtest", help="paper backtest one symbol")
    bt.add_argument("fixture")
    bt.add_argument("--symbol", required=True)
    brief = sub.add_parser("brief", help="asset-class information brief with regime and cost")
    brief.add_argument("fixture")
    posture = sub.add_parser("posture", help="security control snapshot for a fixture")
    posture.add_argument("fixture")
    scenarios = sub.add_parser("scenarios", help="run seeded synthetic paper scenarios")
    scenarios.add_argument("--seed", type=int, default=0)
    scenarios.add_argument("--runs", type=int, default=20)
    scenarios.add_argument("--json", action="store_true")
    return parser


def scan(fixture: str) -> list[dict[str, object]]:
    grouped = group_by_symbol(load_candles(fixture))
    audit = AuditLog()
    rows: list[dict[str, object]] = []
    benchmark = grouped.get("ETH-USD")
    for symbol, series in grouped.items():
        _, fill = run_once(series, audit=audit, benchmark=benchmark if symbol != "ETH-USD" else None)
        rows.append(
            {
                "symbol": symbol,
                "asset_class": fill.asset_class.value,
                "side": fill.side.value,
                "size_fraction": fill.size_fraction,
                "reason": fill.reason,
                "mode": fill.mode.value,
            }
        )
    if not audit.verify():
        raise RuntimeError("audit chain failed verification")
    return rows


def posture(fixture: str) -> dict[str, object]:
    path_text = Path(fixture).read_text(encoding="utf-8")
    payload = json.loads(path_text)
    digest = attest_source(str(payload.get("label")), path_text)
    grouped = group_by_symbol(load_candles(fixture))
    first = next(iter(grouped.values()))
    previous = first[-2].close if len(first) > 1 else None
    feed = feed_status(first[-1].close, previous, age_seconds=0)
    mode = mode_status(ExecutionMode.PAPER)
    return {
        "source_attestation": digest,
        "label": payload.get("label"),
        "paper_only": mode.ok,
        "feed": feed.detail,
        "feed_ok": feed.ok,
        "researcher_can_scan": allow(Role.RESEARCHER, "scan"),
        "operator_can_trade": allow(Role.OPERATOR, "place_order"),
        "live_enabled": False,
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command in {"scan", "demo"}:
        rows = scan(args.fixture)
        print(json.dumps(rows, indent=2))
        if args.command == "demo":
            grouped = group_by_symbol(load_candles(args.fixture))
            first = next(iter(grouped.values()))
            print(json.dumps(backtest(first), indent=2))
        return 0
    if args.command == "brief":
        grouped = group_by_symbol(load_candles(args.fixture))
        print(json.dumps(build_brief(grouped), indent=2))
        return 0
    if args.command == "posture":
        print(json.dumps(posture(args.fixture), indent=2))
        return 0
    if args.command == "scenarios":
        report = run_scenarios(seed=args.seed, runs=args.runs)
        print(json.dumps(report, indent=2) if args.json else render_markdown(report))
        return 0
    grouped = group_by_symbol(load_candles(args.fixture))
    if args.symbol not in grouped:
        raise SystemExit(f"unknown symbol {args.symbol}")
    print(json.dumps(backtest(grouped[args.symbol]), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
