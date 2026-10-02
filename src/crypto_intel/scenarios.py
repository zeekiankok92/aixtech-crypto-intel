"""Seeded synthetic market scenarios for paper-only research."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from statistics import fmean
from typing import Any

from crypto_intel.engine import backtest
from crypto_intel.market import group_by_symbol, load_candles
from crypto_intel.models import AssetClass, Candle


@dataclass(frozen=True)
class Scenario:
    name: str
    daily_mu: float
    daily_sigma: float
    slippage_mult: float
    perp_funding: float
    stable_peg: float
    weight: float


SCENARIOS = (
    Scenario("OPTIMISTIC", 0.0015, 0.03, 1.0, 0.0001, 1.0, 0.25),
    Scenario("NEUTRAL", 0.0, 0.035, 1.5, 0.0, 0.998, 0.50),
    Scenario("PESSIMISTIC", -0.002, 0.055, 3.0, -0.0008, 0.99, 0.25),
)
DAYS = 90
INITIAL_EQUITY = 10_000.0
SCENARIO_DRAWDOWN_LIMIT = 0.20
DISCLAIMER = "SYNTHETIC / PAPER ONLY / NOT ADVICE"
DEFAULT_FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "candles_synthetic.json"


def _generate_path(template: list[Candle], scenario: Scenario, rng: random.Random) -> list[Candle]:
    first = template[0]
    if first.asset_class is AssetClass.STABLECOIN:
        return [
            Candle(
                first.symbol,
                first.asset_class,
                (date(2026, 1, 1) + timedelta(days=day)).isoformat(),
                scenario.stable_peg,
                scenario.stable_peg,
                scenario.stable_peg,
                scenario.stable_peg,
                first.volume,
            )
            for day in range(DAYS)
        ]

    previous = first.close
    candles = []
    for day in range(DAYS):
        open_price = previous
        daily_return = math.exp(
            scenario.daily_mu - 0.5 * scenario.daily_sigma**2 + scenario.daily_sigma * rng.gauss(0.0, 1.0)
        )
        close = open_price * daily_return
        wick = rng.uniform(0.0, scenario.daily_sigma * 0.5)
        high = max(open_price, close) * math.exp(wick)
        low = min(open_price, close) * math.exp(-wick)
        candles.append(
            Candle(
                first.symbol,
                first.asset_class,
                (date(2026, 1, 1) + timedelta(days=day)).isoformat(),
                open_price,
                high,
                low,
                close,
                max(first.volume * math.exp(rng.gauss(0.0, 0.1)), 1.0),
                scenario.perp_funding if first.asset_class is AssetClass.PERPETUAL else 0.0,
            )
        )
        previous = close
    return candles


def _interpolated_percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _aggregate(results: list[dict[str, Any]], runs: int) -> dict[str, Any]:
    returns = [result["return_pct"] for result in results]
    return {
        "ending_equity": fmean(result["ending_equity"] for result in results),
        "return_pct": fmean(returns),
        "mean_return_pct": fmean(returns),
        "return_p05_pct": _interpolated_percentile(returns, 0.05),
        "return_p95_pct": _interpolated_percentile(returns, 0.95),
        "max_drawdown_pct": fmean(result["max_drawdown_pct"] for result in results),
        "trades": fmean(result["trades"] for result in results),
        "halts": fmean(result["halts"] for result in results),
        "asset_classes": {
            asset_class: {
                key: fmean(result["asset_classes"][asset_class][key] for result in results)
                for key in ("ending_equity", "return_pct", "max_drawdown_pct", "trades", "halts")
            }
            for asset_class in results[0]["asset_classes"]
        },
        "runs": runs,
    }


def _simulate_scenario(
    scenario: Scenario,
    seed: int,
    fixture: str | Path,
) -> dict[str, Any]:
    grouped = group_by_symbol(load_candles(fixture))
    rng = random.Random(seed)  # noqa: S311 - deterministic synthetic paths require a seeded PRNG
    paths = {symbol: _generate_path(series, scenario, rng) for symbol, series in grouped.items()}
    benchmark = paths.get("ETH-USD")
    allocation = INITIAL_EQUITY / len(paths)
    portfolio_equity = 0.0
    portfolio_drawdown = 0.0
    total_trades = 0.0
    total_halts = 0.0
    class_totals: dict[str, dict[str, float]] = {}

    for symbol, candles in paths.items():
        result = backtest(
            candles,
            slippage_mult=scenario.slippage_mult,
            max_drawdown=SCENARIO_DRAWDOWN_LIMIT,
            benchmark=benchmark if symbol != "ETH-USD" else None,
        )
        ending_equity = allocation * result["ending_equity"]
        portfolio_equity += ending_equity
        portfolio_drawdown += allocation * result["max_drawdown"]
        total_trades += result["trades"]
        total_halts += result["halts"]
        asset_class = candles[0].asset_class.value
        totals = class_totals.setdefault(
            asset_class,
            {
                "starting_equity": 0.0,
                "ending_equity": 0.0,
                "max_drawdown_pct": 0.0,
                "trades": 0.0,
                "halts": 0.0,
            },
        )
        totals["starting_equity"] += allocation
        totals["ending_equity"] += ending_equity
        totals["max_drawdown_pct"] += allocation * result["max_drawdown"]
        totals["trades"] += result["trades"]
        totals["halts"] += result["halts"]

    for totals in class_totals.values():
        totals["return_pct"] = (totals["ending_equity"] / totals["starting_equity"] - 1.0) * 100.0
        totals["max_drawdown_pct"] = totals["max_drawdown_pct"] / totals["starting_equity"] * 100.0
        del totals["starting_equity"]

    return {
        "ending_equity": portfolio_equity,
        "return_pct": (portfolio_equity / INITIAL_EQUITY - 1.0) * 100.0,
        "max_drawdown_pct": portfolio_drawdown / INITIAL_EQUITY * 100.0,
        "trades": total_trades,
        "halts": total_halts,
        "asset_classes": class_totals,
    }


def run_scenarios(
    *,
    seed: int = 0,
    runs: int = 20,
    fixture: str | Path = DEFAULT_FIXTURE,
) -> dict[str, Any]:
    """Average deterministic 90-day, equal-weight paper scenarios over seeded runs."""
    if runs < 1:
        raise ValueError("runs must be at least 1")
    if not SCENARIOS or not math.isclose(sum(scenario.weight for scenario in SCENARIOS), 1.0):
        raise ValueError("scenario weights must sum to 1")

    rows = []
    for scenario in SCENARIOS:
        aggregate = _aggregate(
            [_simulate_scenario(scenario, seed + run, fixture) for run in range(runs)],
            runs,
        )
        rows.append(
            {
                "name": scenario.name,
                "weight": scenario.weight,
                "daily_mu": scenario.daily_mu,
                "daily_sigma": scenario.daily_sigma,
                "slippage_mult": scenario.slippage_mult,
                "perp_funding_per_bar": scenario.perp_funding,
                "stable_peg": scenario.stable_peg,
                **aggregate,
            }
        )

    return {
        "disclaimer": DISCLAIMER,
        "seed": seed,
        "runs": runs,
        "expected_return_pct": sum(row["weight"] * row["mean_return_pct"] for row in rows),
        "scenarios": rows,
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        f"**{report['disclaimer']}**",
        "",
        f"Seed: `{report['seed']}` · Runs: `{report['runs']}` · "
        f"Probability-weighted expected return: **{report['expected_return_pct']:.2f}%**",
        "",
        "| Scenario | Weight | Ending equity | Return | Mean return (5th–95th) | Max drawdown | Trades | Halts |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in report["scenarios"]:
        lines.append(
            f"| {row['name']} | {row['weight']:.0%} | ${row['ending_equity']:,.2f} | "
            f"{row['return_pct']:.2f}% | {row['mean_return_pct']:.2f}% "
            f"({row['return_p05_pct']:.2f}%–{row['return_p95_pct']:.2f}%) | "
            f"{row['max_drawdown_pct']:.2f}% | {row['trades']:.1f} | {row['halts']:.1f} |"
        )
    lines.extend(["", "Per-asset-class breakdown (mean across runs):", ""])
    for row in report["scenarios"]:
        lines.extend(
            [
                f"**{row['name']}**",
                "",
                "| Asset class | Ending equity | Return | Max drawdown | Trades | Halts |",
                "|---|---:|---:|---:|---:|---:|",
            ]
        )
        for asset_class, values in row["asset_classes"].items():
            lines.append(
                f"| {asset_class} | ${values['ending_equity']:,.2f} | {values['return_pct']:.2f}% | "
                f"{values['max_drawdown_pct']:.2f}% | {values['trades']:.1f} | {values['halts']:.1f} |"
            )
        lines.append("")
    return "\n".join(lines).rstrip()
