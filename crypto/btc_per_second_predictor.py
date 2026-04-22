#!/usr/bin/env python3
"""
Per-Second BTC/USD Statistical Direction Predictor — Alpaca PAPER trading
==========================================================================

PAPER TRADING ONLY. NOT FINANCIAL ADVICE. SEE DISCLAIMER.md.

The crypto twin of `equity/spy_per_second_predictor.py`. Same statistical
approach: rolling buffer of last-trade prices, five micro-features, fixed
logistic, threshold-based entry.

Differences from the equity version:
  - Crypto markets trade 24/7 — no market_open / market_close windows.
  - Uses Alpaca's crypto market-data endpoints (v1beta3) and crypto
    symbol notation ("BTC/USD" not "BTC").
  - Larger PROFIT_TARGET_PCT and STOP_LOSS_PCT to fit BTC's higher
    per-second variance.
  - No short selling — Alpaca paper crypto is long-only.

A 24/7 strategy left unattended will keep trading through nights, weekends,
and any failure mode you have not anticipated. Set MAX_RUN_HOURS so the
script self-terminates after a bounded period.
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
from common.indicators import logistic, zscore, realized_vol, ema
from common.logging_setup import configure

log = configure("btc_per_second_predictor")

# ─────────────────────── parameters ────────────────────────
SYMBOL              = "BTC/USD"

POLL_INTERVAL       = 1.0
WARMUP_TICKS        = 60
BUFFER_LEN          = 240        # 4 minutes of history

EWMA_FAST           = 5
EWMA_SLOW           = 30
ZSCORE_WINDOW       = 60
UPTICK_WINDOW       = 30
VOL_WINDOW          = 60

# weights — see equity twin for explanation
W_SLOPE_FAST        = 30.0       # BTC slope is ~$1/s scale, so smaller multiplier
W_SLOPE_SLOW        = 15.0
W_ZSCORE            = 0.55
W_UPTICK            = 3.5
W_VOL               = 100.0

LONG_THRESHOLD      = 0.58       # higher than equity (BTC noisier)
SHORT_THRESHOLD     = 0.42

BASE_NOTIONAL_PCT   = 0.04       # 4% of equity at full conviction
MAX_HOLD_SECONDS    = 60
PROFIT_TARGET_PCT   = 0.10       # 0.10% — BTC swings more
STOP_LOSS_PCT       = 0.08
COOLDOWN_SECONDS    = 3

MAX_DAILY_LOSS_PCT  = 0.025
MAX_RUN_HOURS       = 4          # auto-stop after this many hours


def compute_features(buf: np.ndarray) -> dict[str, float]:
    fast = ema(buf[-EWMA_FAST * 3:], EWMA_FAST)
    slow = ema(buf[-EWMA_SLOW * 2:], EWMA_SLOW)
    fs = float(fast[-1] - fast[-EWMA_FAST]) / EWMA_FAST if len(fast) >= EWMA_FAST else 0.0
    ss = float(slow[-1] - slow[-EWMA_SLOW]) / EWMA_SLOW if len(slow) >= EWMA_SLOW else 0.0
    z  = zscore(buf, ZSCORE_WINDOW)
    if len(buf) > UPTICK_WINDOW:
        diffs = np.diff(buf[-(UPTICK_WINDOW + 1):])
        uf = float(np.mean(diffs > 0))
    else:
        uf = 0.5
    if len(buf) > VOL_WINDOW:
        rets = np.diff(np.log(buf[-(VOL_WINDOW + 1):]))
        rv = realized_vol(rets, VOL_WINDOW)
    else:
        rv = 0.0
    return {"slope_fast": fs, "slope_slow": ss, "zscore_60s": z,
            "uptick_30s": uf, "rvol_60s": rv}


def predict_p_up(f: dict[str, float]) -> float:
    logit = (
        W_SLOPE_FAST * f["slope_fast"]
      + W_SLOPE_SLOW * f["slope_slow"]
      - W_ZSCORE     * f["zscore_60s"]
      + W_UPTICK     * (f["uptick_30s"] - 0.5)
      - W_VOL        * f["rvol_60s"]
    )
    return logistic(logit)


class OpenTrade:
    def __init__(self, qty, entry, opened_at):
        self.qty = qty
        self.entry = entry
        self.opened_at = opened_at
        self.target = entry * (1 + PROFIT_TARGET_PCT / 100)
        self.stop   = entry * (1 - STOP_LOSS_PCT     / 100)

    def pnl(self, p): return (p - self.entry) * self.qty

    def exit_reason(self, price, p_up):
        held = time.time() - self.opened_at
        if held >= MAX_HOLD_SECONDS:           return f"TIME_STOP({held:.0f}s)"
        if price >= self.target:                return f"PROFIT_TARGET({price:.2f}>={self.target:.2f})"
        if price <= self.stop:                  return f"STOP_LOSS({price:.2f}<={self.stop:.2f})"
        if p_up <= SHORT_THRESHOLD:             return f"SIGNAL_FLIP(p={p_up:.2f})"
        return None


def main():
    log.info("=" * 70)
    log.info("Per-Second %s Predictor  |  paper  |  poll=%.1fs  max_run=%dh",
             SYMBOL, POLL_INTERVAL, MAX_RUN_HOURS)
    log.info("Crypto markets are 24/7 — no market-window guard. AUTO-STOPS in %dh.",
             MAX_RUN_HOURS)

    start_equity = float(ax.get_account()["equity"])
    log.info("Equity $%.2f", start_equity)

    buf: deque[float] = deque(maxlen=BUFFER_LEN)
    trade: OpenTrade | None = None
    last_close_at = 0.0
    started_at = time.time()
    tick = 0
    n_trades = n_wins = 0
    session_pnl = 0.0

    def shutdown(*_):
        log.info("Shutdown — flattening")
        ax.cancel_all_orders()
        ax.close_position(SYMBOL)
        log.info("Session: trades=%d wins=%d pnl=$%+.2f",
                 n_trades, n_wins, session_pnl)
        sys.exit(0)

    sigmod.signal(sigmod.SIGINT,  shutdown)
    sigmod.signal(sigmod.SIGTERM, shutdown)

    while True:
        cycle_start = time.time()
        try:
            if (time.time() - started_at) / 3600 >= MAX_RUN_HOURS:
                log.info("MAX_RUN_HOURS reached — shutting down"); shutdown()

            equity = float(ax.get_account()["equity"])
            if (start_equity - equity) / start_equity > MAX_DAILY_LOSS_PCT:
                log.warning("DAILY LOSS LIMIT — halting"); shutdown()

            try:
                price = ax.get_crypto_latest_trade(SYMBOL)
            except Exception as e:
                log.warning("price fetch failed: %s", e)
                _sleep(cycle_start); continue

            buf.append(price); tick += 1
            arr = np.array(buf, dtype=float)

            if tick < WARMUP_TICKS:
                if tick % 10 == 0:
                    log.info("WARMUP %d/%d  price=%.2f", tick, WARMUP_TICKS, price)
                _sleep(cycle_start); continue

            feats = compute_features(arr)
            p_up = predict_p_up(feats)

            if trade is not None:
                pnl = trade.pnl(price)
                reason = trade.exit_reason(price, p_up)
                log.info("HOLD qty=%.6f entry=%.2f price=%.2f pnl=$%+.2f p_up=%.3f",
                         trade.qty, trade.entry, price, pnl, p_up)
                if reason:
                    log.info("EXIT — %s  pnl=$%+.2f", reason, pnl)
                    ax.submit_market_qty(SYMBOL, round(trade.qty, 6), "sell")
                    session_pnl += pnl; n_trades += 1
                    if pnl >= 0: n_wins += 1
                    trade = None
                    last_close_at = time.time()

            elif time.time() - last_close_at >= COOLDOWN_SECONDS:
                conviction = abs(p_up - 0.5) * 2
                notional = equity * BASE_NOTIONAL_PCT * conviction
                log.info("FLAT  price=%.2f p_up=%.3f  z=%+.2f rvol=%.5f  notional=$%.0f",
                         price, p_up, feats["zscore_60s"], feats["rvol_60s"], notional)
                if p_up >= LONG_THRESHOLD and notional > 5:
                    qty = notional / price
                    log.info(">>> LONG  qty=%.6f notional=$%.2f price=%.2f",
                             qty, notional, price)
                    ax.submit_market_notional(SYMBOL, notional, "buy")
                    trade = OpenTrade(qty, price, time.time())

        except Exception as e:
            log.exception("loop error: %s", e)

        _sleep(cycle_start)


def _sleep(t0):
    time.sleep(max(0.05, POLL_INTERVAL - (time.time() - t0)))


if __name__ == "__main__":
    main()
