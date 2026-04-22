#!/usr/bin/env python3
"""
Per-Second SPY Statistical Direction Predictor — Alpaca PAPER trading
=====================================================================

THIS IS RESEARCH CODE FOR A PAPER-TRADING ACCOUNT. DO NOT RUN AGAINST
A LIVE BROKERAGE ACCOUNT. NOT FINANCIAL ADVICE. SEE DISCLAIMER.md.

Strategy
--------
Polls SPY's last-trade price once per second.  Maintains a rolling buffer of
the most recent N=180 ticks (≈3 minutes).  Each second, recomputes a
hand-tuned logistic that estimates P(next-second price move is upward) from
five micro-features:

  f1  ewma_slope_5s    — slope of EWMA(α=0.4) over last 5 ticks  (momentum)
  f2  ewma_slope_30s   — slope of EWMA(α=0.1) over last 30 ticks (trend)
  f3  zscore_60s       — (price − μ_60s) / σ_60s                 (mean-reversion)
  f4  uptick_freq_30s  — empirical P(up tick) over last 30 ticks (drift)
  f5  realized_vol_60s — std of last 60 log returns              (regime)

The five features are combined with FIXED weights into a logit:

    logit  =  w1·f1  +  w2·f2  −  w3·f3  +  w4·(f4 − 0.5)  −  w5·f5
    p_up   =  σ(logit)

The mean-reversion term f3 enters with a negative coefficient (extended
deviations are expected to revert). The volatility term f5 enters negatively
to shrink confidence in chaotic regimes.

Entry / exit
------------
  p_up >= LONG_THRESHOLD       → enter long  (or maintain)
  p_up <= SHORT_THRESHOLD      → flatten     (and short, if ALLOW_SHORTS)
  otherwise                    → no action

Position sizing scales with conviction:
    notional = BASE_NOTIONAL_PCT · equity · (|p_up − 0.5| · 2)

Risk controls:
  - MAX_HOLD_SECONDS hard time-stop on every trade
  - STOP_LOSS_PCT and PROFIT_TARGET_PCT bracket
  - 2-second cool-down between flatten and re-entry
  - Daily MAX_DAILY_LOSS_PCT halts the bot
  - Trades only inside the 9:35–15:45 ET core window

NOTE
----
The fixed weights below were chosen by inspection to be reasonable, NOT
fitted on out-of-sample data. Treat them as illustrative. Real production
use would require historical calibration, walk-forward validation, slippage
modelling, and many more controls than are present here. See DISCLAIMER.md.
"""

from __future__ import annotations

import math
import signal as sigmod
import sys
import time
from collections import deque
from pathlib import Path

import numpy as np

# allow `python equity/spy_per_second_predictor.py` from repo root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common import alpaca_rest as ax
from common.indicators import logistic, zscore, realized_vol, ema
from common.logging_setup import configure

log = configure("spy_per_second_predictor")

# ──────────────────────── strategy parameters ──────────────────────────
SYMBOL                 = "SPY"

POLL_INTERVAL          = 1.0      # seconds between polls (per-second)
WARMUP_TICKS           = 60       # required ticks before trading
BUFFER_LEN             = 180      # rolling tick history (≈3 min)

EWMA_FAST_PERIOD       = 5
EWMA_SLOW_PERIOD       = 30
ZSCORE_WINDOW          = 60
UPTICK_WINDOW          = 30
VOL_WINDOW             = 60

# logistic weights (hand-set; SEE DISCLAIMER)
W_SLOPE_FAST           = 1200.0   # raw slope is ≈$0.0001/s scale → big multiplier
W_SLOPE_SLOW           =  600.0
W_ZSCORE               =    0.55  # negative sign applied below (mean-revert)
W_UPTICK               =    3.5
W_VOL                  =  150.0   # negative sign applied below (penalty)

LONG_THRESHOLD         = 0.56
SHORT_THRESHOLD        = 0.44
ALLOW_SHORTS           = False    # turn on only if your paper acct supports it

BASE_NOTIONAL_PCT      = 0.05     # 5 % of equity at full conviction
MAX_HOLD_SECONDS       = 30
PROFIT_TARGET_PCT      = 0.05     # exit at +0.05 %
STOP_LOSS_PCT          = 0.04     # exit at −0.04 %
COOLDOWN_SECONDS       = 2

MAX_DAILY_LOSS_PCT     = 0.02     # halt if equity drops 2 %

