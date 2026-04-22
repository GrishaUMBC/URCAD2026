#!/usr/bin/env python3
"""
Account snapshot — equity, buying power, and open positions.

Useful sanity check before/after running any of the strategies.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common import alpaca_rest as ax


def main():
    acct = ax.get_account()
    print("─" * 60)
    print(f"PAPER ACCOUNT  status={acct.get('status')}")
    print(f"  equity            ${float(acct['equity']):>14,.2f}")
    print(f"  cash              ${float(acct['cash']):>14,.2f}")
    print(f"  buying_power      ${float(acct['buying_power']):>14,.2f}")
    print(f"  portfolio_value   ${float(acct['portfolio_value']):>14,.2f}")
    print(f"  daytrade_count    {acct.get('daytrade_count', 'n/a')}")
    print(f"  pattern_daytrader {acct.get('pattern_day_trader', 'n/a')}")

    print("─" * 60)
    positions = ax.get_positions()
    if not positions:
        print("OPEN POSITIONS: (none)")
        return
    print(f"OPEN POSITIONS ({len(positions)})")
    print(f"  {'symbol':<12} {'qty':>14} {'avg_entry':>12} {'mkt_value':>14} {'pnl_$':>12} {'pnl_%':>8}")
    for p in positions:
        sym  = p["symbol"]
        qty  = float(p["qty"])
        avg  = float(p["avg_entry_price"])
        mv   = float(p.get("market_value", 0))
        pnl  = float(p.get("unrealized_pl", 0))
        pnlp = float(p.get("unrealized_plpc", 0)) * 100
        print(f"  {sym:<12} {qty:>14,.4f} {avg:>12,.2f} {mv:>14,.2f} "
              f"{pnl:>+12,.2f} {pnlp:>+7.2f}%")


if __name__ == "__main__":
    main()
