"""Engine globals, executor factory, fill helpers."""
from __future__ import annotations

import asyncio
import logging

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
    impact_coefficient=getattr(settings, "impact_coefficient", 0.1),
    stop_stress_multiplier=float(getattr(settings, "stop_stress_multiplier", 2.5)),
    stop_tail_bps=float(getattr(settings, "stop_tail_bps", 8.0)),
    symbol=settings.symbol,
)
state.risk_manager = risk
executor = None
price_window = PriceWindow(maxlen=180)
ou_tracker = OrnsteinUhlenbeckTracker(maxlen=300, z_entry=2.0)
regime_clf = RegimeClassifier()
kelly = DynamicKellyGate(
    max_fraction=0.25,
    min_order_usdt=float(getattr(settings, "min_order_usdt", 5.0)),
    max_order_usdt=settings.max_order_size_usdt,
)
shadows = ShadowBook.default_book(settings.starting_cash_usdt)
wall_tracker = WallTracker(levels=15, multiple=3.0)
adverse_filter = AdverseSelectionFilter()
whale_tracker = WhaleTracker(multiple=4.0, persist_ticks=5)
spoof_filter = OrderPersistenceFilter(min_persist_ms=1500.0)
btc_filter = BtcTrendFilter(wick_jump_bps=35.0, cooldown_ticks=16)
order_flow = OrderFlowAccumulator(hold_seconds=2.0, min_samples=10, min_abs_pressure=0.18)
circuit_breaker = DrawdownCircuitBreaker(
    loss_streak=3,
    base_min_score=float(getattr(settings, "entry_min_score", 0.55) or 0.55),
    elevated_min_score=0.75,
    sleep_seconds=900.0,
)
atr_tracker = AtrTracker(period=28)
portfolio_risk = PortfolioRiskGate(max_total_risk_pct=0.35, max_concurrent=1)
symbol_router = SymbolRouter(
    min_score=float(getattr(settings, "entry_min_score", 0.55) or 0.55),
    max_spoof=0.55,
)
noise_filter = NoiseFilter(window=12, min_stability=0.55)
trend_follower = TrendFollower(fast=12, slow=48)
motor = AnalysisMotor(window=120)
learner = OnlineLearner(
    window=40,
    base_entry_min=min(getattr(settings, "entry_min_score", 0.32), 0.32),
    base_compound=float(getattr(settings, "compound_fraction", 0.85)),
)
memory = TradeMemory(capacity=200)
sustained = SustainedSignalGate(
    min_confirmations=(1 if getattr(settings, "autonomous_mode", True) else max(settings.signal_confirmations, 4)),
    min_hold_seconds=(0.3 if getattr(settings, "autonomous_mode", True) else 2.0),
    min_score=(min(settings.entry_min_score, 0.35) if getattr(settings, "autonomous_mode", True) else settings.entry_min_score),
)


def _build_executor():
    if settings.trading_mode == "live":
        from app.binance_rest import BinanceRestClient
        from app.live import LiveExecutor

        client = BinanceRestClient(
            api_key=settings.binance_api_key,
            api_secret=settings.binance_api_secret,
            testnet=settings.binance_testnet,
        )
        eff_fee = settings.effective_fee_rate()
        live = LiveExecutor(client, symbol=settings.symbol, fee_rate=eff_fee)
        live.sync_balances()
        return live
    return PaperExecutor(settings.starting_cash_usdt, settings.effective_fee_rate())


def _event_key(key: str, trade: dict) -> str:
    oid = trade.get("exchange_order_id") or trade.get("timestamp")
    return f"{key}:{oid}:{trade['side']}:{trade['quantity']:.12f}"


async def _paper_fill(
    side: str,
    price: float,
    quantity: float,
    *,
    book_levels=None,
    stress: bool = False,
) -> object:
    fill = simulator.fills(
        side=side,
        reference_price=price,
        quantity=quantity,
        book_levels=book_levels,
        stress=stress,
    )
    if fill.latency_ms:
        await asyncio.sleep(fill.latency_ms / 1000)
    return fill
