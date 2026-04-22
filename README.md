# URCAD HFT — LLM Paper-Trading Research Framework

A collection of high-frequency paper-trading strategies developed as the
automated-execution arm of an undergraduate research project (UMBC URCAD)
studying how leading large language models perform in simulated stock
markets.

> ## ⚠ PAPER TRADING ONLY — NOT FINANCIAL ADVICE
>
> Every script in this repository was developed and tested **exclusively
> against Alpaca's paper-trading API**. The authors **do not endorse,
> recommend, or warrant the use of any code in this repository with live
> brokerage funds**. Nothing here is financial advice. **Consult a
> licensed financial advisor before making any real-money investment
> decisions.** See [DISCLAIMER.md](DISCLAIMER.md) for the full notice.

---

## What This Is

The parent research project — *Comparative Performance of Leading Large
Language Models in Simulated Stock Markets* — runs in two parallel
tracks:

1. **MarketWatch simulation.** Five LLMs (Claude Opus 4.6, ChatGPT 5.2,
   Gemini 3 Pro, GLM-5, Kimi K2.5) compete in a multi-week MarketWatch
   stock simulation. Each week, every model receives updated portfolio
   positions and is asked to buy / sell / hold / short / place limit or
   market orders. Performance is measured by total return, cumulative
   profit, weekly return consistency, and portfolio volatility.
2. **Automated paper-trading framework** — *this repository*. An
   independent track that integrates a brokerage paper-trading API
   (Alpaca) with statistical / algorithmic strategies, enabling
   higher-frequency systematic testing outside the weekly MarketWatch
   cadence.

The strategies in this repo are a mix of textbook patterns (pairs
trading, mean reversion, breakout, VWAP, momentum rotation) and
short-horizon statistical predictors built specifically for the
paper-trading framework.

---

## Repository Layout

```
.
├── README.md                       — this file
├── DISCLAIMER.md                   — full paper-trading-only notice
├── LICENSE                         — short permissive notice
├── requirements.txt                — Python dependencies
├── alpaca_config.example.json      — placeholder for your API credentials
├── .gitignore                      — keeps secrets out of git
│
├── common/                         — shared utilities
│   ├── config.py                   — credential loader, paper-only guard
│   ├── alpaca_rest.py              — thin REST wrapper (stocks + crypto)
│   ├── indicators.py               — RSI, MACD, EMA, ATR, VWAP, z-score…
│   └── logging_setup.py            — uniform per-strategy logging
│
├── equity/                         — US stock / ETF strategies
│   ├── spy_per_second_predictor.py     — 1Hz statistical direction predictor
│   ├── multi_asset_momentum_rotator.py — top-N momentum across 8 ETFs
│   ├── pairs_trading_spy_qqq.py        — SPY/QQQ residual mean-reversion
│   ├── zscore_mean_reversion_basket.py — sector-ETF contrarian basket
│   ├── opening_range_breakout.py       — classic ORB
│   └── vwap_reversion.py               — VWAP deviation reversion
│
├── crypto/                         — 24/7 crypto strategies
│   ├── btc_per_second_predictor.py     — BTC twin of the equity predictor
│   ├── crypto_momentum_rotator.py      — top-N momentum across 8 pairs
│   ├── crypto_zscore_mean_reversion.py — long-only contrarian z-score
│   ├── btc_eth_pairs_trading.py        — BTC/ETH spread reversion
│   └── crypto_volatility_breakout.py   — Donchian breakout w/ ATR trail
│
├── scripts/                        — operational helpers
│   ├── check_account.py            — equity, buying power, open positions
│   ├── close_all_positions.py      — emergency flatten
│   └── run_equity_market_hours.sh  — convenience launcher
│
└── logs/                           — per-strategy log files (auto-created)
```

---

## Setup

### 1. Install Python dependencies

Python 3.10+ recommended.

```bash
pip install -r requirements.txt
```