MARKET_OPEN_HM         = (9, 35)
MARKET_CLOSE_HM        = (15, 45)


# ─────────────────────────── feature engine ────────────────────────────
def compute_features(buf: np.ndarray) -> dict[str, float]:
    """Compute the five micro-features used by the logit."""
    fast = ema(buf[-EWMA_FAST_PERIOD * 3:], EWMA_FAST_PERIOD)
    slow = ema(buf[-EWMA_SLOW_PERIOD * 2:], EWMA_SLOW_PERIOD)

    fast_slope = float(fast[-1] - fast[-EWMA_FAST_PERIOD]) / EWMA_FAST_PERIOD \
        if len(fast) >= EWMA_FAST_PERIOD else 0.0
    slow_slope = float(slow[-1] - slow[-EWMA_SLOW_PERIOD]) / EWMA_SLOW_PERIOD \
        if len(slow) >= EWMA_SLOW_PERIOD else 0.0

    z = zscore(buf, ZSCORE_WINDOW)

    if len(buf) > UPTICK_WINDOW:
        diffs = np.diff(buf[-(UPTICK_WINDOW + 1):])
        uptick_freq = float(np.mean(diffs > 0))
    else:
        uptick_freq = 0.5

    if len(buf) > VOL_WINDOW:
        rets = np.diff(np.log(buf[-(VOL_WINDOW + 1):]))
        rv = realized_vol(rets, VOL_WINDOW)
    else:
        rv = 0.0

    return {
        "slope_fast": fast_slope,
        "slope_slow": slow_slope,
        "zscore_60s": z,
        "uptick_30s": uptick_freq,
        "rvol_60s":   rv,
    }


def predict_p_up(feats: dict[str, float]) -> float:
    """Combine features into a P(up next second) estimate."""
    logit = (
        W_SLOPE_FAST * feats["slope_fast"]
      + W_SLOPE_SLOW * feats["slope_slow"]
      - W_ZSCORE     * feats["zscore_60s"]
      + W_UPTICK     * (feats["uptick_30s"] - 0.5)
      - W_VOL        * feats["rvol_60s"]
    )
    return logistic(logit)


# ─────────────────────────── trade state ───────────────────────────────
class OpenTrade:
    def __init__(self, side: str, qty: float, entry: float, opened_at: float):
        self.side      = side
        self.qty       = qty
        self.entry     = entry
        self.opened_at = opened_at
        self.target    = entry * (1 + PROFIT_TARGET_PCT / 100) if side == "long" \
                    else entry * (1 - PROFIT_TARGET_PCT / 100)
        self.stop      = entry * (1 - STOP_LOSS_PCT     / 100) if side == "long" \
                    else entry * (1 + STOP_LOSS_PCT     / 100)

    def pnl(self, price: float) -> float:
        mult = 1 if self.side == "long" else -1
        return mult * (price - self.entry) * self.qty

    def exit_reason(self, price: float, p_up: float) -> str | None:
        held = time.time() - self.opened_at
        if held >= MAX_HOLD_SECONDS:
            return f"TIME_STOP({held:.0f}s)"
        if self.side == "long":
            if price >= self.target: return f"PROFIT_TARGET({price:.2f}>={self.target:.2f})"
            if price <= self.stop:   return f"STOP_LOSS({price:.2f}<={self.stop:.2f})"
            if p_up <= SHORT_THRESHOLD: return f"SIGNAL_FLIP(p={p_up:.2f})"
        else:
            if price <= self.target: return f"PROFIT_TARGET({price:.2f}<={self.target:.2f})"
            if price >= self.stop:   return f"STOP_LOSS({price:.2f}>={self.stop:.2f})"
            if p_up >= LONG_THRESHOLD: return f"SIGNAL_FLIP(p={p_up:.2f})"
        return None


