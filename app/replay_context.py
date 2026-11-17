"""Event-time market context shared by deterministic multi-symbol replay.

This reconstructs the live engine's fail-closed gates from recorded public
trades, closed candles and synchronized depth snapshots. It is not an exchange
queue simulator and cannot identify spoofing with certainty.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Sequence

from app.events import TradeTick
from app.intelligence.spoof import OrderPersistenceFilter
from app.market_indicators import Candle, IndicatorSnapshot, MarketIndicatorTracker
from app.order_flow import FlowPressure, OrderFlowAccumulator
from app.trade_flow import TradeFlowTracker


@dataclass(frozen=True, slots=True)
class ReplayDepthContext:
    spoof_score: float
    stable_bid_usdt: float
    stable_ask_usdt: float
    book_flow: FlowPressure


class ReplayMarketContext:
    """Per-symbol indicator, aggressor-flow, persistent-book and macro state."""

    def __init__(self, symbols: Sequence[str]) -> None:
        names = {str(s).lower() for s in symbols}
        names.update(("btcusdt", "ethusdt"))
        self.indicators = {s: MarketIndicatorTracker() for s in names}
        self.trades = {
            s: TradeFlowTracker(window_seconds=10.0, min_trades=20, max_age_seconds=2.5)
            for s in names
        }
        self.books = {
            s: OrderFlowAccumulator(hold_seconds=1.8, min_samples=7, min_abs_pressure=0.14)
            for s in names
        }
        self.spoof = {s: OrderPersistenceFilter(min_persist_ms=1500.0) for s in names}
        self.last_depth: dict[str, ReplayDepthContext] = {}
        self._indicator_cache: dict[str, tuple[tuple[int | None, int | None], IndicatorSnapshot]] = {}

    def _ensure(self, symbol: str) -> str:
        sym = symbol.lower()
        if sym not in self.indicators:
            self.indicators[sym] = MarketIndicatorTracker()
            self.trades[sym] = TradeFlowTracker(
                window_seconds=10.0, min_trades=20, max_age_seconds=2.5,
            )
            self.books[sym] = OrderFlowAccumulator(
                hold_seconds=1.8, min_samples=7, min_abs_pressure=0.14,
            )
            self.spoof[sym] = OrderPersistenceFilter(min_persist_ms=1500.0)
        return sym

    def update_trade(self, payload: dict, timestamp: float) -> None:
        symbol = self._ensure(str(payload.get("symbol") or ""))
        self.trades[symbol].update(TradeTick(
            symbol=symbol,
            price=float(payload["price"]),
            quantity=float(payload["quantity"]),
            buyer_is_maker=bool(payload["buyer_is_maker"]),
            received_at=datetime.fromtimestamp(timestamp, timezone.utc),
        ), now=timestamp)

    def update_kline(self, payload: dict, timestamp: float) -> None:
        if payload.get("closed") is not True:
            return
        symbol = self._ensure(str(payload.get("symbol") or ""))
        self.indicators[symbol].update(Candle(
            symbol=symbol,
            interval=str(payload["interval"]),
            open_time=int(payload["open_time"]),
            open=float(payload["open"]),
            high=float(payload["high"]),
            low=float(payload["low"]),
            close=float(payload["close"]),
            volume=float(payload.get("volume") or 0.0),
            closed=True,
            received_at=timestamp,
        ))
        self._indicator_cache.pop(symbol, None)

    def indicator_snapshot(self, symbol: str, timestamp: float) -> IndicatorSnapshot:
        sym = self._ensure(symbol)
        tracker = self.indicators[sym]
        rows_1m = tracker._candles["1m"]
        rows_5m = tracker._candles["5m"]
        last_1m = rows_1m[-1].open_time if rows_1m else None
        last_5m = rows_5m[-1].open_time if rows_5m else None
        key = (last_1m, last_5m)
        cached = self._indicator_cache.get(sym)
        if cached is not None and cached[0] == key:
            snapshot = cached[1]
            age_1m = max(0.0, timestamp - last_1m / 1000.0) if last_1m is not None else None
            age_5m = max(0.0, timestamp - last_5m / 1000.0) if last_5m is not None else None
            ready = (
                len(rows_1m) >= 200 and len(rows_5m) >= 50
                and age_1m is not None and age_1m <= 120.0
                and age_5m is not None and age_5m <= 600.0
            )
            return replace(snapshot, ready=ready, age_seconds=age_1m)
        snapshot = tracker.snapshot(now=timestamp)
        self._indicator_cache[sym] = (key, snapshot)
        return snapshot

    def update_depth(
        self, payload: dict, timestamp: float, *,
        imbalance: float, micro_premium_bps: float,
    ) -> ReplayDepthContext:
        symbol = self._ensure(str(payload.get("symbol") or ""))
        raw_bids = payload.get("bids")
        raw_asks = payload.get("asks")
        raw_bids = raw_bids if isinstance(raw_bids, list) else []
        raw_asks = raw_asks if isinstance(raw_asks, list) else []
        bids = [(float(x[0]), float(x[1])) for x in raw_bids[:20] if isinstance(x, (list, tuple)) and len(x) >= 2]
        asks = [(float(x[0]), float(x[1])) for x in raw_asks[:20] if isinstance(x, (list, tuple)) and len(x) >= 2]
        report = self.spoof[symbol].update(
            bids, asks, now_ms=timestamp * 1000.0,
        )
        book = self.books[symbol].update(
            imbalance=imbalance,
            micro_premium_bps=micro_premium_bps,
            timestamp=timestamp,
        )
        result = ReplayDepthContext(
            spoof_score=report.spoof_score,
            stable_bid_usdt=report.stable_bid_usdt,
            stable_ask_usdt=report.stable_ask_usdt,
            book_flow=book,
        )
        self.last_depth[symbol] = result
        return result

    def entry_blockers(
        self, symbol: str, timestamp: float, depth: ReplayDepthContext,
    ) -> tuple[list[str], dict]:
        """Return the same hard contextual blockers used by live entry flow."""
        sym = self._ensure(symbol)
        blockers: list[str] = []
        indicator = self.indicator_snapshot(sym, timestamp)
        if depth.spoof_score >= 0.70:
            blockers.append(f"spoof_risk:{depth.spoof_score:.2f}")
        if not indicator.ready:
            blockers.append("indicator_history_warming_or_stale")
        elif indicator.trend_bias == "bearish" or indicator.momentum_bias == "bearish":
            blockers.append("indicator_bearish_context")
        if indicator.atr14_pct is not None and indicator.atr14_pct >= 0.80:
            blockers.append(f"atr_volatility_stress:{indicator.atr14_pct:.3f}%")
        if indicator.volume_ratio is not None and indicator.volume_ratio < 0.20:
            blockers.append(f"volume_too_thin:{indicator.volume_ratio:.2f}x")
        if (
            indicator.volume_ratio is not None and indicator.volume_ratio >= 4.0
            and indicator.atr14_pct is not None and indicator.atr14_pct >= 0.60
        ):
            blockers.append(
                f"volume_volatility_spike:{indicator.volume_ratio:.2f}x/{indicator.atr14_pct:.3f}%"
            )

        macro: dict = {}
        if sym != "btcusdt":
            btc = self.indicators["btcusdt"]
            btc_indicator = self.indicator_snapshot("btcusdt", timestamp)
            if not btc_indicator.ready:
                blockers.append("btc_context_warming_or_stale")
            asset_return = self.indicators[sym].return_bps(bars=5)
            btc_return = btc.return_bps(bars=5)
            correlation = self.indicators[sym].correlation_with(btc, periods=30)
            eth_return = self.indicators["ethusdt"].return_bps(bars=5)
            macro = {
                "btc_return_5m_bps": btc_return,
                "asset_return_5m_bps": asset_return,
                "relative_strength_5m_bps": (
                    asset_return - btc_return
                    if asset_return is not None and btc_return is not None else None
                ),
                "btc_correlation_30m": correlation,
                "eth_return_5m_bps": eth_return,
                "ready": btc_return is not None and asset_return is not None,
            }
            if not macro["ready"]:
                blockers.append("macro_returns_warming")
            elif btc_return <= -25.0 and (correlation is None or correlation >= 0.45):
                blockers.append("btc_macro_downtrend")
            elif asset_return - btc_return < -20.0:
                blockers.append("relative_strength_vs_btc_weak")
            elif sym != "ethusdt" and btc_return < 0 and eth_return is not None and eth_return <= -30.0:
                blockers.append("major_market_breadth_weak")
        else:
            macro = {
                "btc_return_5m_bps": self.indicators[sym].return_bps(bars=5),
                "btc_correlation_30m": 1.0,
                "ready": True,
            }

        trade = self.trades[sym].snapshot(now=timestamp)
        if not trade.ready:
            blockers.append("trade_flow_not_ready")
        book = depth.book_flow
        fused = 0.55 * book.pressure + 0.45 * trade.delta_ratio
        if not book.ready or not trade.ready or abs(fused) < 0.10:
            blockers.append("book_trade_flow_not_confirmed")
        details = {
            "indicator": indicator,
            "macro": macro,
            "trade_flow": trade,
            "book_flow": book,
            "fused_flow": fused,
        }
        return blockers, details
