#!/usr/bin/env python3
"""
VWAP Reversion Scalper — Alpaca PAPER trading
==============================================

PAPER TRADING ONLY. NOT FINANCIAL ADVICE. SEE DISCLAIMER.md.

Strategy
--------
Volume-weighted average price (VWAP) is a common intraday reference. Many
intraday liquidity providers anchor to it. Short-term deviations from VWAP
on liquid ETFs often revert.

Each cycle:
  1. Pull last N=120 one-minute bars and compute session VWAP.
  2. Compute deviation = (price − VWAP) / VWAP  (in %).
  3. If deviation > +ENTRY_PCT  → SHORT (revert down toward VWAP)
     If deviation < −ENTRY_PCT  → LONG  (revert up toward VWAP)
  4. Exit when price crosses back through VWAP, or hits stop / target.

Suitable symbols: any high-volume liquid ETF (default: SPY).
"""

from __future__ import annotations

import signal as sigmod
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common import alpaca_rest as ax
from common.indicators import vwap
from common.logging_setup import configure

log = configure("vwap_reversion")

# ────────────────────── parameters ────────────────────────
SYMBOL              = "SPY"
BARS_LOOKBACK       = 120
POLL_INTERVAL       = 15
ENTRY_PCT           = 0.15      # % deviation from VWAP to enter
PROFIT_PCT          = 0.10      # % to exit profitably
STOP_PCT            = 0.20      # hard stop %
NOTIONAL_PCT        = 0.10
ALLOW_SHORTS        = False
MAX_DAILY_LOSS_PCT  = 0.02

MARKET_OPEN_HM      = (9, 35)
MARKET_CLOSE_HM     = (15, 45)


def main():
    log.info("=" * 70)
    log.info("VWAP Reversion  |  %s  |  paper", SYMBOL)
    log.info("entry=±%.2f%%  tgt=%.2f%%  stop=%.2f%%  notional=%.0f%%",
             ENTRY_PCT, PROFIT_PCT, STOP_PCT, NOTIONAL_PCT * 100)

    start_equity = float(ax.get_account()["equity"])
    side: str | None = None
    qty: float = 0.0
    entry: float = 0.0

    def flatten():
        ax.cancel_all_orders(); ax.close_position(SYMBOL)

    def shutdown(*_):
        flatten(); sys.exit(0)

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

            bars = ax.get_stock_bars(SYMBOL, "1Min", BARS_LOOKBACK)
            if len(bars) < 20:
                log.info("Insufficient bars (%d)", len(bars)); _sleep(t0); continue

            highs   = np.array([b["h"] for b in bars], dtype=float)
            lows    = np.array([b["l"] for b in bars], dtype=float)
            closes  = np.array([b["c"] for b in bars], dtype=float)
            volumes = np.array([b["v"] for b in bars], dtype=float)
            v       = vwap(highs, lows, closes, volumes)

            price = ax.get_stock_latest_trade(SYMBOL)
            dev_pct = (price - v) / v * 100

            log.info("price=%.2f  vwap=%.2f  dev=%+.3f%%  side=%s",
                     price, v, dev_pct, side or "FLAT")

            # ── manage open position ──────────────
            if side is not None:
                if side == "long":
                    pnl_pct = (price - entry) / entry * 100
                    if dev_pct >= 0 or pnl_pct >= PROFIT_PCT or pnl_pct <= -STOP_PCT:
                        log.info("EXIT LONG @ %.2f pnl=%.3f%%", price, pnl_pct)
                        flatten(); side = None
                else:  # short
                    pnl_pct = (entry - price) / entry * 100
                    if dev_pct <= 0 or pnl_pct >= PROFIT_PCT or pnl_pct <= -STOP_PCT:
                        log.info("EXIT SHORT @ %.2f pnl=%.3f%%", price, pnl_pct)
                        flatten(); side = None
                _sleep(t0); continue

            # ── new entry ─────────────────────────
            notional = equity * NOTIONAL_PCT
            if dev_pct <= -ENTRY_PCT:
                log.info(">>> LONG (revert up) notional=$%.2f", notional)
                ax.submit_market_notional(SYMBOL, notional, "buy")
                side = "long";  qty = notional / price; entry = price
            elif dev_pct >= ENTRY_PCT and ALLOW_SHORTS:
                log.info(">>> SHORT (revert down) notional=$%.2f", notional)
                ax.submit_market_notional(SYMBOL, notional, "sell")
                side = "short"; qty = notional / price; entry = price

        except Exception as e:
            log.exception("loop error: %s", e)

        _sleep(t0)


def _sleep(t0: float):
    time.sleep(max(1.0, POLL_INTERVAL - (time.time() - t0)))


if __name__ == "__main__":
    main()
