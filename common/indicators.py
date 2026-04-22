"""
Numpy implementations of common technical / statistical indicators used across
the strategy scripts. Kept dependency-light (numpy only) and pure-functional.
"""

from __future__ import annotations

import numpy as np


def ema(series: np.ndarray, period: int) -> np.ndarray:
    """Exponential moving average. Returns array of same length."""
    if len(series) == 0:
        return series
    k = 2.0 / (period + 1)
    out = np.empty_like(series, dtype=float)
    out[0] = series[0]
    for i in range(1, len(series)):
        out[i] = series[i] * k + out[i - 1] * (1 - k)
    return out


def sma(series: np.ndarray, period: int) -> float:
    if len(series) < period:
        return float(np.mean(series)) if len(series) else 0.0
    return float(np.mean(series[-period:]))


def rsi(closes: np.ndarray, period: int = 14) -> float:
    if len(closes) < period + 1:
        return 50.0
    delta = np.diff(closes[-(period + 1):])
    gain  = np.where(delta > 0, delta, 0.0).mean()
    loss  = np.where(delta < 0, -delta, 0.0).mean()
    if loss == 0:
        return 100.0
    return 100 - 100 / (1 + gain / loss)


def macd(closes: np.ndarray,
         fast: int = 12, slow: int = 26, signal: int = 9) -> tuple[float, float, float]:
    """Return (macd_line, signal_line, histogram)."""
    if len(closes) < slow + signal:
        return 0.0, 0.0, 0.0
    fast_e = ema(closes, fast)
    slow_e = ema(closes, slow)
    macd_l = fast_e - slow_e
    sig_l  = ema(macd_l, signal)
    return float(macd_l[-1]), float(sig_l[-1]), float(macd_l[-1] - sig_l[-1])


def bollinger(closes: np.ndarray, period: int = 20, n_std: float = 2.0) -> tuple[float, float, float]:
    """Return (upper, mid, lower)."""
    if len(closes) < period:
        m = float(closes[-1]) if len(closes) else 0.0
        return m, m, m
    window = closes[-period:]
    mid = float(np.mean(window))
    std = float(np.std(window, ddof=1))
    return mid + n_std * std, mid, mid - n_std * std


def atr(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray,
        period: int = 14) -> float:
    if len(closes) < 2:
        return float(highs[-1] - lows[-1])
    tr = np.maximum(
        highs[1:] - lows[1:],
        np.maximum(np.abs(highs[1:] - closes[:-1]),
                   np.abs(lows[1:]  - closes[:-1])),
    )
    return float(np.mean(tr[-period:]))


def vwap(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray,
         volumes: np.ndarray) -> float:
    typical = (highs + lows + closes) / 3.0
    vol_sum = float(np.sum(volumes))
    return float(np.sum(typical * volumes) / vol_sum) if vol_sum > 0 else float(closes[-1])


def zscore(series: np.ndarray, lookback: int) -> float:
    """Z-score of the most recent value vs a trailing window."""
    if len(series) < lookback:
        return 0.0
    window = series[-lookback:]
    mu = float(np.mean(window))
    sd = float(np.std(window, ddof=1))
    if sd == 0:
        return 0.0
    return (float(series[-1]) - mu) / sd


def linreg_slope(series: np.ndarray, window: int) -> float:
    """OLS slope coefficient over the last `window` samples."""
    if len(series) < window:
        return 0.0
    seg = series[-window:].astype(float)
    x = np.arange(window, dtype=float)
    return float(np.polyfit(x, seg, 1)[0])


def realized_vol(returns: np.ndarray, lookback: int) -> float:
    """Standard deviation of recent log returns (annualization left to caller)."""
    if len(returns) < lookback:
        return float(np.std(returns, ddof=1)) if len(returns) > 1 else 0.0
    return float(np.std(returns[-lookback:], ddof=1))


def hurst_exponent(series: np.ndarray, max_lag: int = 20) -> float:
    """
    Cheap Hurst exponent estimate.  H < 0.5 → mean-reverting,
    H ≈ 0.5 → random walk, H > 0.5 → trending.
    """
    if len(series) < max_lag * 2:
        return 0.5
    lags = range(2, max_lag)
    tau = [np.std(np.subtract(series[lag:], series[:-lag])) for lag in lags]
    tau = np.array(tau)
    if np.any(tau <= 0):
        return 0.5
    poly = np.polyfit(np.log(list(lags)), np.log(tau), 1)
    return float(poly[0] * 2.0)


def logistic(x: float) -> float:
    """Stable logistic sigmoid."""
    if x >= 0:
        z = np.exp(-x)
        return float(1.0 / (1.0 + z))
    z = np.exp(x)
    return float(z / (1.0 + z))
