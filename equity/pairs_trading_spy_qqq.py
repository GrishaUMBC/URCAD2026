#!/usr/bin/env python3
"""
SPY/QQQ Pairs Trading — Alpaca PAPER trading
=============================================

PAPER TRADING ONLY. NOT FINANCIAL ADVICE. SEE DISCLAIMER.md.

Strategy
--------
SPY (S&P 500) and QQQ (Nasdaq 100) share enormous overlap in mega-cap
holdings (AAPL, MSFT, NVDA, etc.) so their *spread* tends to be much more
mean-reverting than either individual price.

Every POLL_INTERVAL seconds:
  1. Fetch latest trade for SPY and QQQ.
  2. Compute hedge ratio β via OLS over a rolling window of recent prices.
  3. Compute residual:    spread_t = QQQ_t − β · SPY_t
  4. Compute z-score of spread vs its trailing window.
  5. If z > +ENTRY_Z   → spread is rich   → SHORT QQQ + LONG SPY  (mean-revert)
     If z < −ENTRY_Z   → spread is cheap  → LONG  QQQ + SHORT SPY
     |z| < EXIT_Z      → unwind

NOTE: shorting either leg requires margin/short approval on the paper acct.
Set ALLOW_SHORTS = False to run only the long-only directional version
(enters whichever leg is "cheap" relative to the other and waits for revert).
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

log = configure("pairs_trading_spy_qqq")

# ─────────────────────── parameters ────────────────────────
SYM_A             = "QQQ"
SYM_B             = "SPY"
POLL_INTERVAL     = 5
HEDGE_WINDOW      = 60
ZSCORE_WINDOW     = 60
ENTRY_Z           = 2.0
EXIT_Z            = 0.4
NOTIONAL_PER_LEG  = 0.10           # 10% of equity per leg
ALLOW_SHORTS      = False
MAX_DAILY_LOSS_PCT = 0.02

MARKET_OPEN_HM    = (9, 35)
MARKET_CLOSE_HM   = (15, 45)


def hedge_ratio(a: np.ndarray, b: np.ndarray) -> float:
    """OLS slope: a = β·b + ε."""
    if len(a) < 5 or len(b) < 5:
        return 1.0
    cov = np.cov(a, b, ddof=1)
    return float(cov[0, 1] / cov[1, 1]) if cov[1, 1] != 0 else 1.0


def main():
    log.info("=" * 70)
    log.info("Pairs Trading  |  %s − β·%s  |  paper", SYM_A, SYM_B)
    log.info("entry_z=±%.2f  exit_z=±%.2f  shorts=%s",
             ENTRY_Z, EXIT_Z, ALLOW_SHORTS)

    start_equity = float(ax.get_account()["equity"])

    a_buf: deque[float] = deque(maxlen=HEDGE_WINDOW + ZSCORE_WINDOW)
    b_buf: deque[float] = deque(maxlen=HEDGE_WINDOW + ZSCORE_WINDOW)
    spread_buf: deque[float] = deque(maxlen=ZSCORE_WINDOW)

    # state: -1 = short A / long B, 0 = flat, +1 = long A / short B
    state = 0

    def flatten():
        ax.close_position(SYM_A)
        ax.close_position(SYM_B)

    def shutdown(*_):
        log.info("Shutdown — flattening pair")
        flatten()
        sys.exit(0)

    sigmod.signal(sigmod.SIGINT,  shutdown)
    sigmod.signal(sigmod.SIGTERM, shutdown)

    while True:
        t0 = time.time()
        try:
            if not ax.in_market_window(*MARKET_OPEN_HM, *MARKET_CLOSE_HM):
                log.info("Outside window — flattening and exiting")
                flatten(); shutdown()

            equity = float(ax.get_account()["equity"])
            if (start_equity - equity) / start_equity > MAX_DAILY_LOSS_PCT:
                log.warning("DAILY LOSS LIMIT — halting"); flatten(); shutdown()

            pa = ax.get_stock_latest_trade(SYM_A)
            pb = ax.get_stock_latest_trade(SYM_B)
            a_buf.append(pa); b_buf.append(pb)

            if len(a_buf) < HEDGE_WINDOW:
                log.info("WARMUP %d/%d  %s=%.2f %s=%.2f",
                         len(a_buf), HEDGE_WINDOW, SYM_A, pa, SYM_B, pb)
                _sleep(t0); continue

            a_arr = np.array(a_buf); b_arr = np.array(b_buf)
            beta  = hedge_ratio(a_arr[-HEDGE_WINDOW:], b_arr[-HEDGE_WINDOW:])
            spread = pa - beta * pb
            spread_buf.append(spread)

            if len(spread_buf) < ZSCORE_WINDOW:
                log.info("Spread warmup %d/%d  spread=%.4f β=%.3f",
                         len(spread_buf), ZSCORE_WINDOW, spread, beta)
                _sleep(t0); continue

            z = zscore(np.array(spread_buf), ZSCORE_WINDOW)
            log.info("STATE=%+d  %s=%.2f  %s=%.2f  β=%.3f  spread=%+.3f  z=%+.2f",
                     state, SYM_A, pa, SYM_B, pb, beta, spread, z)

            notional = equity * NOTIONAL_PER_LEG

            # exit logic
            if state != 0 and abs(z) <= EXIT_Z:
                log.info("EXIT pair (z=%.2f within ±%.2f)", z, EXIT_Z)
                flatten(); state = 0; _sleep(t0); continue

            # entry logic
            if state == 0:
                if z >= ENTRY_Z:
                    # spread rich: SHORT A, LONG B
                    if ALLOW_SHORTS:
                        log.info(">>> SHORT %s + LONG %s  notional=$%.2f/leg",
                                 SYM_A, SYM_B, notional)
                        ax.submit_market_notional(SYM_A, notional, "sell")
                        ax.submit_market_notional(SYM_B, notional, "buy")
                        state = -1
                    else:
                        log.info(">>> LONG %s only (shorts disabled)", SYM_B)
                        ax.submit_market_notional(SYM_B, notional, "buy")
                        state = -1
                elif z <= -ENTRY_Z:
                    # spread cheap: LONG A, SHORT B
                    if ALLOW_SHORTS:
                        log.info(">>> LONG %s + SHORT %s  notional=$%.2f/leg",
                                 SYM_A, SYM_B, notional)
                        ax.submit_market_notional(SYM_A, notional, "buy")
                        ax.submit_market_notional(SYM_B, notional, "sell")
                        state = +1
                    else:
                        log.info(">>> LONG %s only (shorts disabled)", SYM_A)
                        ax.submit_market_notional(SYM_A, notional, "buy")
                        state = +1

        except Exception as e:
            log.exception("loop error: %s", e)

        _sleep(t0)


def _sleep(t0: float):
    time.sleep(max(0.5, POLL_INTERVAL - (time.time() - t0)))


if __name__ == "__main__":
    main()
