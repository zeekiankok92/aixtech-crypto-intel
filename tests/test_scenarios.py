from pathlib import Path

import pytest

from crypto_intel.scenarios import (
    SCENARIO_DRAWDOWN_LIMIT,
    SCENARIOS,
    run_scenarios,
)

FIXTURE = Path(__file__).parents[1] / "fixtures" / "candles_synthetic.json"
DRAWDOWN_TOLERANCE_PCT = 1.0


def test_same_seed_produces_identical_output():
    first = run_scenarios(seed=17, runs=1, fixture=FIXTURE)
    second = run_scenarios(seed=17, runs=1, fixture=FIXTURE)
    assert first == second


def test_scenario_mean_returns_follow_assumptions():
    report = run_scenarios(seed=1, runs=500, fixture=FIXTURE)
    returns = {scenario["name"]: scenario["mean_return_pct"] for scenario in report["scenarios"]}
    assert returns["OPTIMISTIC"] >= returns["NEUTRAL"] >= returns["PESSIMISTIC"]


def test_pessimistic_drawdown_respects_scenario_halt():
    report = run_scenarios(seed=47, runs=4, fixture=FIXTURE)
    pessimistic = next(row for row in report["scenarios"] if row["name"] == "PESSIMISTIC")
    # Daily close gaps can move the realized drawdown slightly past the halt threshold.
    assert pessimistic["max_drawdown_pct"] <= SCENARIO_DRAWDOWN_LIMIT * 100 + DRAWDOWN_TOLERANCE_PCT


def test_stablecoins_never_trade():
    report = run_scenarios(seed=53, runs=2, fixture=FIXTURE)
    for scenario in report["scenarios"]:
        assert scenario["asset_classes"]["stablecoin"]["trades"] == 0


def test_scenario_weights_sum_to_one():
    assert sum(scenario.weight for scenario in SCENARIOS) == pytest.approx(1.0)
