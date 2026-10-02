from pathlib import Path

from crypto_intel.cli import main

FIXTURE = Path(__file__).parents[1] / "fixtures" / "candles_synthetic.json"


def test_cli_scan(capsys):
    assert main(["scan", str(FIXTURE)]) == 0
    out = capsys.readouterr().out
    assert "BTC-USD" in out
    assert "paper" in out


def test_cli_backtest(capsys):
    assert main(["backtest", str(FIXTURE), "--symbol", "ETH-USD"]) == 0
    assert "ending_equity" in capsys.readouterr().out


def test_cli_scenarios_markdown_and_json(capsys):
    assert main(["scenarios", "--seed", "3", "--runs", "1"]) == 0
    assert "SYNTHETIC / PAPER ONLY / NOT ADVICE" in capsys.readouterr().out
    assert main(["scenarios", "--seed", "3", "--runs", "1", "--json"]) == 0
    assert '"expected_return_pct"' in capsys.readouterr().out
