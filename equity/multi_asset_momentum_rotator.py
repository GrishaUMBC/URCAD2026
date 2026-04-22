#!/usr/bin/env python3
"""
Multi-Asset Momentum Rotator — Alpaca PAPER trading
====================================================

PAPER TRADING ONLY. NOT FINANCIAL ADVICE. SEE DISCLAIMER.md.

Strategy
--------
Scans a basket of liquid ETFs every REBALANCE_INTERVAL seconds, ranks them
by short-term momentum (rate of change over MOMENTUM_LOOKBACK seconds), and
holds the top TOP_N most-positively-trending names with equal-weight
notional.  Anything not in the top set is liquidated.

Universe is fixed and customizable below — defaults are large-cap sector
ETFs that all have tight spreads and strong intraday liquidity.

Why this is interesting
-----------------------
This is a "frequently updates positions" strategy: it actively rebalances
across the universe instead of running a single-symbol bot.  It demonstrates
how to manage a small portfolio rather than a single open position.
"""

from __future__ import annotations

import signal as sigmod
import sys
import time
from collections import deque
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common import alpaca_rest as ax
from common.indicators import linreg_slope
from common.logging_setup import configure

log = configure("multi_asset_momentum_rotator")

# ────────────────────────── parameters ──────────────────────────────
UNIVERSE             = ["SPY", "QQQ", "IWM", "DIA", "XLF", "XLE", "XLK", "XLV"]
TOP_N                = 3        # hold the top-3 momentum names
REBALANCE_INTERVAL   = 30       # seconds between rebalances
MOMENTUM_LOOKBACK    = 12       # samples (≈6 min @ 30s) for slope calc
NOTIONAL_PER_NAME_PCT = 0.10    # 10% of equity per held name
MIN_SLOPE_TO_HOLD    = 0.0      # skip names whose slope is non-positive
MAX_DAILY_LOSS_PCT   = 0.025

MARKET_OPEN_HM       = (9, 35)
MARKET_CLOSE_HM      = (15, 45)


def fetch_prices(symbols: list[str]) -> dict[str, float]:
    out = {}
    for s in symbols:
        try:
            out[s] = ax.get_stock_latest_trade(s)
        except Exception as e:
            log.warning("price fetch %s: %s", s, e)
    return out


def rank_by_momentum(history: dict[str, deque]) -> list[tuple[str, float]]:
    scored = []
    for sym, h in history.items():
        if len(h) < MOMENTUM_LOOKBACK:
            continue
        slope = linreg_slope(np.array(h, dtype=float), MOMENTUM_LOOKBACK)
        # normalise by price so slope is comparable across $20 vs $500 names
        norm  = slope / float(h[-1]) if h[-1] else 0.0
        scored.append((sym, norm))
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored


def current_holdings() -> dict[str, float]:
    """Return {symbol: qty} for the symbols in our universe."""
    out = {}
    try:
        positions = ax.get_positions()
    except Exception as e:
        log.warning("get_positions: %s", e)
        return out
    for p in positions:
        sym = p.get("symbol")
        if sym in UNIVERSE:
            out[sym] = float(p.get("qty", 0))
    return out


def rebalance(target_set: set[str], notional: float):
    held = current_holdings()

    # 1. liquidate anything not in target_set
    for sym, qty in held.items():
        if sym not in target_set and abs(qty) > 0:
            log.info("LIQUIDATE %s qty=%.4f", sym, qty)
            try:
                ax.close_position(sym)
            except Exception as e:
                log.warning("liquidate %s: %s", sym, e)

    # 2. buy into anything in target_set we don't already hold
    for sym in target_set:
        if held.get(sym, 0) <= 0:
            try:
                log.info("BUY %s notional=$%.2f", sym, notional)
                ax.submit_market_notional(sym, notional, "buy")
            except Exception as e:
                log.warning("buy %s: %s", sym, e)


def main():
    log.info("=" * 70)
    log.info("Multi-Asset Momentum Rotator  |  paper  |  universe=%s",
             ",".join(UNIVERSE))
    log.info("Top-%d  rebalance=%ds  lookback=%d  notional/name=%.0f%%",
             TOP_N, REBALANCE_INTERVAL, MOMENTUM_LOOKBACK,
             NOTIONAL_PER_NAME_PCT * 100)

    start_equity = float(ax.get_account()["equity"])
    log.info("Equity $%.2f", start_equity)

    history: dict[str, deque] = {s: deque(maxlen=MOMENTUM_LOOKBACK + 5)
                                 for s in UNIVERSE}

    def shutdown(*_):
        log.info("Shutdown — closing all positions in universe")
        for s in UNIVERSE:
            ax.close_position(s)
        sys.exit(0)

    sigmod.signal(sigmod.SIGINT,  shutdown)
    sigmod.signal(sigmod.SIGTERM, shutdown)

    while True:
        cycle = time.time()
        try:
            if not ax.in_market_window(*MARKET_OPEN_HM, *MARKET_CLOSE_HM):
                log.info("Outside trading window — flattening universe and exiting")
                for s in UNIVERSE:
                    ax.close_position(s)
                shutdown()

            equity = float(ax.get_account()["equity"])
            if (start_equity - equity) / start_equity > MAX_DAILY_LOSS_PCT:
                log.warning("DAILY LOSS LIMIT — halting")
                shutdown()

            prices = fetch_prices(UNIVERSE)
            for s, p in prices.items():
                history[s].append(p)

            scored = rank_by_momentum(history)
            log.info("RANK: %s",
                     "  ".join(f"{s}={v*100:+.4f}%" for s, v in scored[:6]))

            target = {s for s, v in scored[:TOP_N] if v > MIN_SLOPE_TO_HOLD}
            log.info("TARGET HOLDINGS: %s", sorted(target) or "[none — all flat]")

            notional = equity * NOTIONAL_PER_NAME_PCT
            rebalance(target, notional)

        except Exception as e:
            log.exception("loop error: %s", e)

        elapsed = time.time() - cycle
        time.sleep(max(1.0, REBALANCE_INTERVAL - elapsed))


if __name__ == "__main__":
    main()
