#!/usr/bin/env python3
"""
Crypto Volatility Breakout — Alpaca PAPER trading
==================================================

PAPER TRADING ONLY. NOT FINANCIAL ADVICE. SEE DISCLAIMER.md.

Strategy
--------
Donchian-style breakout adapted for 24/7 crypto:

  1. Maintain a rolling N-tick price buffer (default N = 60 minutes of
     1-minute bars).
  2. Compute upper = max(high) and lower = min(low) over the buffer.
  3. If latest price > upper × (1 + BREAKOUT_BUFFER_PCT/100) → enter LONG.
  4. Trail stop = ATR-based, widened with current realized volatility so
     the stop survives normal noise but cuts on real reversals.
  5. Exit on trail stop, profit target, or MAX_HOLD_MINUTES.

Long-only (no paper-crypto shorts).
"""

from __future__ import annotations

import signal as sigmod
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common import alpaca_rest as ax
from common.indicators import atr
from common.logging_setup import configure

log = configure("crypto_volatility_breakout")

# ────────────────────── parameters ────────────────────────
SYMBOL                 = "BTC/USD"
LOOKBACK_BARS          = 60         # one-minute bars of history
BREAKOUT_BUFFER_PCT    = 0.05       # require 0.05% above prior high
ATR_MULT               = 2.5
PROFIT_TARGET_R        = 2.0        # profit = R × ATR
MAX_HOLD_MINUTES       = 90
NOTIONAL_PCT           = 0.15
POLL_INTERVAL          = 30
MAX_DAILY_LOSS_PCT     = 0.03
MAX_RUN_HOURS          = 8


def main():
    log.info("=" * 70)
    log.info("Crypto Volatility Breakout  |  %s  |  paper", SYMBOL)
    log.info("lookback=%d bars  buffer=%.2f%%  atr_mult=%.2f  tgt=%.2fR",
             LOOKBACK_BARS, BREAKOUT_BUFFER_PCT, ATR_MULT, PROFIT_TARGET_R)

    start_equity = float(ax.get_account()["equity"])
    started_at = time.time()

    in_position = False
    entry_price = 0.0
    qty = 0.0
    target = 0.0
    best_price = 0.0
    trail_dist = 0.0
    opened_at = 0.0

    def flatten():
        ax.cancel_all_orders(); ax.close_position(SYMBOL)

    def shutdown(*_):
        flatten(); sys.exit(0)

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

            bars = ax.get_crypto_bars(SYMBOL, "1Min", LOOKBACK_BARS)
            if len(bars) < 20:
                log.info("Insufficient bars (%d)", len(bars))
                time.sleep(POLL_INTERVAL); continue

            highs  = np.array([b["h"] for b in bars], dtype=float)
            lows   = np.array([b["l"] for b in bars], dtype=float)
            closes = np.array([b["c"] for b in bars], dtype=float)

            upper = float(np.max(highs[:-1]))      # exclude current bar
            lower = float(np.min(lows[:-1]))
            a     = atr(highs, lows, closes)
            try:
                price = ax.get_crypto_latest_trade(SYMBOL)
            except Exception as e:
                log.warning("price: %s", e); time.sleep(POLL_INTERVAL); continue

            log.info("price=%.2f upper=%.2f lower=%.2f atr=%.2f in_pos=%s",
                     price, upper, lower, a, in_position)

            # ── manage open position ─────────────
            if in_position:
                if price > best_price:
                    best_price = price
                stop = best_price - trail_dist
                held_min = (time.time() - opened_at) / 60
                pnl = (price - entry_price) * qty

                log.info("HOLD entry=%.2f best=%.2f stop=%.2f tgt=%.2f pnl=$%+.2f held=%.0fm",
                         entry_price, best_price, stop, target, pnl, held_min)

                exit_now = (
                    price <= stop
                    or price >= target
                    or held_min >= MAX_HOLD_MINUTES
                )
                if exit_now:
                    reason = "TRAIL_STOP" if price <= stop \
                        else "PROFIT_TARGET" if price >= target \
                        else "TIME_STOP"
                    log.info("EXIT — %s pnl=$%+.2f", reason, pnl)
                    flatten(); in_position = False
                time.sleep(POLL_INTERVAL); continue

            # ── look for breakout ────────────────
            threshold = upper * (1 + BREAKOUT_BUFFER_PCT / 100)
            if price >= threshold:
                trail_dist = ATR_MULT * a
                target_dist = PROFIT_TARGET_R * a
                notional = equity * NOTIONAL_PCT
                qty = notional / price
                entry_price = price
                best_price = price
                target = price + target_dist
                opened_at = time.time()
                log.info(">>> LONG BREAKOUT  price=%.2f  upper=%.2f  notional=$%.2f  trail=%.2f  tgt=%.2f",
                         price, upper, notional, trail_dist, target)
                ax.submit_market_notional(SYMBOL, notional, "buy")
                in_position = True
            else:
                log.info("WAITING — price below breakout threshold %.2f", threshold)

        except Exception as e:
            log.exception("loop error: %s", e)

        time.sleep(max(1.0, POLL_INTERVAL - (time.time() - t0)))


if __name__ == "__main__":
    main()
