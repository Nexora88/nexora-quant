"""Engine globals, executor factory, fill helpers."""
from __future__ import annotations

import asyncio
import logging
import os

from app.config import settings
from app.paper import PaperExecutor
from app.risk import RiskManager
from app.simulation import ExecutionSimulator
from app.state import RuntimeState
from app.analytics.microstructure import OrnsteinUhlenbeckTracker
from app.analytics.regime import RegimeClassifier
from app.analytics.motor import AnalysisMotor
from app.dynamic_gate import DynamicKellyGate
from app.shadow import ShadowBook
from app.analytics.walls import WallTracker
from app.analytics.sustained import SustainedSignalGate
from app.intelligence.adverse import AdverseSelectionFilter
from app.intelligence.whale import WhaleTracker
from app.intelligence.noise import NoiseFilter
from app.intelligence.learner import OnlineLearner
from app.intelligence.trend_follow import TrendFollower
from app.intelligence.memory import TradeMemory
from app.intelligence.spoof import OrderPersistenceFilter
from app.intelligence.btc_filter import BtcTrendFilter
from app.symbol_router import SymbolRouter
from app.order_flow import OrderFlowAccumulator
from app.circuit_breaker import DrawdownCircuitBreaker
from app.atr_stops import AtrTracker
from app.portfolio_risk import PortfolioRiskGate
from app.strategy import PriceWindow
from app.live_hardening import harden_live_executor

harden_live_executor()

log = logging.getLogger(__name__)
state = RuntimeState()

risk = RiskManager(
    max_order_size_usdt=settings.max_order_size_usdt,
    max_daily_loss_usdt=settings.max_daily_loss_usdt,
    max_consecutive_losses=settings.max_consecutive_losses,
    max_spread_bps=settings.max_spread_bps,
    max_data_age_seconds=settings.max_data_age_seconds,
)
simulator = ExecutionSimulator(
    slippage_bps=settings.simulated_slippage_bps,
    latency_ms=settings.simulated_latency_ms,
    partial_fill_probability=settings.simulated_partial_fill_probability,
    seed=settings.simulation_seed,
    impact_coefficient=float(settings.impact_coefficient),
    stop_stress_multiplier=float(settings.stop_stress_multiplier),
    stop_tail_bps=float(settings.stop_tail_bps),
    symbol=settings.symbol,
)
state.risk_manager = risk
executor = None
price_window = PriceWindow(maxlen=180)
ou_tracker = OrnsteinUhlenbeckTracker(maxlen=300, z_entry=2.0)
regime_clf = RegimeClassifier()
kelly = DynamicKellyGate(
    max_fraction=0.25,
    min_order_usdt=float(settings.min_order_usdt),
    max_order_usdt=settings.max_order_size_usdt,
)
shadows = ShadowBook.default_book(settings.starting_cash_usdt)
wall_tracker = WallTracker(levels=15, multiple=3.0)
adverse_filter = AdverseSelectionFilter()
whale_tracker = WhaleTracker(multiple=4.0, persist_ticks=5)
spoof_filter = OrderPersistenceFilter(min_persist_ms=1500.0)
btc_filter = BtcTrendFilter(wick_jump_bps=35.0, cooldown_ticks=16)
order_flow = OrderFlowAccumulator(hold_seconds=1.8, min_samples=7, min_abs_pressure=0.14)
circuit_breaker = DrawdownCircuitBreaker(
    loss_streak=3,
    base_min_score=float(settings.entry_min_score),
    elevated_min_score=min(0.95, float(settings.entry_min_score) + 0.20),
    sleep_seconds=900.0,
)
atr_tracker = AtrTracker(period=28)
portfolio_risk = PortfolioRiskGate(
    max_total_risk_pct=float(settings.risk_per_trade_pct),
    max_concurrent=int(settings.max_concurrent_positions),
)
symbol_router = SymbolRouter(
    min_score=float(settings.entry_min_score),
    max_spoof=0.60,
)
noise_filter = NoiseFilter(window=12, min_stability=0.55)
trend_follower = TrendFollower(fast=12, slow=48)
motor = AnalysisMotor(window=120)
learner = OnlineLearner(
    window=40,
    base_entry_min=float(settings.entry_min_score),
    base_compound=float(settings.compound_fraction),
    frozen=os.getenv("LEARNER_FROZEN", "").strip().lower() in {"1", "true", "yes", "on"},
    min_trades_before_adapt=int(os.getenv("LEARNER_MIN_TRADES", "25")),
)
memory = TradeMemory(capacity=200)
sustained = SustainedSignalGate(
    min_confirmations=(
        max(1, settings.signal_confirmations)
        if getattr(settings, "autonomous_mode", True)
        else max(settings.signal_confirmations, 4)
    ),
    min_hold_seconds=(1.5 if getattr(settings, "autonomous_mode", True) else 2.0),
    min_score=float(settings.entry_min_score),
)


def _build_executor():
    if settings.trading_mode == "live":
        from app.binance_rest import BinanceRestClient
        from app.live import LiveExecutor
        try:
            from app.live_hardening import install_maker_entry
            install_maker_entry()
        except Exception:
            log.exception("install_maker_entry failed")

        client = BinanceRestClient(
            api_key=settings.binance_api_key,
            api_secret=settings.binance_api_secret,
            testnet=settings.binance_testnet,
        )
        return LiveExecutor(client, settings.symbol, fee_rate=settings.effective_fee_rate())
    return PaperExecutor(settings.starting_cash_usdt, settings.effective_fee_rate())


async def _paper_fill(side: str, price: float, quantity: float, *, book_levels=None, stress: bool = False):
    return await asyncio.to_thread(
        simulator.fills,
        side=side,
        reference_price=price,
        quantity=quantity,
        book_levels=book_levels,
        stress=stress,
    )


def _event_key(key: str, trade: dict) -> str:
    return f"{key}:{trade.get('timestamp')}:{trade.get('side')}:{trade.get('price')}"
