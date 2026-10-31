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
        self.emergency: bool = False
        self.emergency_reason: str | None = None
        self.io_queue_stats: dict[str, Any] = {}
        self.learner_snapshot: dict[str, Any] = {}
        self.memory_lessons: list[dict[str, Any]] = []
        self.motor_report: dict[str, Any] | None = None
        self.score_history: deque = deque(maxlen=180)
        self.universe_board: list[dict[str, Any]] = []
        self.depth_watch: list[str] = []
        self.paused: bool = False
        self.peak_equity: float = 0.0
        self.live_log: deque = deque(maxlen=80)
        self.trade_symbol: str | None = None
        self.side_books: dict = {}
        self.router_board: list = []
        self.position_tp_pct: float | None = None
        self.position_sl_pct: float | None = None
        self.position_trail_pct: float | None = None
        self.dynamic_targets_note: str | None = None
        self.last_sizing_note: str | None = None
        self.wick_stop_state = None
        self.btc_block: bool = False
        self.btc_filter_snap: str | None = None
        self.last_flow: dict | None = None

    def update_book(self, book: BookTicker) -> None:
        self.latest_book = book
        self.last_message_at = book.received_at
        self.events_seen += 1
        mid = (book.bid + book.ask) / 2 if book.bid and book.ask else book.bid
        now = datetime.now(timezone.utc).isoformat()
        self.price_curve.append({"ts": now, "mid": mid, "bid": book.bid, "ask": book.ask})

    def data_age_seconds(self) -> float | None:
        if not self.last_message_at:
            return None
        ref = self.last_message_at
        if getattr(ref, "tzinfo", None) is None:
            ref = ref.replace(tzinfo=timezone.utc)
        return max(0.0, (datetime.now(timezone.utc) - ref).total_seconds())

    def record_analysis(self, analysis: Any) -> None:
        if hasattr(analysis, "__dataclass_fields__"):
            self.last_analysis = asdict(analysis)
        elif isinstance(analysis, dict):
            self.last_analysis = dict(analysis)
        else:
            self.last_analysis = {"score": getattr(analysis, "score", None)}
        sc = float(getattr(analysis, "score", 0) or 0)
        self.score_history.append({"ts": datetime.now(timezone.utc).isoformat(), "score": sc})

    def record_signal(self, signal: Any) -> None:
        if signal is None:
            self.last_signal = None
            return
        if hasattr(signal, "__dataclass_fields__"):
            self.last_signal = asdict(signal)
        elif isinstance(signal, dict):
            self.last_signal = dict(signal)

    def record_decision(self, decision: Any) -> None:
        if decision is None:
            return
        if hasattr(decision, "to_dict"):
            d = decision.to_dict()
        elif hasattr(decision, "__dataclass_fields__"):
            d = asdict(decision)
        elif isinstance(decision, dict):
            d = dict(decision)
        else:
            d = {"action": getattr(decision, "action", None)}
        self.last_decision = d
        self.decision_history.appendleft(d)

    def record_fill(self, trade: dict) -> None:
        self.recent_fills.appendleft(dict(trade))

    def sample_equity(self) -> None:
        if not self.executor:
            return
        mark = self.latest_book.bid if self.latest_book else None
        try:
            snap = self.executor.snapshot(mark)
            eq = float(snap.get("equity_usdt", 0))
            self.equity_curve.append({"ts": datetime.now(timezone.utc).isoformat(), "equity": eq})
            if eq > self.peak_equity:
                self.peak_equity = eq
        except Exception:
            pass

    def snapshot(self) -> dict[str, Any]:
        age = self.data_age_seconds()
        mark = self.latest_book.bid if self.latest_book else None
        portfolio = self.executor.snapshot(mark) if self.executor else {}
        dd_pct = 0.0
        if self.peak_equity > 0 and portfolio:
            eq = float(portfolio.get("equity_usdt", 0) or 0)
            dd_pct = max(0.0, (self.peak_equity - eq) / self.peak_equity * 100.0)
        daily_used_pct = 0.0
        if self.risk_manager and settings.max_daily_loss_usdt > 0:
            try:
                used = float(getattr(self.risk_manager, "realized_pnl_today", 0) or 0)
                if used < 0:
                    daily_used_pct = min(100.0, abs(used) / settings.max_daily_loss_usdt * 100.0)
            except Exception:
                pass
        market = None
        if self.latest_book is not None:
            b = self.latest_book
            market = {
                "symbol": b.symbol,
                "bid": b.bid,
                "bid_qty": b.bid_qty,
                "ask": b.ask,
                "ask_qty": b.ask_qty,
                "received_at": str(getattr(b, "received_at", "")),
            }
        return {
            "mode": settings.trading_mode,
            "symbol": (self.trade_symbol or settings.symbol),
            "target_price": settings.target_price,
            "connected": bool(age is not None and age <= settings.max_data_age_seconds),
            "reconnect_count": self.reconnect_count,
            "events_seen": self.events_seen,
            "data_age_seconds": age,
            "last_error": self.last_error,
            "kill_switch": bool(getattr(self.risk_manager, "kill_switch", False)) if self.risk_manager else False,
            "kill_switch_reason": getattr(self.risk_manager, "kill_switch_reason", None) if self.risk_manager else None,
            "realized_pnl_today": getattr(self.risk_manager, "realized_pnl_today", 0) if self.risk_manager else 0,
            "consecutive_losses": getattr(self.risk_manager, "consecutive_losses", 0) if self.risk_manager else 0,
            "market": market,
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
            "emergency": self.emergency,
            "emergency_reason": self.emergency_reason,
            "io_queue_stats": dict(self.io_queue_stats) if self.io_queue_stats else {},
            "learner_snapshot": dict(self.learner_snapshot) if self.learner_snapshot else {},
            "memory_lessons": list(self.memory_lessons)[:10],
            "motor_report": self.motor_report,
            "risk_limits": {
                "max_order_size_usdt": settings.max_order_size_usdt,
                "max_daily_loss_usdt": settings.max_daily_loss_usdt,
                "take_profit_pct": settings.take_profit_pct,
                "stop_loss_pct": settings.stop_loss_pct,
                "trailing_stop_pct": settings.trailing_stop_pct,
                "entry_min_score": settings.entry_min_score,
            },
            "score_history": list(self.score_history)[-120:],
            "universe_board": list(self.universe_board)[:12],
            "depth_watch": list(self.depth_watch)[:8],
            "paused": bool(self.paused),
            "peak_equity": self.peak_equity,
            "max_drawdown_pct": round(dd_pct, 3),
            "daily_loss_used_pct": round(daily_used_pct, 2),
            "live_log": list(self.live_log)[:40],
            "trade_symbol": self.trade_symbol,
            "last_sizing_note": self.last_sizing_note,
            "btc_block": bool(getattr(self, "btc_block", False)),
            "btc_filter_snap": getattr(self, "btc_filter_snap", None),
            "last_flow": getattr(self, "last_flow", None),
            "dynamic_targets_note": self.dynamic_targets_note,
            "position_tp_pct": self.position_tp_pct,
            "position_sl_pct": self.position_sl_pct,
            "telemetry": {
                "data_age_ms": round((age or 0) * 1000, 1) if age is not None else None,
                "events_seen": self.events_seen,
                "reconnect_count": self.reconnect_count,
                "heartbeat_ok": bool(age is not None and age <= settings.max_data_age_seconds),
            },
        }