### 2. Add your Alpaca PAPER trading credentials

Sign in at https://alpaca.markets, navigate to **Paper Trading → API
Keys**, and generate a key pair.

```bash
cp alpaca_config.example.json alpaca_config.json
# then edit alpaca_config.json and fill in:
#   "api_key":    "YOUR_PAPER_KEY"
#   "api_secret": "YOUR_PAPER_SECRET"
```

`alpaca_config.json` is in `.gitignore` and **must never be committed**.
`common/config.py` will refuse to load any config whose endpoint is not
the paper-trading host — this is a hard guardrail to prevent accidental
live-account use.

### 3. Verify the connection

```bash
python scripts/check_account.py
```

Expected output:

```
────────────────────────────────────────────────────────────
PAPER ACCOUNT  status=ACTIVE
  equity            $    100,000.00
  cash              $    100,000.00
  buying_power      $    400,000.00
  ...
OPEN POSITIONS: (none)
```

---

## Running a Strategy

Each script is fully self-contained — strategy parameters are at the
top, logging is auto-configured, signals are handled gracefully (Ctrl-C
flattens any open position). Run from the repository root:

```bash
# Headline strategy — per-second SPY direction predictor
python equity/spy_per_second_predictor.py

# Crypto twin (24/7 — auto-stops after MAX_RUN_HOURS)
python crypto/btc_per_second_predictor.py

# Multi-asset momentum rotator
python equity/multi_asset_momentum_rotator.py
```

Each strategy writes to `logs/<strategy_name>.log` *and* prints to
stdout, so you can tail the log or monitor live.

### Stop / clean up

Ctrl-C will trigger the strategy's shutdown handler, which cancels all
open orders and flattens any open position. If a script crashes
ungracefully:

```bash
python scripts/close_all_positions.py
```

---

## Strategies in Detail

### Equity (US stocks / ETFs)

#### `spy_per_second_predictor.py` — *headline strategy*
Polls SPY's last-trade price every second. Maintains a 3-minute rolling
buffer and computes five micro-features (fast & slow EWMA slopes,
60-second z-score, 30-second uptick frequency, 60-second realized
volatility). Combines them via a fixed-weight logit into an estimate of
P(next-second price moves up). Enters long when P ≥ 0.56, exits / shorts
when P ≤ 0.44. Position sizing scales with conviction.

#### `multi_asset_momentum_rotator.py`
Tracks 8 sector / index ETFs. Every 30 seconds, ranks them by
price-normalized linear-regression slope and rotates the portfolio so
that the top-3 most positively trending names are held with equal-weight
notional. Liquidates anything that drops out.

#### `pairs_trading_spy_qqq.py`
SPY and QQQ have huge mega-cap overlap, so their *spread* mean-reverts.
Every 5 seconds: refit a rolling OLS hedge ratio β, compute spread =
QQQ − β·SPY, z-score it. Take a contrarian bet when |z| ≥ 2.0, unwind
when |z| ≤ 0.4. Long-only by default; turn on `ALLOW_SHORTS` if your
paper account supports short selling.

#### `zscore_mean_reversion_basket.py`
Per-symbol contrarian z-score legs across 8 sector ETFs. Each name is
treated independently — when its log-return distribution stretches
beyond ±1.8σ, open a position betting on reversion. Up to 4 legs open
simultaneously.

#### `opening_range_breakout.py`
Classic ORB. Defines the "opening range" as the high/low of SPY's first
15 minutes after the open, then takes one breakout per day with an
ATR-relative profit target and stop.

#### `vwap_reversion.py`
Computes intraday VWAP from one-minute bars and trades deviations back
toward the volume-weighted mean. Exits on cross-back, profit target, or
hard stop.

### Crypto (24/7)

#### `btc_per_second_predictor.py`
BTC/USD twin of the SPY predictor. Same five-feature logit, wider
profit/stop bands to suit BTC's higher per-second variance. Long-only
(Alpaca paper crypto does not support shorts). Self-terminates after
`MAX_RUN_HOURS`.

