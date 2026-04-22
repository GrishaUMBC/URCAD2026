#!/usr/bin/env python3
"""
Crypto Z-Score Mean-Reversion — Alpaca PAPER trading
=====================================================

PAPER TRADING ONLY. NOT FINANCIAL ADVICE. SEE DISCLAIMER.md.

Strategy
--------
Per-pair contrarian: when a coin's recent log-return distribution is
stretched far below its rolling mean (z ≤ -ENTRY_Z), buy and wait for
mean-reversion back toward |z| ≤ EXIT_Z.

Long-only (Alpaca paper crypto does not support shorting), so this only
takes the "oversold bounce" side. Skips long-z entries.

Designed to run alongside (or instead of) `crypto_momentum_rotator.py`
since the two strategies have opposite directional biases.
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
from common.indicators import zscore
from common.logging_setup import configure

log = configure("crypto_zscore_mean_reversion")

# ────────────────────── parameters ────────────────────────
UNIVERSE            = ["BTC/USD", "ETH/USD", "SOL/USD",
                       "AVAX/USD", "LINK/USD", "LTC/USD"]
POLL_INTERVAL       = 10
LOOKBACK            = 60
ENTRY_Z             = 1.8
EXIT_Z              = 0.5
NOTIONAL_PER_NAME   = 0.06
MAX_OPEN_LEGS       = 3
MAX_DAILY_LOSS_PCT  = 0.025
MAX_RUN_HOURS       = 6


class Leg:
    __slots__ = ("symbol", "qty", "entry_price")
    def __init__(self, symbol, qty, entry_price):
        self.symbol = symbol; self.qty = qty; self.entry_price = entry_price


def main():
    log.info("=" * 70)
    log.info("Crypto Z-Score Mean-Reversion  |  paper")
    log.info("Universe=%s  ENTRY_Z=%.2f  EXIT_Z=%.2f", ",".join(UNIVERSE),
             ENTRY_Z, EXIT_Z)

    start_equity = float(ax.get_account()["equity"])
    started_at = time.time()
    history = {s: deque(maxlen=LOOKBACK + 10) for s in UNIVERSE}
    legs: dict[str, Leg] = {}

    def flatten_all():
        for s in list(legs.keys()):
            ax.close_position(s)
        legs.clear()

    def shutdown(*_):
        log.info("Shutdown — closing legs"); flatten_all(); sys.exit(0)

    sigmod.signal(sigmod.SIGINT,  shutdown)
    sigmod.signal(sigmod.SIGTERM, shutdown)

    while True:
        t0 = time.time()
        try:
            if (time.time() - started_at) / 3600 >= MAX_RUN_HOURS:
                log.info("MAX_RUN_HOURS reached"); flatten_all(); shutdown()

            equity = float(ax.get_account()["equity"])
            if (start_equity - equity) / start_equity > MAX_DAILY_LOSS_PCT:
                log.warning("DAILY LOSS LIMIT — halting"); flatten_all(); shutdown()

            for sym in UNIVERSE:
                try: p = ax.get_crypto_latest_trade(sym)
                except Exception as e:
                    log.warning("price %s: %s", sym, e); continue
                history[sym].append(p)
                if len(history[sym]) < LOOKBACK + 1: continue

                arr = np.array(history[sym], dtype=float)
                rets = np.diff(np.log(arr))
                z = zscore(rets, LOOKBACK)
                in_leg = sym in legs

                if in_leg and abs(z) <= EXIT_Z:
                    leg = legs.pop(sym)
                    log.info("EXIT %s qty=%.6f entry=%.2f exit=%.2f z=%+.2f",
                             sym, leg.qty, leg.entry_price, p, z)
                    ax.close_position(sym)
                    continue

                if not in_leg and len(legs) < MAX_OPEN_LEGS and z <= -ENTRY_Z:
                    notional = equity * NOTIONAL_PER_NAME
                    if notional < 5: continue
                    log.info(">>> LONG %s notional=$%.2f z=%+.2f price=%.2f",
                             sym, notional, z, p)
                    ax.submit_market_notional(sym, notional, "buy")
                    legs[sym] = Leg(sym, notional / p, p)

            log.info("OPEN LEGS (%d): %s", len(legs),
                     ", ".join(legs.keys()) or "[none]")

        except Exception as e:
            log.exception("loop error: %s", e)

        time.sleep(max(1.0, POLL_INTERVAL - (time.time() - t0)))


if __name__ == "__main__":
    main()
