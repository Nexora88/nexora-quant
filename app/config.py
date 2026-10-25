"""Validated environment configuration; exchange order submission stays disabled."""
from dataclasses import dataclass
import os

from dotenv import load_dotenv

load_dotenv()


def _float(name: str, default: float) -> float:
    raw = os.getenv(name)
    try:
        return default if raw is None else float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be numeric") from exc


@dataclass(frozen=True, slots=True)
class Settings:
    symbol: str = os.getenv("SYMBOL", "btcusdt").lower()
    trading_mode: str = os.getenv("TRADING_MODE", "paper").lower()
    starting_cash_usdt: float = _float("STARTING_CASH_USDT", 1000.0)
    order_size_usdt: float = _float("ORDER_SIZE_USDT", 25.0)
    fee_rate: float = _float("FEE_RATE", 0.001)
    max_order_size_usdt: float = _float("MAX_ORDER_SIZE_USDT", 50.0)
    max_daily_loss_usdt: float = _float("MAX_DAILY_LOSS_USDT", 25.0)
    max_consecutive_losses: int = int(os.getenv("MAX_CONSECUTIVE_LOSSES", "3"))
    max_spread_bps: float = _float("MAX_SPREAD_BPS", 20.0)
    max_data_age_seconds: float = _float("MAX_DATA_AGE_SECONDS", 5.0)
    imbalance_threshold: float = _float("IMBALANCE_THRESHOLD", 0.70)
    take_profit_pct: float = _float("TAKE_PROFIT_PCT", 1.0)
    stop_loss_pct: float = _float("STOP_LOSS_PCT", 0.5)
    signal_confirmations: int = int(os.getenv("SIGNAL_CONFIRMATIONS", "3"))
    simulated_slippage_bps: float = _float("SIMULATED_SLIPPAGE_BPS", 2.0)
    simulated_latency_ms: int = int(os.getenv("SIMULATED_LATENCY_MS", "100"))
    simulated_partial_fill_probability: float = _float("SIMULATED_PARTIAL_FILL_PROBABILITY", 0.15)
    simulation_seed: int = int(os.getenv("SIMULATION_SEED", "0"))
    store_path: str = os.getenv("PAPER_DB_PATH", "data/paper.sqlite3")
    market_history_path: str = os.getenv("MARKET_HISTORY_PATH", "data/market-history.jsonl.gz")
    log_level: str = os.getenv("LOG_LEVEL", "INFO").upper()

    def validate(self) -> "Settings":
        if self.trading_mode != "paper":
            raise ValueError("Only TRADING_MODE=paper is supported; live execution is disabled.")
        if not self.symbol or not self.symbol.isalnum():
            raise ValueError("SYMBOL must be alphanumeric, e.g. btcusdt.")
        if self.starting_cash_usdt <= 0 or self.order_size_usdt <= 0:
            raise ValueError("Starting cash and order size must be positive.")
        if self.order_size_usdt > self.max_order_size_usdt:
            raise ValueError("ORDER_SIZE_USDT cannot exceed MAX_ORDER_SIZE_USDT.")
        if not 0 <= self.fee_rate < 0.1:
            raise ValueError("FEE_RATE must be between 0 and 0.1.")
        if min(self.max_order_size_usdt, self.max_daily_loss_usdt, self.max_spread_bps,
               self.max_data_age_seconds, self.take_profit_pct, self.stop_loss_pct) <= 0:
            raise ValueError("Risk limits and TP/SL percentages must be positive.")
        if self.max_consecutive_losses < 1 or self.signal_confirmations < 1:
            raise ValueError("Loss and signal confirmation counts must be at least 1.")
        if self.simulated_latency_ms < 0 or self.simulated_slippage_bps < 0:
            raise ValueError("Simulated latency and slippage cannot be negative.")
        if not 0 <= self.simulated_partial_fill_probability <= 1:
            raise ValueError("SIMULATED_PARTIAL_FILL_PROBABILITY must be in [0, 1].")
        if not 0.5 < self.imbalance_threshold <= 1:
            raise ValueError("IMBALANCE_THRESHOLD must be in (0.5, 1].")
        return self


settings = Settings().validate()
