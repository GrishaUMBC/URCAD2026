#!/usr/bin/env python3
"""
EMERGENCY FLATTEN: cancel all open orders and close every open position.

Use this if a strategy script crashes mid-run, or if you just want a
clean slate before starting a new session.

PAPER TRADING ONLY. Even though the underlying API call is the same,
common.config.load_config() will refuse to load anything that isn't
pointed at the paper-trading endpoint.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common import alpaca_rest as ax


def main():
    print("Cancelling all open orders…")
    ax.cancel_all_orders()
    print("Closing all open positions…")
    ax.close_all_positions()
    print("Done. Run scripts/check_account.py to verify.")


if __name__ == "__main__":
    main()
