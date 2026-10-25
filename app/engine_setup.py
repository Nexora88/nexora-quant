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
from app.dynamic_gate import DynamicKellyGate
from app.shadow import ShadowBook
from app.analytics.walls import WallTracker
from app.analytics.sustained import SustainedSignalGate
from app.intelligence.adverse import AdverseSelectionFilter
from app.intelligence.whale import WhaleTracker
from app.intelligence.noise import NoiseFilter
from app.strategy import PriceWindow
from app.microstructure_costs import ObservedExecutionCostModel

log = logging.getLogger(__name__)
state = RuntimeState()
execution_costs = ObservedExecutionCostModel(min_samples=30, horizon_ms=1000, window_size=500)

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
)
state.risk_manager = risk
executor = None
price_window = PriceWindow(maxlen=180)
ou_tracker = OrnsteinUhlenbeckTracker(maxlen=300, z_entry=2.0)
regime_clf = RegimeClassifier()
kelly = DynamicKellyGate(
    max_fraction=0.25,
    min_order_usdt=5.0,
    max_order_usdt=settings.max_order_size_usdt,
)
shadows = ShadowBook.default_book(settings.starting_cash_usdt)
wall_tracker = WallTracker(levels=15, multiple=3.0)
adverse_filter = AdverseSelectionFilter()
whale_tracker = WhaleTracker(multiple=4.0, persist_ticks=5)
noise_filter = NoiseFilter(window=12, min_stability=0.55)
sustained = SustainedSignalGate(
    min_confirmations=max(settings.signal_confirmations, 4),
    min_hold_seconds=2.0,
    min_score=settings.entry_min_score,
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
        live = LiveExecutor(
            client,
            symbol=settings.symbol,
            fee_rate=settings.fee_rate,
        )
        live.sync_balances()
        return live
    return PaperExecutor(settings.starting_cash_usdt, settings.fee_rate)


def _event_key(key: str, trade: dict) -> str:
    oid = trade.get("exchange_order_id") or trade.get("timestamp")
    return f"{key}:{oid}:{trade['side']}:{trade['quantity']:.12f}"


async def _paper_fill(
    side: str, price: float, quantity: float, *, book_levels=None
) -> object:
    fill = simulator.fill(
        side=side, reference_price=price, quantity=quantity, book_levels=book_levels
    )
    if fill.latency_ms:
        await asyncio.sleep(fill.latency_ms / 1000)
    return fill
