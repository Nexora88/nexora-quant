"""Command-line entry point."""
import argparse
import asyncio
import logging
from app.config import settings
from app.engine import run


def main() -> None:
    parser = argparse.ArgumentParser(description="Nexora Quant autonomous trading")
    parser.add_argument(
        "--once",
        action="store_true",
        help="validate and print configuration without connecting",
    )
    args = parser.parse_args()
    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    if args.once:
        mode = settings.trading_mode
        print(f"Nexora Quant | symbol={settings.symbol.upper()} | mode={mode}")
        print(f"Target price: {settings.target_price or 'disabled'}")
        print(
            f"TP={settings.take_profit_pct}% SL={settings.stop_loss_pct}% "
            f"Trail={settings.trailing_stop_pct}% min_score={settings.entry_min_score}"
        )
        if mode == "paper":
            print("Orders: simulated (paper)")
            print(f"Paper starting cash: {settings.starting_cash_usdt:.2f} USDT")
        else:
            net = "TESTNET" if settings.binance_testnet else "MAINNET (REAL MONEY)"
            print(f"Orders: LIVE ({net})")
        print("Dashboard: uvicorn app.api:app --host 0.0.0.0 --port 8000")
        return
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        logging.getLogger(__name__).info("Shutdown requested")


if __name__ == "__main__":
    main()
