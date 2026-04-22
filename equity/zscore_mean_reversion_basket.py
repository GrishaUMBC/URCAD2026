#!/usr/bin/env python3
"""
Z-Score Mean-Reversion on Sector ETF Basket — Alpaca PAPER trading
==================================================================

PAPER TRADING ONLY. NOT FINANCIAL ADVICE. SEE DISCLAIMER.md.

Strategy
--------
For each ETF in a basket of sector funds, compute a rolling z-score of its
log-return sequence over a long lookback. When a name's z-score gets
extreme (|z| ≥ ENTRY_Z), open a *contrarian* position betting on reversion.

Every POLL_INTERVAL seconds:
  - Update each symbol's price buffer
  - Compute z-score of recent log returns vs lookback
  - Open / close per-symbol positions independently

This is a multi-leg strategy: it can be holding positions in several
sectors simultaneously, each with its own thesis. Position state is held
in-memory; on shutdown, every open name is flattened.
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

log = configure("zscore_mean_reversion_basket")

# ────────────────────── parameters ────────────────────────
BASKET             = ["XLF", "XLE", "XLK", "XLV", "XLY", "XLP", "XLI", "XLU"]
POLL_INTERVAL      = 10
LOOKBACK           = 60        # samples for z-score
ENTRY_Z            = 1.8       # contrarian entry threshold
EXIT_Z             = 0.5       # close when within this band
NOTIONAL_PER_NAME  = 0.06      # 6% of equity per active leg
MAX_OPEN_LEGS      = 4
ALLOW_SHORTS       = False
MAX_DAILY_LOSS_PCT = 0.025

MARKET_OPEN_HM     = (9, 35)
MARKET_CLOSE_HM    = (15, 45)


class Leg:
    __slots__ = ("symbol", "side", "qty", "entry_price")
    def __init__(self, symbol, side, qty, entry_price):
        self.symbol = symbol
        self.side = side
        self.qty = qty
        self.entry_price = entry_price


def main():
    log.info("=" * 70)
    log.info("Z-Score Mean-Reversion Basket  |  paper")
    log.info("Basket=%s  ENTRY_Z=±%.2f  EXIT_Z=±%.2f  max_legs=%d",
             ",".join(BASKET), ENTRY_Z, EXIT_Z, MAX_OPEN_LEGS)

    start_equity = float(ax.get_account()["equity"])

    history: dict[str, deque] = {s: deque(maxlen=LOOKBACK + 10) for s in BASKET}
    legs: dict[str, Leg] = {}

    def flatten_all():
        for s in list(legs.keys()):
            ax.close_position(s)
        legs.clear()

    def shutdown(*_):
        log.info("Shutdown — closing all open legs")
        flatten_all()
        sys.exit(0)

    sigmod.signal(sigmod.SIGINT,  shutdown)
    sigmod.signal(sigmod.SIGTERM, shutdown)

    while True:
        t0 = time.time()
        try:
            if not ax.in_market_window(*MARKET_OPEN_HM, *MARKET_CLOSE_HM):
                log.info("Outside window — flattening and exiting")
                flatten_all(); shutdown()

            equity = float(ax.get_account()["equity"])
            if (start_equity - equity) / start_equity > MAX_DAILY_LOSS_PCT:
                log.warning("DAILY LOSS LIMIT — halting"); flatten_all(); shutdown()

            for sym in BASKET:
                try:
                    p = ax.get_stock_latest_trade(sym)
                except Exception as e:
                    log.warning("price %s: %s", sym, e); continue
                history[sym].append(p)

                if len(history[sym]) < LOOKBACK + 1:
                    continue

                arr = np.array(history[sym], dtype=float)
                returns = np.diff(np.log(arr))
                z = zscore(returns, LOOKBACK)

                in_leg = sym in legs

                # ── exit ──────────────────────
                if in_leg and abs(z) <= EXIT_Z:
                    leg = legs.pop(sym)
                    pnl_per_share = (p - leg.entry_price) * (1 if leg.side == "long" else -1)
                    log.info("EXIT %s %s qty=%.4f entry=%.2f exit=%.2f pnl/sh=$%+.4f z=%+.2f",
                             sym, leg.side, leg.qty, leg.entry_price, p, pnl_per_share, z)
                    ax.close_position(sym)
                    continue

                # ── entry ─────────────────────
                if not in_leg and len(legs) < MAX_OPEN_LEGS and abs(z) >= ENTRY_Z:
                    notional = equity * NOTIONAL_PER_NAME
                    if z >= ENTRY_Z:
                        # returns stretched UP → contrarian short
                        if not ALLOW_SHORTS:
                            log.info("SKIP %s SHORT signal (z=%+.2f) — shorts disabled", sym, z)
                            continue
                        log.info(">>> SHORT %s notional=$%.2f z=%+.2f price=%.2f",
                                 sym, notional, z, p)
                        ax.submit_market_notional(sym, notional, "sell")
                        legs[sym] = Leg(sym, "short", notional / p, p)
                    else:
                        log.info(">>> LONG %s notional=$%.2f z=%+.2f price=%.2f",
                                 sym, notional, z, p)
                        ax.submit_market_notional(sym, notional, "buy")
                        legs[sym] = Leg(sym, "long", notional / p, p)

            log.info("OPEN LEGS (%d): %s", len(legs),
                     ", ".join(f"{l.symbol}({l.side})" for l in legs.values()) or "[none]")

        except Exception as e:
            log.exception("loop error: %s", e)

        time.sleep(max(1.0, POLL_INTERVAL - (time.time() - t0)))


if __name__ == "__main__":
    main()
