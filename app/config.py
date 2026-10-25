"""Validated environment configuration.

Supports:
  TRADING_MODE=paper   — simulated fills only (default, safest)
  TRADING_MODE=live    — real Binance Spot market orders (requires API keys + confirmation)
"""
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


def _bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _optional_float(name: str) -> float | None:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return None
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be numeric") from exc
    return value if value > 0 else None


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
    trailing_stop_pct: float = _float("TRAILING_STOP_PCT", 0.35)
    signal_confirmations: int = int(os.getenv("SIGNAL_CONFIRMATIONS", "3"))
    entry_min_score: float = _float("ENTRY_MIN_SCORE", 0.55)
    target_price: float | None = _optional_float("TARGET_PRICE")
    simulated_slippage_bps: float = _float("SIMULATED_SLIPPAGE_BPS", 2.0)
    simulated_latency_ms: int = int(os.getenv("SIMULATED_LATENCY_MS", "100"))
    simulated_partial_fill_probability: float = _float("SIMULATED_PARTIAL_FILL_PROBABILITY", 0.15)
    simulation_seed: int = int(os.getenv("SIMULATION_SEED", "0"))
    store_path: str = os.getenv("PAPER_DB_PATH", "data/paper.sqlite3")
    market_history_path: str = os.getenv("MARKET_HISTORY_PATH", "data/market-history.jsonl.gz")
    log_level: str = os.getenv("LOG_LEVEL", "INFO").upper()
    binance_api_key: str = os.getenv("BINANCE_API_KEY", "")
    binance_api_secret: str = os.getenv("BINANCE_API_SECRET", "")
    binance_testnet: bool = _bool("BINANCE_TESTNET", True)
    live_confirm: str = os.getenv("LIVE_CONFIRM", "")
    impact_coefficient: float = _float("IMPACT_COEFFICIENT", 0.1)
    features_db_path: str = os.getenv("FEATURES_DB_PATH", "data/features.sqlite3")
    execution_costs_path: str = os.getenv("EXECUTION_COSTS_PATH", "data/execution-costs.json")
    cors_origins: str = os.getenv("CORS_ORIGINS", "")
    jwt_secret: str = os.getenv("NEXORA_JWT_SECRET", "")
    jwt_ttl_seconds: int = int(os.getenv("NEXORA_JWT_TTL_SECONDS", "86400"))
    host: str = os.getenv("HOST", "0.0.0.0")
    port: int = int(os.getenv("PORT", "8000"))

    def validate(self) -> "Settings":
        if self.trading_mode not in ("paper", "live"):
            raise ValueError("TRADING_MODE must be 'paper' or 'live'.")
        if not self.symbol or not self.symbol.isalnum():
            raise ValueError("SYMBOL must be alphanumeric, e.g. btcusdt.")
        if self.starting_cash_usdt <= 0 or self.order_size_usdt <= 0:
            raise ValueError("Starting cash and order size must be positive.")
        if self.order_size_usdt > self.max_order_size_usdt:
            raise ValueError("ORDER_SIZE_USDT cannot exceed MAX_ORDER_SIZE_USDT.")
        if not 0 <= self.fee_rate < 0.1:
            raise ValueError("FEE_RATE must be between 0 and 0.1.")
        if min(
            self.max_order_size_usdt,
            self.max_daily_loss_usdt,
            self.max_spread_bps,
            self.max_data_age_seconds,
            self.take_profit_pct,
            self.stop_loss_pct,
        ) <= 0:
            raise ValueError("Risk limits and TP/SL percentages must be positive.")
        if self.trailing_stop_pct < 0:
            raise ValueError("TRAILING_STOP_PCT cannot be negative.")
        if self.max_consecutive_losses < 1 or self.signal_confirmations < 1:
            raise ValueError("Loss and signal confirmation counts must be at least 1.")
        if self.simulated_latency_ms < 0 or self.simulated_slippage_bps < 0:
            raise ValueError("Simulated latency and slippage cannot be negative.")
        if not 0 <= self.simulated_partial_fill_probability <= 1:
            raise ValueError("SIMULATED_PARTIAL_FILL_PROBABILITY must be in [0, 1].")
        if not 0.5 < self.imbalance_threshold <= 1:
            raise ValueError("IMBALANCE_THRESHOLD must be in (0.5, 1].")
        if self.impact_coefficient < 0:
            raise ValueError("IMPACT_COEFFICIENT cannot be negative.")
        if not 0 < self.entry_min_score <= 1:
            raise ValueError("ENTRY_MIN_SCORE must be in (0, 1].")
        if self.trading_mode == "live":
            if not self.binance_api_key or not self.binance_api_secret:
                raise ValueError(
                    "TRADING_MODE=live requires BINANCE_API_KEY and BINANCE_API_SECRET."
                )
            if not self.binance_testnet and self.live_confirm != "I_UNDERSTAND_REAL_MONEY":
                raise ValueError(
                    "Mainnet live trading requires LIVE_CONFIRM=I_UNDERSTAND_REAL_MONEY "
                    "and BINANCE_TESTNET=false. Keep withdrawal permissions disabled "
                    "and use an IP-restricted API key. Testnet validation and "
                    "independent net-of-cost evaluation are strongly recommended first."
                )
        return self


settings = Settings().validate()
