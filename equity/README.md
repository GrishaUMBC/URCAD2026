# Equity Strategies

Six paper-trading strategies operating on US stocks / ETFs. All scripts
in this folder run only against Alpaca's paper-trading endpoint and are
intended exclusively as research artifacts.

> **PAPER TRADING ONLY. NOT FINANCIAL ADVICE.** See top-level
> [DISCLAIMER.md](../DISCLAIMER.md). Talk to a licensed financial advisor
> before risking real money on anything in this folder.

| Script | Cadence | Symbols | Description |
|---|---|---|---|
| `spy_per_second_predictor.py` | every 1s | SPY | Logit over 5 micro-features → P(up next second). Headline strategy. |
| `multi_asset_momentum_rotator.py` | every 30s | 8 ETFs | Holds top-3 by momentum, rebalances continuously. |
| `pairs_trading_spy_qqq.py` | every 5s | SPY/QQQ | Mean-reverts the SPY/QQQ residual via rolling β + z-score. |
| `zscore_mean_reversion_basket.py` | every 10s | 8 sector ETFs | Independent contrarian z-score legs across sectors. |
| `opening_range_breakout.py` | every 5s | SPY | Defines OR in first 15 minutes, takes one breakout per day. |
| `vwap_reversion.py` | every 15s | SPY | Trades deviations from session VWAP back toward the mean. |

## Run

From the repository root:

```bash
python equity/spy_per_second_predictor.py
python equity/multi_asset_momentum_rotator.py
# ...etc
```

Each script writes its log to `logs/<name>.log` and prints to stdout.

## Common Parameters

Most strategies share these knobs at the top of the file:

- `MAX_DAILY_LOSS_PCT` — daily kill-switch threshold
- `MARKET_OPEN_HM` / `MARKET_CLOSE_HM` — trading window (avoid open / close)
- `ALLOW_SHORTS` — disabled by default; only enable if your paper account
  has short-selling approval

## Safety Reminders

1. Verify `alpaca_config.json` points at `paper-api.alpaca.markets` —
   `common/config.py` will refuse to load any other endpoint.
2. Always test changes on a single script first.
3. The strategy parameters are illustrative, NOT optimized.
