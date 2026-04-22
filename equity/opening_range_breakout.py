#!/usr/bin/env python3
"""
Opening-Range Breakout (ORB) — Alpaca PAPER trading
====================================================

PAPER TRADING ONLY. NOT FINANCIAL ADVICE. SEE DISCLAIMER.md.

Strategy
--------
Classic ORB: define the "opening range" as the high and low of SPY's first
ORB_MINUTES of the trading session (default 15 minutes after the 9:30 ET
open). Then for the rest of the session:

  - If price breaks ABOVE the OR-high  → enter long
  - If price breaks BELOW the OR-low   → enter short (if shorts allowed)

Position is protected by:
  - Profit target  = OR-range × PROFIT_R   (1.5× the OR-range)
  - Hard stop loss = OR-range × STOP_R     (1.0× the OR-range)
  - Time-based flatten at MARKET_CLOSE_HM

Only ONE breakout is taken per day. After exit (target, stop, or close),
the bot stops looking for new entries until the next session.
"""

from __future__ import annotations

import signal as sigmod
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common import alpaca_rest as ax
from common.logging_setup import configure

log = configure("opening_range_breakout")

# ────────────────────── parameters ────────────────────────
SYMBOL              = "SPY"
ORB_MINUTES         = 15
PROFIT_R            = 1.5      # target = R × range
STOP_R              = 1.0      # stop   = R × range
NOTIONAL_PCT        = 0.20     # 20% of equity on the breakout
ALLOW_SHORTS        = False
POLL_INTERVAL       = 5

MARKET_OPEN_HM      = (9, 30)
MARKET_CLOSE_HM     = (15, 45)


def market_time() -> datetime:
    return datetime.fromisoformat(ax.get_clock()["timestamp"])


def is_in_orb_window(now: datetime) -> bool:
    open_h, open_m = MARKET_OPEN_HM
    minutes_since_open = (now.hour - open_h) * 60 + (now.minute - open_m)
    return 0 <= minutes_since_open < ORB_MINUTES


def is_after_orb(now: datetime) -> bool:
    open_h, open_m = MARKET_OPEN_HM
    minutes_since_open = (now.hour - open_h) * 60 + (now.minute - open_m)
    return minutes_since_open >= ORB_MINUTES


def main():
    log.info("=" * 70)
    log.info("Opening-Range Breakout  |  %s  |  paper", SYMBOL)
    log.info("OR=%dmin  profit_R=%.2f  stop_R=%.2f  notional=%.0f%%",
             ORB_MINUTES, PROFIT_R, STOP_R, NOTIONAL_PCT * 100)

    or_high: float | None = None
    or_low:  float | None = None
    or_range_prices: list[float] = []
    breakout_taken = False
    side: str | None = None
    qty: float = 0.0
    target: float = 0.0
    stop:   float = 0.0

    def flatten():
        ax.cancel_all_orders()
        ax.close_position(SYMBOL)

    def shutdown(*_):
        log.info("Shutdown — flattening")
        flatten()
        sys.exit(0)

    sigmod.signal(sigmod.SIGINT,  sigmod.SIG_DFL)
    sigmod.signal(sigmod.SIGINT,  shutdown)
    sigmod.signal(sigmod.SIGTERM, shutdown)

    while True:
        t0 = time.time()
        try:
            clock = ax.get_clock()
            if not clock.get("is_open", False):
                log.info("Market closed — exiting")
                flatten(); shutdown()

            now = market_time()
            price = ax.get_stock_latest_trade(SYMBOL)

            # ── phase 1: building the opening range ─────────
            if is_in_orb_window(now):
                or_range_prices.append(price)
                cur_h = max(or_range_prices)
                cur_l = min(or_range_prices)
                log.info("ORB-BUILDING  price=%.2f  range=[%.2f, %.2f] (%d samples)",
                         price, cur_l, cur_h, len(or_range_prices))
                _sleep(t0); continue

            # ── lock in OR boundaries the first time we exit the window ─
            if or_high is None and is_after_orb(now):
                if not or_range_prices:
                    log.warning("No ORB samples collected — using last price as range")
                    or_range_prices = [price]
                or_high = max(or_range_prices)
                or_low  = min(or_range_prices)
                log.info("ORB LOCKED  high=%.2f  low=%.2f  range=%.2f",
                         or_high, or_low, or_high - or_low)

            # ── phase 2: managing open position ────────────
            if breakout_taken and side is not None:
                hit_target = (price >= target) if side == "long" else (price <= target)
                hit_stop   = (price <= stop)   if side == "long" else (price >= stop)
                log.info("HOLD %s qty=%.4f price=%.2f tgt=%.2f stop=%.2f",
                         side, qty, price, target, stop)
                if hit_target or hit_stop:
                    reason = "PROFIT_TARGET" if hit_target else "STOP_LOSS"
                    log.info("EXIT %s — %s @ %.2f", side.upper(), reason, price)
                    flatten()
                    side = None
                    log.info("Done for the day — waiting for close")
                _sleep(t0); continue

            # ── EOD flatten ────────────────────────────────
            close_h, close_m = MARKET_CLOSE_HM
            if (now.hour, now.minute) >= (close_h, close_m):
                log.info("Market-close flatten")
                flatten(); shutdown()

            # ── phase 3: looking for breakout ──────────────
            if or_high is not None and not breakout_taken:
                rng = or_high - or_low
                equity = float(ax.get_account()["equity"])
                notional = equity * NOTIONAL_PCT

                if price > or_high:
                    side = "long"
                    target = price + PROFIT_R * rng
                    stop   = price - STOP_R   * rng
                    qty    = notional / price
                    log.info(">>> LONG BREAKOUT  price=%.2f or_high=%.2f tgt=%.2f stop=%.2f",
                             price, or_high, target, stop)
                    ax.submit_market_notional(SYMBOL, notional, "buy")
                    breakout_taken = True

                elif price < or_low and ALLOW_SHORTS:
                    side = "short"
                    target = price - PROFIT_R * rng
                    stop   = price + STOP_R   * rng
                    qty    = notional / price
                    log.info(">>> SHORT BREAKOUT  price=%.2f or_low=%.2f tgt=%.2f stop=%.2f",
                             price, or_low, target, stop)
                    ax.submit_market_notional(SYMBOL, notional, "sell")
                    breakout_taken = True

                else:
                    log.info("WAITING  price=%.2f  range=[%.2f, %.2f]",
                             price, or_low, or_high)

        except Exception as e:
            log.exception("loop error: %s", e)

        _sleep(t0)


def _sleep(t0: float):
    time.sleep(max(0.5, POLL_INTERVAL - (time.time() - t0)))


if __name__ == "__main__":
    main()
