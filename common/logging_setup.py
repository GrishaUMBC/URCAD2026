"""
Uniform logging configuration used by every strategy script.

Each strategy gets its own log file under logs/<name>.log so concurrent
strategies don't trample each other's output.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path


def configure(name: str, level: int = logging.INFO) -> logging.Logger:
    """Configure root logger with a console + file handler scoped to `name`."""
    log_dir = Path(__file__).resolve().parent.parent / "logs"
    log_dir.mkdir(exist_ok=True)
    log_path = log_dir / f"{name}.log"

    fmt = logging.Formatter(
        "%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    logger = logging.getLogger()
    logger.setLevel(level)
    logger.handlers.clear()

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    logger.addHandler(console)

    fileh = logging.FileHandler(log_path, encoding="utf-8")
    fileh.setFormatter(fmt)
    logger.addHandler(fileh)

    logger.info("Logging to %s", log_path)
    return logger
