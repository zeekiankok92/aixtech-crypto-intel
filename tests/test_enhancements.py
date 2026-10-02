from pathlib import Path

import pytest

from crypto_intel.briefing import build_brief
from crypto_intel.cli import main
from crypto_intel.costs import round_trip_cost
from crypto_intel.market import group_by_symbol, load_candles
from crypto_intel.models import AssetClass, ExecutionMode
from crypto_intel.posture import Role, Severity, allow, attest_source, feed_status, refuse_trade_secret
from crypto_intel.regime import Regime, classify
from crypto_intel.strategies import PLAYBOOK, signal_for

FIXTURE = Path(__file__).parents[1] / "fixtures" / "candles_synthetic.json"


def test_playbook_covers_every_class():
    assert set(PLAYBOOK) == set(AssetClass)
    for card in PLAYBOOK.values():
        assert {"hypothesis", "entry", "invalidation", "horizon"} <= set(card)


def test_regime_and_cost_are_class_aware():
    grouped = group_by_symbol(load_candles(FIXTURE))
    assert classify(grouped["BTC-USD"]) in {Regime.TREND, Regime.RANGE, Regime.STRESS}
    assert round_trip_cost(AssetClass.MEME) > round_trip_cost(AssetClass.MAJOR)
    assert round_trip_cost(AssetClass.STABLECOIN) < round_trip_cost(AssetClass.DEFI)


def test_stress_major_stands_aside():
    series = group_by_symbol(load_candles(FIXTURE))["BTC-USD"]
    stressed = []
    for candle in series:
        stressed.append(
            type(candle)(
                candle.symbol,
                candle.asset_class,
                candle.timestamp,
                candle.open,
                candle.close * 1.08,
                candle.close * 0.92,
                candle.close,
                candle.volume,
                candle.funding_rate,
            )
        )
    signal = signal_for(stressed)
    assert signal.side.value == "flat"
    assert "stress" in signal.reason


def test_brief_and_posture_commands(capsys):
    grouped = group_by_symbol(load_candles(FIXTURE))
    brief = build_brief(grouped)
    assert brief["mode"] == "paper"
    assert brief["audit_ok"] is True
    assert brief["symbols"] == len(grouped)
    assert main(["brief", str(FIXTURE)]) == 0
    assert main(["posture", str(FIXTURE)]) == 0
    out = capsys.readouterr().out
    assert "source_attestation" in out
    assert "operator_can_trade" in out


def test_security_posture_refuses_trade_paths():
    assert len(attest_source("SYNTHETIC", "fixture")) == 64
    assert len(attest_source("PUBLIC_READ", "ticker")) == 64
    with pytest.raises(PermissionError):
        refuse_trade_secret("exchange_trade_key")
    with pytest.raises(ValueError):
        attest_source("LIVE", "nope")
    assert allow(Role.OPERATOR, "place_order") is False
    assert allow(Role.AUDITOR, "verify_chain") is True
    stale = feed_status(10.0, 10.0, age_seconds=1000)
    assert stale.ok is False
    assert stale.severity is Severity.WATCH
    jump = feed_status(20.0, 10.0, age_seconds=1)
    assert jump.severity is Severity.HIGH
    assert feed_status(10.0, 10.1, 1).ok is True
    assert ExecutionMode.PAPER.value == "paper"
