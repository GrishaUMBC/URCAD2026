# Crypto Strategies

Five paper-trading strategies operating on Alpaca crypto pairs. Crypto
markets trade 24/7 — every script in this folder enforces a
`MAX_RUN_HOURS` self-terminate so an unattended bot doesn't keep trading
through the night.

> **PAPER TRADING ONLY. NOT FINANCIAL ADVICE.** See top-level
> [DISCLAIMER.md](../DISCLAIMER.md). Crypto markets are highly volatile;
> talk to a licensed financial advisor before risking real money on
> anything in this folder.

| Script | Cadence | Symbols | Description |
|---|---|---|---|
| `btc_per_second_predictor.py` | every 1s | BTC/USD | Logit over 5 micro-features → P(up next second). |
| `crypto_momentum_rotator.py` | every 30s | 8 pairs | Holds top-3 by momentum, rebalances continuously. |
| `crypto_zscore_mean_reversion.py` | every 10s | 6 pairs | Long-only contrarian z-score legs. |
| `btc_eth_pairs_trading.py` | every 10s | BTC/ETH | OLS hedge + z-score of log-price spread. |
| `crypto_volatility_breakout.py` | every 30s | BTC/USD | Donchian breakout with ATR-trailing stop. |

## Crypto vs Equity — Important Differences

1. **24/7 markets.** No `in_market_window()` guard. Each script enforces
   a `MAX_RUN_HOURS` ceiling so an unattended run stops itself.
2. **Long-only.** Alpaca paper crypto does not currently support short
   selling. Strategies that *would* go short on a signal (e.g. the
   pairs-trading rich-spread case) instead skip and log it.
3. **Wider stops & targets.** BTC's per-second variance is roughly
   10× SPY's, so PROFIT_TARGET_PCT and STOP_LOSS_PCT are wider.
4. **Symbol notation.** Crypto pairs use `"BTC/USD"`, not `"BTC"`.
   `common.alpaca_rest` URL-encodes the slash for endpoints that need it.
5. **Smaller notional minimums.** Some pairs accept ≥$1 orders. Others
   may require more. The scripts skip orders below a small threshold.

## Run

From the repository root:

```bash
python crypto/btc_per_second_predictor.py
python crypto/crypto_momentum_rotator.py
# ...etc
```

## Universe Customization

Each script defines its `UNIVERSE` (or symbols) at the top of the file.
Make sure every symbol you add is supported by your Alpaca paper
account — list available pairs at https://docs.alpaca.markets/docs/crypto-trading.

## Suggested Combinations

These can be run concurrently (each writes to its own log):

  - `crypto_momentum_rotator.py` + `crypto_zscore_mean_reversion.py`
    — opposite directional biases, can hedge each other
  - `btc_per_second_predictor.py` + `crypto_volatility_breakout.py`
    — fast intraday + slower swing
