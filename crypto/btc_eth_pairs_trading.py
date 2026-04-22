#!/usr/bin/env python3
"""
BTC/ETH Pairs Trading — Alpaca PAPER trading
=============================================

PAPER TRADING ONLY. NOT FINANCIAL ADVICE. SEE DISCLAIMER.md.

Strategy
--------
BTC and ETH are the two largest crypto assets and historically exhibit
strong long-run correlation. Their *spread* is more mean-reverting than
either price alone, making them a natural pairs-trading candidate.

Every POLL_INTERVAL seconds:
  1. Fetch latest prices for BTC/USD and ETH/USD
  2. Compute log-price spread:  s_t = ln(ETH_t) − β · ln(BTC_t)
     β is recomputed via OLS over a rolling HEDGE_WINDOW
  3. Compute z-score of spread vs trailing window
  4. z ≥ +ENTRY_Z → spread rich  → spread should fall
                                  → since shorts are not allowed in paper
                                    crypto, simply skip rich entries
     z ≤ -ENTRY_Z → spread cheap → spread should rise
                                  → LONG ETH (long-only paper crypto)
  5. Exit when |z| ≤ EXIT_Z

Long-only adaptation makes this strictly a "buy ETH when it looks cheap
relative to BTC" strategy.
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

log = configure("btc_eth_pairs_trading")

# ────────────────────── parameters ────────────────────────
SYM_RICH         = "ETH/USD"     # "A" leg in the residual
SYM_BASE         = "BTC/USD"     # "B" leg / hedge
POLL_INTERVAL    = 10
HEDGE_WINDOW     = 60
ZSCORE_WINDOW    = 60
ENTRY_Z          = 2.0
EXIT_Z           = 0.4
NOTIONAL_PCT     = 0.10
MAX_DAILY_LOSS_PCT = 0.025
MAX_RUN_HOURS    = 6


def hedge_ratio(a: np.ndarray, b: np.ndarray) -> float:
    if len(a) < 5 or len(b) < 5: return 1.0
    cov = np.cov(a, b, ddof=1)
    return float(cov[0, 1] / cov[1, 1]) if cov[1, 1] != 0 else 1.0


def main():
    log.info("=" * 70)
    log.info("Crypto Pairs Trading  |  ln(%s) − β·ln(%s)  |  paper",
             SYM_RICH, SYM_BASE)
    log.info("entry_z=±%.2f exit_z=±%.2f long-only-on-cheap-spread",
             ENTRY_Z, EXIT_Z)

    start_equity = float(ax.get_account()["equity"])
    started_at = time.time()

    a_buf: deque[float] = deque(maxlen=HEDGE_WINDOW + ZSCORE_WINDOW)
    b_buf: deque[float] = deque(maxlen=HEDGE_WINDOW + ZSCORE_WINDOW)
    spread_buf: deque[float] = deque(maxlen=ZSCORE_WINDOW)
    in_position = False

    def flatten():
        ax.close_position(SYM_RICH)

    def shutdown(*_):
        log.info("Shutdown — flattening"); flatten(); sys.exit(0)

    sigmod.signal(sigmod.SIGINT,  shutdown)
    sigmod.signal(sigmod.SIGTERM, shutdown)

    while True:
        t0 = time.time()
        try:
            if (time.time() - started_at) / 3600 >= MAX_RUN_HOURS:
                log.info("MAX_RUN_HOURS reached"); flatten(); shutdown()

            equity = float(ax.get_account()["equity"])
            if (start_equity - equity) / start_equity > MAX_DAILY_LOSS_PCT:
                log.warning("DAILY LOSS LIMIT — halting"); flatten(); shutdown()

            try:
                pa = ax.get_crypto_latest_trade(SYM_RICH)
                pb = ax.get_crypto_latest_trade(SYM_BASE)
            except Exception as e:
                log.warning("price fetch: %s", e); _sleep(t0); continue

            a_buf.append(np.log(pa)); b_buf.append(np.log(pb))

            if len(a_buf) < HEDGE_WINDOW:
                log.info("WARMUP %d/%d", len(a_buf), HEDGE_WINDOW)
                _sleep(t0); continue

            beta = hedge_ratio(np.array(a_buf)[-HEDGE_WINDOW:],
                               np.array(b_buf)[-HEDGE_WINDOW:])
            spread = np.log(pa) - beta * np.log(pb)
            spread_buf.append(spread)

            if len(spread_buf) < ZSCORE_WINDOW:
                log.info("Spread warmup %d/%d", len(spread_buf), ZSCORE_WINDOW)
                _sleep(t0); continue

            z = zscore(np.array(spread_buf), ZSCORE_WINDOW)
            log.info("%s=%.2f %s=%.2f β=%.3f spread=%+.4f z=%+.2f in_pos=%s",
                     SYM_RICH, pa, SYM_BASE, pb, beta, spread, z, in_position)

            if in_position and abs(z) <= EXIT_Z:
                log.info("EXIT — z within ±%.2f", EXIT_Z)
                flatten(); in_position = False; _sleep(t0); continue

            if not in_position and z <= -ENTRY_Z:
                notional = equity * NOTIONAL_PCT
                log.info(">>> LONG %s (cheap leg) notional=$%.2f z=%+.2f",
                         SYM_RICH, notional, z)
                ax.submit_market_notional(SYM_RICH, notional, "buy")
                in_position = True
            elif not in_position and z >= ENTRY_Z:
                log.info("SKIP RICH-SPREAD signal (z=%+.2f) — no shorts in paper crypto", z)

        except Exception as e:
            log.exception("loop error: %s", e)

        _sleep(t0)


def _sleep(t0):
    time.sleep(max(1.0, POLL_INTERVAL - (time.time() - t0)))


if __name__ == "__main__":
    main()
