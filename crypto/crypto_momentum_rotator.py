#!/usr/bin/env python3
"""
Crypto Momentum Rotator — Alpaca PAPER trading
==============================================

PAPER TRADING ONLY. NOT FINANCIAL ADVICE. SEE DISCLAIMER.md.

Strategy
--------
Crypto twin of `equity/multi_asset_momentum_rotator.py`. Polls a fixed
universe of crypto pairs every REBALANCE_INTERVAL seconds, ranks by
short-term price slope, holds the top-N most positively trending names
with equal-weight notional, and liquidates anything that drops out.

Universe defaults to the most-liquid Alpaca crypto pairs. Adjust as
needed — make sure each pair is supported by your paper account.

Crypto-specific caveats:
  - 24/7 — set MAX_RUN_HOURS so the bot self-terminates.
  - No shorting on Alpaca paper crypto, so the rotator is long-only.
  - Trades a notional minimum (some pairs require ≥$1).
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

log = configure("crypto_momentum_rotator")

# ────────────────────── parameters ────────────────────────
UNIVERSE             = ["BTC/USD", "ETH/USD", "SOL/USD", "AVAX/USD",
                        "LINK/USD", "DOGE/USD", "LTC/USD", "BCH/USD"]
TOP_N                = 3
REBALANCE_INTERVAL   = 30
MOMENTUM_LOOKBACK    = 12
NOTIONAL_PER_NAME_PCT = 0.08
MIN_SLOPE_TO_HOLD    = 0.0
MAX_DAILY_LOSS_PCT   = 0.03
MAX_RUN_HOURS        = 6


def fetch_prices(symbols):
    out = {}
    for s in symbols:
        try:
            out[s] = ax.get_crypto_latest_trade(s)
        except Exception as e:
            log.warning("price %s: %s", s, e)
    return out


def rank_by_momentum(history):
    scored = []
    for sym, h in history.items():
        if len(h) < MOMENTUM_LOOKBACK: continue
        slope = linreg_slope(np.array(h, dtype=float), MOMENTUM_LOOKBACK)
        norm = slope / float(h[-1]) if h[-1] else 0.0
        scored.append((sym, norm))
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored


def current_holdings():
    out = {}
    try:
        for p in ax.get_positions():
            sym = p.get("symbol")
            # Alpaca returns crypto symbols without slash — normalise both ways
            if sym and (sym in UNIVERSE or sym.replace("USD", "/USD") in UNIVERSE):
                key = sym if sym in UNIVERSE else sym.replace("USD", "/USD")
                out[key] = float(p.get("qty", 0))
    except Exception as e:
        log.warning("get_positions: %s", e)
    return out


def rebalance(target_set, notional):
    held = current_holdings()
    for sym, qty in held.items():
        if sym not in target_set and abs(qty) > 0:
            log.info("LIQUIDATE %s qty=%.6f", sym, qty)
            try: ax.close_position(sym)
            except Exception as e: log.warning("liq %s: %s", sym, e)
    for sym in target_set:
        if held.get(sym, 0) <= 0:
            try:
                log.info("BUY %s notional=$%.2f", sym, notional)
                ax.submit_market_notional(sym, notional, "buy")
            except Exception as e:
                log.warning("buy %s: %s", sym, e)


def main():
    log.info("=" * 70)
    log.info("Crypto Momentum Rotator  |  paper  |  universe=%s",
             ",".join(UNIVERSE))
    log.info("Top-%d  rebalance=%ds  max_run=%dh",
             TOP_N, REBALANCE_INTERVAL, MAX_RUN_HOURS)

    start_equity = float(ax.get_account()["equity"])
    started_at = time.time()
    history = {s: deque(maxlen=MOMENTUM_LOOKBACK + 5) for s in UNIVERSE}

    def shutdown(*_):
        log.info("Shutdown — closing universe")
        for s in UNIVERSE: ax.close_position(s)
        sys.exit(0)

    sigmod.signal(sigmod.SIGINT,  shutdown)
    sigmod.signal(sigmod.SIGTERM, shutdown)

    while True:
        t0 = time.time()
        try:
            if (time.time() - started_at) / 3600 >= MAX_RUN_HOURS:
                log.info("MAX_RUN_HOURS reached"); shutdown()

            equity = float(ax.get_account()["equity"])
            if (start_equity - equity) / start_equity > MAX_DAILY_LOSS_PCT:
                log.warning("DAILY LOSS LIMIT — halting"); shutdown()

            prices = fetch_prices(UNIVERSE)
            for s, p in prices.items(): history[s].append(p)

            scored = rank_by_momentum(history)
            log.info("RANK: %s",
                     "  ".join(f"{s}={v*100:+.4f}%" for s, v in scored[:6]))

            target = {s for s, v in scored[:TOP_N] if v > MIN_SLOPE_TO_HOLD}
            log.info("TARGET: %s", sorted(target) or "[none]")
            rebalance(target, equity * NOTIONAL_PER_NAME_PCT)

        except Exception as e:
            log.exception("loop error: %s", e)

        time.sleep(max(1.0, REBALANCE_INTERVAL - (time.time() - t0)))


if __name__ == "__main__":
    main()
