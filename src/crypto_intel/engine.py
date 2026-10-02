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
    max_drawdown: float = 0.12,
    benchmark: list[Candle] | None = None,
    mode: ExecutionMode = ExecutionMode.PAPER,
) -> tuple[Signal, PaperFill]:
    assert_paper_only(mode)
    signal = signal_for(candles, benchmark)
    gap = 0.0
    if len(candles) >= 2 and candles[-2].close:
        gap = candles[-1].open / candles[-2].close - 1.0
    decision = evaluate(
        signal,
        kill_switch=kill_switch,
        drawdown=drawdown,
        max_drawdown=max_drawdown,
        gap_pct=gap,
    )
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


def backtest(
    candles: list[Candle],
    *,
    audit: AuditLog | None = None,
    slippage_mult: float = 1.0,
    max_drawdown: float = 0.12,
    benchmark: list[Candle] | None = None,
) -> dict[str, float]:
    """Walk-forward paper backtest. Cost is the declared class assumption."""
    if not math.isfinite(slippage_mult) or slippage_mult <= 0:
        raise ValueError("slippage_mult must be positive and finite")
    if not math.isfinite(max_drawdown) or not 0 < max_drawdown <= 1:
        raise ValueError("max_drawdown must be positive, finite, and at most 1")
    log = audit or AuditLog()
    equity = 1.0
    peak = 1.0
    worst_drawdown = 0.0
    trades = 0
    halts = 0
    for index in range(8, len(candles) - 1):
        window = candles[: index + 1]
        drawdown = 1.0 - equity / peak
        if drawdown >= max_drawdown:
            halts += 1
            break
        _, fill = run_once(
            window,
            audit=log,
            drawdown=drawdown,
            max_drawdown=max_drawdown,
            benchmark=benchmark[: index + 1] if benchmark is not None else None,
        )
        if fill.size_fraction <= 0:
            continue
        forward = candles[index + 1].close / candles[index].close - 1.0
        funding = abs(candles[index + 1].funding_rate) if fill.side is not None else 0.0
        if fill.side.value == "long":
            funding_pnl = -funding * fill.size_fraction
        else:
            funding_pnl = funding * fill.size_fraction
        pnl = fill.size_fraction * (forward - round_trip_cost(fill.asset_class) * slippage_mult) + funding_pnl
        equity *= 1.0 + pnl
        peak = max(peak, equity)
        worst_drawdown = max(worst_drawdown, 1.0 - equity / peak)
        trades += 1
    return {
        "ending_equity": round(equity, 6),
        "trades": float(trades),
        "max_drawdown": round(worst_drawdown, 6),
        "halts": float(halts),
    }
