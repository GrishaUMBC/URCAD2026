#!/bin/bash
# Quick launcher — runs one equity strategy in the foreground. Edit the
# `STRATEGY` variable below to change which one. Reads alpaca_config.json
# from the repository root.
#
# PAPER TRADING ONLY. SEE DISCLAIMER.md.

set -e

STRATEGY="${1:-spy_per_second_predictor}"

cd "$(dirname "$0")/.."

if [ ! -f alpaca_config.json ]; then
    echo "ERROR: alpaca_config.json not found in repo root."
    echo "Copy alpaca_config.example.json -> alpaca_config.json and add your"
    echo "PAPER trading credentials from https://alpaca.markets."
    exit 1
fi

echo "Starting equity/${STRATEGY}.py …  (Ctrl-C to stop and flatten)"
python3 "equity/${STRATEGY}.py"
