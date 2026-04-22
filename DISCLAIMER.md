# DISCLAIMER

## Paper Trading Only

Every strategy in this repository was developed and tested **exclusively with
Alpaca's paper-trading API**. Paper trading uses simulated money against a
sandboxed copy of real market data — no real funds are ever at risk.

The authors **do not endorse, recommend, or warrant the use of any script in
this repository with live brokerage funds**. The scripts are research
artifacts produced as part of an undergraduate research project
(UMBC URCAD) on the behavior of large language models in simulated markets.

## Not Financial Advice

Nothing in this repository constitutes financial, investment, legal, or tax
advice. The strategies implemented here are illustrative — they exist to
demonstrate technical patterns (statistical signal generation, REST/websocket
order management, position lifecycle handling), **not** to be used as
profitable trading systems.

If you are considering investing real money, **consult a licensed financial
advisor**. Past simulated performance is not indicative of future results.
Real markets involve slippage, commissions, latency, partial fills, halts,
gaps, and many other frictions that paper trading does not faithfully model.

## What Could Go Wrong (with Real Money)

If you ignore this disclaimer and run any of these scripts against a live
account, you may lose money quickly. Specifically:

  - **Latency.** Strategies labelled "per-second" assume sub-second feedback
    loops. Network latency, broker queue depth, and exchange routing in a
    real environment will degrade fills.
  - **Slippage.** Paper-trade fills are simulated at the quoted price.
    Real fills, especially for larger size, walk through the order book.
  - **Overfitting.** Statistical thresholds, EWMA windows, and z-score
    cutoffs in this repo were tuned on a small slice of paper-trading data
    over a single research period. They are almost certainly overfit.
  - **Risk controls are minimal.** Stops are placeholder values. There is
    no portfolio-level VaR check, no correlation-aware position sizing, no
    circuit-breaker for unusual market conditions, no kill-switch.
  - **Crypto runs 24/7.** A crypto strategy left running unattended will
    keep trading through weekends, holidays, and any failure mode you have
    not anticipated.
  - **Bugs.** This is research code. It has not been audited.

## Use With Care, Even In Paper

Even in a paper-trading account, please:

  - Start with the smallest position-sizing parameters.
  - Keep logs and review them.
  - Be aware that excessive paper-trading activity can hit Alpaca rate
    limits and get your API key throttled.
  - Never share your `alpaca_config.json`. Treat paper credentials with
    the same care as live credentials — they are still tied to your
    account identity.

## TL;DR

Paper trading. Research only. Not advice. Talk to a financial advisor
before risking real money on anything you read here.
