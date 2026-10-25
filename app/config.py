"""Validated environment configuration. Live execution is intentionally unsupported."""
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
        if min(self.max_order_size_usdt, self.max_daily_loss_usdt, self.max_spread_bps, self.max_data_age_seconds) <= 0:
            raise ValueError("Risk limits must be positive.")
        if self.max_consecutive_losses < 1:
            raise ValueError("MAX_CONSECUTIVE_LOSSES must be at least 1.")
        if not 0.5 < self.imbalance_threshold <= 1:
            raise ValueError("IMBALANCE_THRESHOLD must be in (0.5, 1].")
        return self

settings = Settings().validate()
