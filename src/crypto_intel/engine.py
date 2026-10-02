"""Paper research engine. Live order routing is intentionally absent."""

from __future__ import annotations

import math

from crypto_intel.costs import round_trip_cost
from crypto_intel.models import Candle, ExecutionMode, PaperFill, Signal
from crypto_intel.risk import evaluate
from crypto_intel.security import AuditLog, assert_paper_only
from crypto_intel.strategies import signal_for


def run_once(
    candles: list[Candle],
    *,
    audit: AuditLog,
    kill_switch: bool = False,
    drawdown: float = 0.0,
    benchmark: list[Candle] | None = None,
    mode: ExecutionMode = ExecutionMode.PAPER,
) -> tuple[Signal, PaperFill]:
    assert_paper_only(mode)
    signal = signal_for(candles, benchmark)
    gap = 0.0
    if len(candles) >= 2 and candles[-2].close:
        gap = candles[-1].open / candles[-2].close - 1.0
    decision = evaluate(signal, kill_switch=kill_switch, drawdown=drawdown, gap_pct=gap)
    audit.append("signal", f"{signal.symbol} {signal.side.value} {signal.reason}")
    audit.append("risk", f"allowed={decision.allowed} size={decision.size_fraction:.4f} {'; '.join(decision.reasons)}")
    fill = PaperFill(
        symbol=signal.symbol,
        asset_class=signal.asset_class,
        side=signal.side if decision.allowed else signal.side,
        price=candles[-1].close,
        size_fraction=decision.size_fraction,
        reason=signal.reason if decision.allowed else "; ".join(decision.reasons),
        mode=mode,
        notes=decision.reasons,
    )
    audit.append("paper_fill", f"{fill.symbol} size={fill.size_fraction:.4f} mode={fill.mode.value}")
    return signal, fill


def backtest(candles: list[Candle], *, audit: AuditLog | None = None, slippage_mult: float = 1.0) -> dict[str, float]:
    """Walk-forward paper backtest. Cost is the declared class assumption."""
    if not math.isfinite(slippage_mult) or slippage_mult <= 0:
        raise ValueError("slippage_mult must be positive and finite")
    log = audit or AuditLog()
    equity = 1.0
    peak = 1.0
    trades = 0
    for index in range(8, len(candles) - 1):
        window = candles[: index + 1]
        drawdown = 1.0 - equity / peak
        _, fill = run_once(window, audit=log, drawdown=drawdown)
        if fill.size_fraction <= 0:
            continue
        forward = candles[index + 1].close / candles[index].close - 1.0
        pnl = fill.size_fraction * (forward - round_trip_cost(fill.asset_class) * slippage_mult)
        equity *= 1.0 + pnl
        peak = max(peak, equity)
        trades += 1
    return {
        "ending_equity": round(equity, 6),
        "trades": float(trades),
        "max_drawdown": round(1.0 - equity / peak if peak else 0.0, 6),
    }