# ─────────────────────────── main loop ─────────────────────────────────
def main():
    log.info("=" * 70)
    log.info("Per-Second SPY Predictor  |  paper trading  |  poll=%.1fs",
             POLL_INTERVAL)
    log.info("Thresholds: long>=%.2f  short<=%.2f  shorts_allowed=%s",
             LONG_THRESHOLD, SHORT_THRESHOLD, ALLOW_SHORTS)
    log.info("Risk: hold<=%ds  tgt=%.3f%%  stop=%.3f%%  daily_kill=%.2f%%",
             MAX_HOLD_SECONDS, PROFIT_TARGET_PCT, STOP_LOSS_PCT,
             MAX_DAILY_LOSS_PCT * 100)

    acct = ax.get_account()
    start_equity = float(acct["equity"])
    log.info("Equity: $%.2f  buying_power: $%s", start_equity, acct["buying_power"])

    buf: deque[float] = deque(maxlen=BUFFER_LEN)
    trade: OpenTrade | None = None
    last_close_at = 0.0
    tick = 0
    session_pnl = 0.0
    n_trades = n_wins = 0

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
            # ── window check ──────────────────────────────
            if not ax.in_market_window(*MARKET_OPEN_HM, *MARKET_CLOSE_HM):
                if trade is not None:
                    log.info("Outside trading window — flattening")
                    ax.cancel_all_orders()
                    ax.close_position(SYMBOL)
                    trade = None
                log.info("Market closed — exiting.")
                shutdown()

            # ── daily kill-switch ─────────────────────────
            equity = float(ax.get_account()["equity"])
            if (start_equity - equity) / start_equity > MAX_DAILY_LOSS_PCT:
                log.warning("DAILY LOSS LIMIT HIT — halting (equity=$%.2f)", equity)
                ax.cancel_all_orders(); ax.close_position(SYMBOL)
                shutdown()

            # ── poll price + update buffer ────────────────
            price = ax.get_stock_latest_trade(SYMBOL)
            buf.append(price)
            tick += 1
            arr = np.array(buf, dtype=float)

            if tick < WARMUP_TICKS:
                if tick % 10 == 0:
                    log.info("WARMUP %d/%d  price=%.2f", tick, WARMUP_TICKS, price)
                _sleep_to_next(cycle_start)
                continue

            # ── compute prediction ────────────────────────
            feats = compute_features(arr)
            p_up = predict_p_up(feats)

            # ── manage open trade ─────────────────────────
            if trade is not None:
                pnl = trade.pnl(price)
                reason = trade.exit_reason(price, p_up)
                log.info("HOLD %-5s qty=%.4f entry=%.2f price=%.2f pnl=$%+.2f p_up=%.3f",
                         trade.side.upper(), trade.qty, trade.entry, price, pnl, p_up)
                if reason:
                    side_close = "sell" if trade.side == "long" else "buy"
                    log.info("EXIT %s — %s  pnl=$%+.2f",
                             trade.side.upper(), reason, pnl)
                    ax.submit_market_qty(SYMBOL, round(trade.qty, 4), side_close)
                    session_pnl += pnl
                    n_trades += 1
                    if pnl >= 0: n_wins += 1
                    trade = None
                    last_close_at = time.time()

            # ── entry logic ───────────────────────────────
            elif time.time() - last_close_at >= COOLDOWN_SECONDS:
                conviction = abs(p_up - 0.5) * 2
                notional = equity * BASE_NOTIONAL_PCT * conviction

                log.info("FLAT  price=%.2f p_up=%.3f  slope_f=%+.5f slope_s=%+.5f "
                         "z=%+.2f uptick=%.2f rvol=%.5f  notional=$%.0f",
                         price, p_up, feats["slope_fast"], feats["slope_slow"],
                         feats["zscore_60s"], feats["uptick_30s"], feats["rvol_60s"],
                         notional)

                if p_up >= LONG_THRESHOLD and notional > 1:
                    qty = notional / price
                    log.info(">>> LONG  qty=%.4f  notional=$%.2f  price=%.2f",
                             qty, notional, price)
                    ax.submit_market_notional(SYMBOL, notional, "buy")
                    trade = OpenTrade("long", qty, price, time.time())

                elif p_up <= SHORT_THRESHOLD and ALLOW_SHORTS and notional > 1:
                    qty = notional / price
                    log.info(">>> SHORT  qty=%.4f  notional=$%.2f  price=%.2f",
                             qty, notional, price)
                    ax.submit_market_notional(SYMBOL, notional, "sell")
                    trade = OpenTrade("short", qty, price, time.time())

        except Exception as e:
            log.exception("loop error: %s", e)

        _sleep_to_next(cycle_start)


def _sleep_to_next(cycle_start: float):
    elapsed = time.time() - cycle_start
    time.sleep(max(0.05, POLL_INTERVAL - elapsed))


if __name__ == "__main__":
    main()
