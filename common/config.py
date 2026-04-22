"""
Credential loader for Alpaca paper-trading API.

Reads alpaca_config.json from the repository root (or a path provided via the
ALPACA_CONFIG environment variable). Refuses to load any config whose
endpoint does not point at the paper-trading host — this is a hard guardrail
to prevent accidental live-account usage.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

PAPER_HOST = "paper-api.alpaca.markets"


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _resolve_config_path() -> Path:
    env = os.environ.get("ALPACA_CONFIG")
    if env:
        return Path(env).expanduser().resolve()
    return _repo_root() / "alpaca_config.json"


def load_config() -> dict[str, Any]:
    """
    Load and validate Alpaca credentials.

    Raises FileNotFoundError if alpaca_config.json is missing.
    Raises RuntimeError if the configured endpoint is not the paper host.
    """
    path = _resolve_config_path()
    if not path.exists():
        example = _repo_root() / "alpaca_config.example.json"
        msg = (
            f"alpaca_config.json not found at {path}.\n"
            f"Copy {example.name} → alpaca_config.json and fill in your "
            f"PAPER trading API credentials from https://alpaca.markets."
        )
        raise FileNotFoundError(msg)

    with path.open() as f:
        cfg = json.load(f)

    endpoint = cfg.get("endpoint", "")
    if PAPER_HOST not in endpoint:
        raise RuntimeError(
            f"Refusing to load config: endpoint {endpoint!r} is not the "
            f"paper-trading host. Every script in this repo is paper-only."
        )

    if not cfg.get("api_key") or not cfg.get("api_secret"):
        raise RuntimeError("alpaca_config.json is missing api_key or api_secret.")

    if "YOUR_ALPACA" in cfg["api_key"] or "YOUR_ALPACA" in cfg["api_secret"]:
        raise RuntimeError(
            "alpaca_config.json still contains placeholder values. "
            "Fill in your real paper-trading API key + secret."
        )

    return cfg


def trading_headers(cfg: dict[str, Any] | None = None) -> dict[str, str]:
    cfg = cfg or load_config()
    return {
        "APCA-API-KEY-ID":     cfg["api_key"],
        "APCA-API-SECRET-KEY": cfg["api_secret"],
        "Content-Type":        "application/json",
    }


if __name__ == "__main__":
    try:
        cfg = load_config()
        print(f"OK — loaded paper config for endpoint {cfg['endpoint']}")
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
