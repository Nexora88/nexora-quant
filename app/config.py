"""Runtime settings from environment (.env).

Key knobs:
  TRADING_MODE=paper|live
  ENTRY_MIN_SCORE — paper default 0.28 (learning); raise for live
  UNIVERSE_AUTO — screen ~30 majors → DEPTH_TOP_N L2 streams
  MARKET_HISTORY_ENABLED — off by default (avoids backpressure noise)
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()


def _bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return float(raw)


def _int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return int(raw)


@dataclass(frozen=True)
class Settings:
    trading_mode: str = os.getenv("TRADING_MODE", "paper").strip().lower() or "paper"
    symbol: str = (os.getenv("SYMBOL", "btcusdt") or "btcusdt").strip().lower()
    binance_api_key: str = os.getenv("BINANCE_API_KEY", "") or ""
    binance_api_secret: str = os.getenv("BINANCE_API_SECRET", "") or ""
    binance_testnet: bool = _bool("BINANCE_TESTNET", True)

    starting_cash_usdt: float = _float("STARTING_CASH_USDT", 30.0)
    order_size_usdt: float = _float("ORDER_SIZE_USDT", 8.0)
    max_order_size_usdt: float = _float("MAX_ORDER_SIZE_USDT", 10.0)
    min_order_usdt: float = _float("MIN_ORDER_USDT", 5.0)

    universe_auto: bool = _bool("UNIVERSE_AUTO", True)
    depth_top_n: int = _int("DEPTH_TOP_N", 5)
    universe_min_quote_volume: float = _float("UNIVERSE_MIN_QUOTE_VOLUME", 5_000_000.0)

    autonomous_mode: bool = _bool("AUTONOMOUS_MODE", True)
    autonomous_symbol: bool = _bool("AUTONOMOUS_SYMBOL", True)

    max_daily_loss_usdt: float = _float("MAX_DAILY_LOSS_USDT", 5.0)
    max_consecutive_losses: int = _int("MAX_CONSECUTIVE_LOSSES", 5)
    compound_fraction: float = _float("COMPOUND_FRACTION", 0.85)

    take_profit_pct: float = _float("TAKE_PROFIT_PCT", 1.20)
    stop_loss_pct: float = _float("STOP_LOSS_PCT", 0.35)
    trailing_stop_pct: float = _float("TRAILING_STOP_PCT", 0.25)
    min_reward_risk_ratio: float = _float("MIN_REWARD_RISK_RATIO", 2.0)

    entry_min_score: float = _float("ENTRY_MIN_SCORE", 0.28)
    signal_confirmations: int = _int("SIGNAL_CONFIRMATIONS", 1)
    imbalance_threshold: float = _float("IMBALANCE_THRESHOLD", 0.55)

    fee_rate: float = _float("FEE_RATE", 0.001)
    fee_use_bnb_discount: bool = _bool("FEE_USE_BNB_DISCOUNT", False)

    max_spread_bps: float = _float("MAX_SPREAD_BPS", 8.0)
    max_data_age_seconds: float = _float("MAX_DATA_AGE_SECONDS", 5.0)
    impact_coefficient: float = _float("IMPACT_COEFFICIENT", 0.1)

    target_price: float | None = (
        float(os.getenv("TARGET_PRICE")) if os.getenv("TARGET_PRICE") else None
    )
    target_equity_usdt: float | None = (
        float(os.getenv("TARGET_EQUITY_USDT"))
        if os.getenv("TARGET_EQUITY_USDT")
        else None
    )

    market_history_enabled: bool = _bool("MARKET_HISTORY_ENABLED", False)
    market_history_path: str = os.getenv("MARKET_HISTORY_PATH", "data/market-history.jsonl.gz") or "data/market-history.jsonl.gz"
    market_history_max_pending: int = _int("MARKET_HISTORY_MAX_PENDING", 4000)

    log_level: str = (os.getenv("LOG_LEVEL", "INFO") or "INFO").upper()

    def watch_symbols(self) -> tuple[str, ...]:
        raw = os.getenv("WATCH_SYMBOLS", "") or ""
        parts = [p.strip().lower() for p in raw.split(",") if p.strip()]
        return tuple(parts)

    def validate(self) -> None:
        if self.trading_mode not in {"paper", "live"}:
            raise ValueError("TRADING_MODE must be paper or live")
        if self.order_size_usdt <= 0 or self.max_order_size_usdt <= 0:
            raise ValueError("order sizes must be positive")
        if not 0 < self.entry_min_score <= 1:
            raise ValueError("ENTRY_MIN_SCORE must be in (0, 1]")
        if self.trading_mode == "live" and (
            not self.binance_api_key or not self.binance_api_secret
        ):
            raise ValueError("live mode requires BINANCE_API_KEY and BINANCE_API_SECRET")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    s = Settings()
    s.validate()
    return s


settings = get_settings()
