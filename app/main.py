"""Command-line entry point."""
import argparse
import asyncio
import logging
from app.config import settings
from app.engine import run

def main() -> None:
    parser = argparse.ArgumentParser(description="Nexora Quant (paper trading only)")
    parser.add_argument("--once", action="store_true", help="validate and print configuration without connecting")
    args = parser.parse_args()
    logging.basicConfig(level=getattr(logging, settings.log_level, logging.INFO), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if args.once:
        print(f"Nexora Quant | symbol={settings.symbol.upper()} | mode=paper")
        print("Live order submission: disabled")
        print(f"Paper starting cash: {settings.starting_cash_usdt:.2f} USDT")
        return
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        logging.getLogger(__name__).info("Shutdown requested")

if __name__ == "__main__":
    main()
