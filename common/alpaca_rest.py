"""
Thin REST wrapper around the Alpaca paper-trading + market-data APIs.

Designed to be small and dependency-light (only `requests`). The `alpaca-py`
SDK is also a perfectly good option — we use plain REST in this repo so the
sample scripts are easy to read end-to-end without a SDK abstraction layer.

Endpoints
---------
Trading        : https://paper-api.alpaca.markets/v2
Stock data     : https://data.alpaca.markets/v2
Crypto data    : https://data.alpaca.markets/v1beta3/crypto/us
"""

from __future__ import annotations

import logging
from typing import Any

import requests

from .config import load_config, trading_headers

log = logging.getLogger(__name__)

CFG          = load_config()
TRADING_URL  = CFG["endpoint"].rstrip("/")
STOCK_DATA   = "https://data.alpaca.markets/v2"
CRYPTO_DATA  = "https://data.alpaca.markets/v1beta3/crypto/us"
HEADERS      = trading_headers(CFG)
TIMEOUT      = 10


# ─────────────────────────── primitive HTTP helpers ──────────────────────
def _check(r: requests.Response) -> requests.Response:
    if r.status_code >= 400:
        log.error("Alpaca %s %s -> %d  body=%s",
                  r.request.method, r.url, r.status_code, r.text[:400])
        r.raise_for_status()
    return r


def get(path: str, params: dict | None = None, base: str = TRADING_URL) -> dict:
    return _check(requests.get(base + path, headers=HEADERS,
                               params=params, timeout=TIMEOUT)).json()


def post(path: str, body: dict, base: str = TRADING_URL) -> dict:
    return _check(requests.post(base + path, headers=HEADERS,
                                json=body, timeout=TIMEOUT)).json()


def delete(path: str, base: str = TRADING_URL) -> None:
    r = requests.delete(base + path, headers=HEADERS, timeout=TIMEOUT)
    if r.status_code not in (200, 204):
        _check(r)


# ────────────────────────────── account / clock ──────────────────────────
def get_account() -> dict:
    return get("/account")


def get_clock() -> dict:
    return get("/clock")


def get_positions() -> list[dict]:
    return get("/positions")


def get_position(symbol: str) -> dict | None:
    try:
        return get(f"/positions/{_safe(symbol)}")
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code == 404:
            return None
        raise


def cancel_all_orders() -> None:
    try:
        delete("/orders")
    except Exception as e:
        log.warning("cancel_all_orders: %s", e)


def close_position(symbol: str) -> None:
    try:
        delete(f"/positions/{_safe(symbol)}")
        log.info("Closed position in %s", symbol)
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code == 404:
            return
        log.warning("close_position(%s): %s", symbol, e)


def close_all_positions() -> None:
    try:
        delete("/positions?cancel_orders=true")
    except Exception as e:
        log.warning("close_all_positions: %s", e)


# ────────────────────────────── orders ──────────────────────────────────
def submit_market_qty(symbol: str, qty: float, side: str,
                      tif: str = "day") -> dict:
    """Whole or fractional share market order."""
    return post("/orders", {
        "symbol":        symbol,
        "qty":           f"{qty}",
        "side":          side,
        "type":          "market",
        "time_in_force": tif,
    })


def submit_market_notional(symbol: str, notional: float, side: str,
                           tif: str = "day") -> dict:
    """Notional (dollar-amount) market order."""
    return post("/orders", {
        "symbol":        symbol,
        "notional":      f"{notional:.2f}",
        "side":          side,
        "type":          "market",
        "time_in_force": tif,
    })


def submit_limit(symbol: str, qty: float, side: str, limit_price: float,
                 tif: str = "day") -> dict:
    return post("/orders", {
        "symbol":        symbol,
        "qty":           f"{qty}",
        "side":          side,
        "type":          "limit",
        "limit_price":   f"{limit_price:.4f}",
        "time_in_force": tif,
    })


def submit_trailing_stop(symbol: str, qty: float, side: str,
                         trail_percent: float, tif: str = "day") -> dict:
    return post("/orders", {
        "symbol":        symbol,
        "qty":           f"{qty}",
        "side":          side,
        "type":          "trailing_stop",
        "trail_percent": f"{trail_percent}",
        "time_in_force": tif,
    })


# ────────────────────────────── stock data ──────────────────────────────
def get_stock_bars(symbol: str, timeframe: str = "1Min",
                   limit: int = 60, feed: str = "iex") -> list[dict]:
    data = get(f"/stocks/{symbol}/bars",
               {"timeframe": timeframe, "limit": limit,
                "sort": "asc", "feed": feed},
               base=STOCK_DATA)
    return data.get("bars", [])


def get_stock_latest_trade(symbol: str, feed: str = "iex") -> float:
    data = get(f"/stocks/{symbol}/trades/latest", {"feed": feed},
               base=STOCK_DATA)
    return float(data["trade"]["p"])


def get_stock_latest_quote(symbol: str, feed: str = "iex") -> tuple[float, float]:
    """Returns (bid, ask)."""
    data = get(f"/stocks/{symbol}/quotes/latest", {"feed": feed},
               base=STOCK_DATA)
    q = data["quote"]
    return float(q["bp"]), float(q["ap"])


# ────────────────────────────── crypto data ─────────────────────────────
def get_crypto_bars(symbol: str, timeframe: str = "1Min",
                    limit: int = 60) -> list[dict]:
    data = get("/bars",
               {"symbols": symbol, "timeframe": timeframe, "limit": limit},
               base=CRYPTO_DATA)
    return data.get("bars", {}).get(symbol, [])


def get_crypto_latest_trade(symbol: str) -> float:
    data = get("/latest/trades", {"symbols": symbol}, base=CRYPTO_DATA)
    return float(data["trades"][symbol]["p"])


def get_crypto_latest_quote(symbol: str) -> tuple[float, float]:
    data = get("/latest/quotes", {"symbols": symbol}, base=CRYPTO_DATA)
    q = data["quotes"][symbol]
    return float(q["bp"]), float(q["ap"])


# ────────────────────────────── helpers ─────────────────────────────────
def _safe(symbol: str) -> str:
    """URL-encode symbols that contain a slash (crypto pairs like BTC/USD)."""
    return symbol.replace("/", "%2F")


def in_market_window(open_h: int = 9, open_m: int = 35,
                     close_h: int = 15, close_m: int = 45) -> bool:
    clock = get_clock()
    if not clock.get("is_open", False):
        return False
    from datetime import datetime
    ts = datetime.fromisoformat(clock["timestamp"])
    h, m = ts.hour, ts.minute
    return (h, m) >= (open_h, open_m) and (h, m) <= (close_h, close_m)