#### `crypto_momentum_rotator.py`
Top-N momentum across 8 crypto pairs (BTC, ETH, SOL, AVAX, LINK, DOGE,
LTC, BCH). 30-second rebalance cadence.

#### `crypto_zscore_mean_reversion.py`
Long-only contrarian per-pair z-score legs. Designed to coexist with the
momentum rotator — they have opposite directional biases and can hedge.

#### `btc_eth_pairs_trading.py`
BTC and ETH are highly correlated. Models the log-price spread with a
rolling OLS hedge ratio, z-scores it, and goes long whichever leg looks
*cheap*. Skips rich-spread signals (no shorts in paper crypto).

#### `crypto_volatility_breakout.py`
Donchian-style breakout: enters long when price clears the prior
60-bar high by a buffer; trails an ATR-scaled stop; exits on stop,
profit target, or `MAX_HOLD_MINUTES`.

---

## Common Engineering Patterns

Every strategy script follows the same template:

1. **Top-of-file parameters block.** All knobs (thresholds, lookbacks,
   notional %s, risk caps) are constants at the top — easy to tune
   without scrolling through the logic.
2. **Paper-only credential loader.** `common.config.load_config()`
   refuses any non-paper endpoint and refuses to load placeholder
   credentials.
3. **Per-strategy log file.** `common/logging_setup.py` writes to
   `logs/<strategy>.log` so concurrent strategies don't collide.
4. **Daily kill-switch.** `MAX_DAILY_LOSS_PCT` halts trading if equity
   drops more than the configured fraction since startup.
5. **Market-window guard** (equity only). Trades only inside
   `MARKET_OPEN_HM` ↔ `MARKET_CLOSE_HM` (default 9:35 ↔ 15:45 ET).
6. **Self-terminate ceiling** (crypto only). Each crypto script enforces
   a `MAX_RUN_HOURS` so an unattended bot doesn't keep trading
   indefinitely.
7. **Graceful shutdown.** SIGINT / SIGTERM handlers cancel open orders
   and flatten open positions before exit.

---

## Why "Frequently Updates Positions"

The research framework needed strategies that exercise the full
order-management lifecycle, not just one-shot trades. Several scripts
(`multi_asset_momentum_rotator`, `zscore_mean_reversion_basket`,
`crypto_momentum_rotator`, `crypto_zscore_mean_reversion`) actively
manage a multi-symbol portfolio with continuous rebalancing — entries,
liquidations, sizing changes — so the framework gets meaningful
coverage of REST endpoints, error paths, and position-state transitions.

---

## Limitations & Things This Code Does Not Do

In keeping with the disclaimer, the following are **deliberately not
implemented** and would be required before any live use:

- Backtesting harness (these are forward-only paper bots)
- Walk-forward parameter optimization
- Slippage / impact modelling
- Cross-strategy portfolio-level VaR or correlation budget
- Pattern-day-trader rule tracking
- Tax-lot accounting
- Order-routing optimization (everything is a market order via Alpaca)
- Persistent state across restarts (all positions are in-memory; on
  restart, prior holdings are not re-attached to a strategy's state
  machine — use `scripts/close_all_positions.py` between sessions)
- Authentication beyond a static config file

---

## Contributing

This is an undergraduate research artifact. Pull requests adding
**additional paper-only strategies**, **better risk controls**, or
**clearer documentation** are welcome. Anything that touches live-trading
endpoints will be rejected.

---

## License & Reuse

Public-domain-style: free to use, copy, modify, redistribute. No
warranty. See [LICENSE](LICENSE) and [DISCLAIMER.md](DISCLAIMER.md) for
the full notice — the only restriction we ask anyone to honor is the
**"paper trading only — talk to a financial advisor before risking real
money"** spirit of the project.
