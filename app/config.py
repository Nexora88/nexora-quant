"""Validated environment configuration.

  TRADING_MODE=paper | live
  AUTONOMOUS_MODE=true — self-decide; soft filters
  COMPOUND_FRACTION — redeploy free cash (small wins stack)
  MIN_REWARD_RISK_RATIO — require TP/SL asymmetry for expectancy
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
    # Comma-separated extra pairs for paper multi-stream capture (not concurrent live orders).
    symbols_raw: str = os.getenv("SYMBOLS", "")
    trading_mode: str = os.getenv("TRADING_MODE", "paper").lower()
    starting_cash_usdt: float = _float("STARTING_CASH_USDT", 1000.0)
    order_size_usdt: float = _float("ORDER_SIZE_USDT", 10.0)
    fee_rate: float = _float("FEE_RATE", 0.001)
    # Dynamic schedule: VIP tier + optional BNB fee discount (~25% off typical table).
    fee_vip_level: int = int(os.getenv("FEE_VIP_LEVEL", "0"))
    fee_use_bnb_discount: bool = _bool("FEE_USE_BNB_DISCOUNT", False)
    # Paper stop path: multiply impact + optional fat-tail on stress sells.
    stop_stress_multiplier: float = _float("STOP_STRESS_MULTIPLIER", 2.5)
    stop_tail_bps: float = _float("STOP_TAIL_BPS", 8.0)
    max_order_size_usdt: float = _float("MAX_ORDER_SIZE_USDT", 25.0)
    max_daily_loss_usdt: float = _float("MAX_DAILY_LOSS_USDT", 5.0)
    max_consecutive_losses: int = int(os.getenv("MAX_CONSECUTIVE_LOSSES", "5"))
    max_spread_bps: float = _float("MAX_SPREAD_BPS", 20.0)
    max_data_age_seconds: float = _float("MAX_DATA_AGE_SECONDS", 8.0)
    imbalance_threshold: float = _float("IMBALANCE_THRESHOLD", 0.65)
    # Asymmetric R:R: default TP > SL so expectancy can stay positive at <50% win-rate.
    take_profit_pct: float = _float("TAKE_PROFIT_PCT", 1.20)
    stop_loss_pct: float = _float("STOP_LOSS_PCT", 0.35)
    min_reward_risk_ratio: float = _float("MIN_REWARD_RISK_RATIO", 2.0)
    trailing_stop_pct: float = _float("TRAILING_STOP_PCT", 0.25)
    signal_confirmations: int = int(os.getenv("SIGNAL_CONFIRMATIONS", "1"))
    entry_min_score: float = _float("ENTRY_MIN_SCORE", 0.32)
    target_price: float | None = _optional_float("TARGET_PRICE")
    simulated_slippage_bps: float = _float("SIMULATED_SLIPPAGE_BPS", 2.0)
    simulated_latency_ms: int = int(os.getenv("SIMULATED_LATENCY_MS", "50"))
    simulated_partial_fill_probability: float = _float("SIMULATED_PARTIAL_FILL_PROBABILITY", 0.0)
    simulation_seed: int = int(os.getenv("SIMULATION_SEED", "0"))
    store_path: str = os.getenv("PAPER_DB_PATH", "data/paper.sqlite3")
    market_history_path: str = os.getenv("MARKET_HISTORY_PATH", "data/market-history.jsonl.gz")
    log_level: str = os.getenv("LOG_LEVEL", "INFO").upper()
    binance_api_key: str = os.getenv("BINANCE_API_KEY", "")
    binance_api_secret: str = os.getenv("BINANCE_API_SECRET", "")
    binance_testnet: bool = _bool("BINANCE_TESTNET", True)
    live_confirm: str = os.getenv("LIVE_CONFIRM", "")
    autonomous_mode: bool = _bool("AUTONOMOUS_MODE", True)
    compound_fraction: float = _float("COMPOUND_FRACTION", 0.85)
    min_order_usdt: float = _float("MIN_ORDER_USDT", 5.0)
    impact_coefficient: float = _float("IMPACT_COEFFICIENT", 0.1)
    features_db_path: str = os.getenv("FEATURES_DB_PATH", "data/features.sqlite3")
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
        if not 0 <= self.fee_vip_level <= 9:
            raise ValueError("FEE_VIP_LEVEL must be in 0..9.")
        if self.stop_stress_multiplier < 1.0:
            raise ValueError("STOP_STRESS_MULTIPLIER must be >= 1.")
        if self.stop_tail_bps < 0:
            raise ValueError("STOP_TAIL_BPS cannot be negative.")
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
        if not 0 < self.compound_fraction <= 1:
            raise ValueError("COMPOUND_FRACTION must be in (0, 1].")
        if self.min_reward_risk_ratio < 1.0:
            raise ValueError("MIN_REWARD_RISK_RATIO must be >= 1.0.")
        if self.stop_loss_pct > 0 and (self.take_profit_pct / self.stop_loss_pct) + 1e-12 < self.min_reward_risk_ratio:
            raise ValueError(
                f"TAKE_PROFIT_PCT/STOP_LOSS_PCT must be >= MIN_REWARD_RISK_RATIO "
                f"({self.min_reward_risk_ratio}); got {self.take_profit_pct / self.stop_loss_pct:.3f}."
            )
        if self.min_order_usdt <= 0:
            raise ValueError("MIN_ORDER_USDT must be positive.")
        if self.trading_mode == "live":
            if not self.binance_api_key or not self.binance_api_secret:
                raise ValueError(
                    "TRADING_MODE=live requires BINANCE_API_KEY and BINANCE_API_SECRET."
                )
            if not self.binance_testnet:
                if self.live_confirm != "I_UNDERSTAND_REAL_MONEY":
                    raise ValueError(
                        "Mainnet live trading requires LIVE_CONFIRM=I_UNDERSTAND_REAL_MONEY "
                        "and BINANCE_TESTNET=false. Use testnet first."
                    )
        return self

    def watch_symbols(self) -> tuple[str, ...]:
        """Primary SYMBOL plus optional SYMBOLS list (deduped, lowercased)."""
        primary = self.symbol.lower()
        extra = [s.strip().lower() for s in (self.symbols_raw or "").split(",") if s.strip()]
        out: list[str] = []
        for s in [primary, *extra]:
            if s and s not in out:
                out.append(s)
        return tuple(out)

    def effective_fee_rate(self) -> float:
        """Taker rate after VIP + optional BNB discount (or FEE_RATE override)."""
        from app.fees import schedule_from_settings

        return schedule_from_settings(
            fee_rate=self.fee_rate,
            vip_level=self.fee_vip_level,
            use_bnb_discount=self.fee_use_bnb_discount,
        ).taker_rate()


settings = Settings().validate()
