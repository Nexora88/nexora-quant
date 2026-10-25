"""In-memory runtime state with equity curve and analysis for the dashboard."""
from collections import deque
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any

from app.events import BookTicker, TradeTick
from app.config import settings


class RuntimeState:
    def __init__(self) -> None:
        self.latest_book: BookTicker | None = None
        self.trades: deque[TradeTick] = deque(maxlen=1000)
        self.last_message_at = None
        self.reconnect_count = 0
        self.events_seen = 0
        self.last_error = None
        self.executor = None
        self.risk_manager = None
        self.last_analysis: dict[str, Any] | None = None
        self.last_signal: dict[str, Any] | None = None
        self.peak_price: float = 0.0
        self.equity_curve: deque[dict[str, Any]] = deque(maxlen=500)
        self.price_curve: deque[dict[str, Any]] = deque(maxlen=500)
        self.recent_fills: deque[dict[str, Any]] = deque(maxlen=50)
        self.shadow_leaderboard: list[dict[str, Any]] = []
        self.last_decision: dict[str, Any] | None = None
        self.decision_history: deque = deque(maxlen=50)

    def update_book(self, book: BookTicker) -> None:
        self.latest_book = book
        self.last_message_at = book.received_at
        self.events_seen += 1
        mid = (book.bid + book.ask) / 2 if book.bid and book.ask else book.bid
        now = datetime.now(timezone.utc).isoformat()
        if mid and mid > 0:
            self.price_curve.append({"t": now, "mid": mid, "bid": book.bid, "ask": book.ask})
            if self.executor and getattr(self.executor, "base_quantity", 0) > 0:
                self.peak_price = max(self.peak_price, book.bid)

    def record_analysis(self, analysis: Any) -> None:
        self.last_analysis = {
            "mid": analysis.mid,
            "spread_bps": analysis.spread_bps,
            "imbalance": analysis.imbalance,
            "momentum_bps": analysis.momentum_bps,
            "trend": analysis.trend,
            "distance_to_target_pct": analysis.distance_to_target_pct,
            "target_bias": analysis.target_bias,
            "score": analysis.score,
            "reasons": list(analysis.reasons),
            "created_at": analysis.created_at.isoformat(),
            "weighted_obi": getattr(analysis, "weighted_obi", None),
            "micro_price": getattr(analysis, "micro_price", None),
            "micro_premium_bps": getattr(analysis, "micro_premium_bps", 0.0),
            "ou_zscore": getattr(analysis, "ou_zscore", None),
            "mean_reversion_signal": getattr(analysis, "mean_reversion_signal", "none"),
            "regime": getattr(analysis, "regime", "unknown"),
        }

    def record_decision(self, decision: Any) -> None:
        d = decision.to_dict() if hasattr(decision, "to_dict") else dict(decision)
        self.last_decision = d
        self.decision_history.append(d)

    def record_signal(self, signal: Any | None) -> None:
        if signal is None:
            return
        self.last_signal = {
            "action": signal.action,
            "reason": signal.reason,
            "strength": signal.strength,
            "created_at": signal.created_at.isoformat(),
        }

    def record_fill(self, trade: dict[str, Any]) -> None:
        self.recent_fills.appendleft(dict(trade))
        if trade.get("side") == "buy":
            entry = float(trade.get("price") or 0)
            self.peak_price = entry
        mark = self.latest_book.bid if self.latest_book else None
        if self.executor:
            snap = self.executor.snapshot(mark)
            self.equity_curve.append(
                {
                    "t": datetime.now(timezone.utc).isoformat(),
                    "equity": snap.get("equity_usdt"),
                    "realized": snap.get("realized_pnl_usdt"),
                    "unrealized": snap.get("unrealized_pnl_usdt"),
                }
            )

    def sample_equity(self) -> None:
        mark = self.latest_book.bid if self.latest_book else None
        if not self.executor:
            return
        snap = self.executor.snapshot(mark)
        self.equity_curve.append(
            {
                "t": datetime.now(timezone.utc).isoformat(),
                "equity": snap.get("equity_usdt"),
                "realized": snap.get("realized_pnl_usdt"),
                "unrealized": snap.get("unrealized_pnl_usdt"),
            }
        )

    def add_trade(self, trade: TradeTick) -> None:
        self.trades.append(trade)
        self.last_message_at = trade.received_at
        self.events_seen += 1

    def data_age_seconds(self) -> float | None:
        if self.last_message_at is None:
            return None
        return max(0.0, (datetime.now(timezone.utc) - self.last_message_at).total_seconds())

    def snapshot(self) -> dict:
        book = self.latest_book
        age = self.data_age_seconds()
        risk = self.risk_manager
        portfolio = (
            self.executor.snapshot(book.bid if book else None) if self.executor else None
        )
        return {
            "mode": settings.trading_mode,
            "symbol": settings.symbol.upper(),
            "target_price": settings.target_price,
            "connected": age is not None and age <= settings.max_data_age_seconds,
            "reconnect_count": self.reconnect_count,
            "events_seen": self.events_seen,
            "data_age_seconds": age,
            "last_error": self.last_error,
            "kill_switch": bool(risk and risk.kill_switch),
            "kill_switch_reason": risk.kill_switch_reason if risk else None,
            "realized_pnl_today": risk.realized_pnl_today if risk else 0,
            "consecutive_losses": risk.consecutive_losses if risk else 0,
            "market": asdict(book) if book else None,
            "portfolio": portfolio,
            "analysis": self.last_analysis,
            "last_signal": self.last_signal,
            "peak_price": self.peak_price,
            "equity_curve": list(self.equity_curve)[-120:],
            "price_curve": list(self.price_curve)[-120:],
            "recent_fills": list(self.recent_fills)[:20],
            "shadow_leaderboard": list(self.shadow_leaderboard)[:5],
            "last_decision": self.last_decision,
            "decision_history": list(self.decision_history)[:15],
            "risk_limits": {
                "max_order_size_usdt": settings.max_order_size_usdt,
                "max_daily_loss_usdt": settings.max_daily_loss_usdt,
                "take_profit_pct": settings.take_profit_pct,
                "stop_loss_pct": settings.stop_loss_pct,
                "trailing_stop_pct": settings.trailing_stop_pct,
                "entry_min_score": settings.entry_min_score,
            },
        }
