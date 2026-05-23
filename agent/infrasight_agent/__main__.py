"""Entrada CLI: `python -m infrasight_agent`."""

from __future__ import annotations

import asyncio
import logging
import sys

from .agent import Agent
from .config import load_config

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def main() -> int:
    logging.basicConfig(level=logging.INFO, format=LOG_FORMAT, stream=sys.stdout)
    cfg = load_config()
    agent = Agent(cfg)
    try:
        asyncio.run(agent.run())
    except KeyboardInterrupt:
        logging.info("Agente detenido por el usuario")
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
