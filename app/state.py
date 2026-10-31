"""Runtime state for the trading engine and dashboard."""
from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.events import BookTicker


@dataclass
class RuntimeState:
    def __init__(self) -> None:
        self.mode: str = "paper"
        self.symbol: str = "btcusdt"
        self.trade_symbol: str | None = None
        self.connected: bool = False
        self.reconnect_count: int = 0
        self.events_seen: int = 0
        self.last_error: str | None = None
        self.kill_switch: bool = False
        self.kill_switch_reason: str | None = None
        self.paused: bool = False
        self.emergency: bool = False
        self.executor: Any = None
        self.risk_manager: Any = None
        self.latest_book: BookTicker | None = None
        self.latest_analysis: Any = None
        self.latest_signal: Any = None
        self.latest_decision: Any = None
        self.peak_price: float = 0.0
        self.position_tp_pct: float | None = None
        self.position_sl_pct: float | None = None
        self.position_trail_pct: float | None = None
        self.dynamic_targets_note: str | None = None
        self.last_sizing_note: str | None = None
        self.wick_stop_state = None
        self.btc_block: bool = False
        self.btc_filter_snap: str | None = None
        self.last_flow: dict | None = None
        self.learner_snapshot: dict | None = None
        self.shadow_leaderboard: list = field(default_factory=list) if False else []
        self.side_books: dict = {}
        self.router_board: list = []
        self.price_curve: deque = deque(maxlen=300)
        self.equity_curve: deque = deque(maxlen=300)
        self.recent_fills: deque = deque(maxlen=40)
        self._book_ts: float = 0.0

    def update_book(self, book: BookTicker) -> None:
        self.latest_book = book
        self.connected = True
        self.events_seen += 1
        self._book_ts = datetime.now(timezone.utc).timestamp()
        mid = (book.bid + book.ask) / 2.0 if book.ask >= book.bid else book.bid
        self.price_curve.append({"t": self._book_ts, "mid": mid})

    def data_age_seconds(self) -> float:
        if not self._book_ts:
            return 999.0
        return max(0.0, datetime.now(timezone.utc).timestamp() - self._book_ts)

    def record_analysis(self, analysis: Any) -> None:
        self.latest_analysis = analysis

    def record_signal(self, signal: Any) -> None:
        self.latest_signal = signal

    def record_decision(self, decision: Any) -> None:
        self.latest_decision = decision

    def record_fill(self, trade: dict) -> None:
        self.recent_fills.appendleft(dict(trade))

    def sample_equity(self) -> None:
        if not self.executor:
            return
        mark = self.latest_book.bid if self.latest_book else None
        try:
            snap = self.executor.snapshot(mark)
            eq = float(snap.get("equity_usdt", 0))
            self.equity_curve.append({"t": datetime.now(timezone.utc).timestamp(), "equity": eq})
        except Exception:
            pass

    def snapshot(self) -> dict[str, Any]:
        mark = self.latest_book.bid if self.latest_book else None
        portfolio = self.executor.snapshot(mark) if self.executor else {}
        analysis = None
        if self.latest_analysis is not None:
            a = self.latest_analysis
            analysis = {
                "mid": getattr(a, "mid", None),
                "spread_bps": getattr(a, "spread_bps", None),
                "imbalance": getattr(a, "imbalance", None),
                "momentum_bps": getattr(a, "momentum_bps", None),
                "trend": getattr(a, "trend", None),
                "score": getattr(a, "score", None),
                "reasons": list(getattr(a, "reasons", []) or []),
                "regime": getattr(a, "regime", None),
                "weighted_obi": getattr(a, "weighted_obi", None),
                "micro_premium_bps": getattr(a, "micro_premium_bps", None),
            }
        decision = None
        if self.latest_decision is not None:
            d = self.latest_decision
            decision = d.to_dict() if hasattr(d, "to_dict") else asdict(d) if hasattr(d, "__dataclass_fields__") else {}
        market = None
        if self.latest_book is not None:
            b = self.latest_book
            market = {
                "symbol": b.symbol,
                "bid": b.bid,
                "bid_qty": b.bid_qty,
                "ask": b.ask,
                "ask_qty": b.ask_qty,
                "received_at": getattr(b, "received_at", None),
            }
        from app.config import settings as _s

        return {
            "mode": self.mode or _s.trading_mode,
            "symbol": (self.trade_symbol or self.symbol or _s.symbol),
            "connected": self.connected and self.data_age_seconds() <= 8.0,
            "reconnect_count": self.reconnect_count,
            "events_seen": self.events_seen,
            "data_age_seconds": self.data_age_seconds(),
            "last_error": self.last_error,
            "kill_switch": self.kill_switch,
            "kill_switch_reason": self.kill_switch_reason,
            "paused": self.paused,
            "market": market,
            "portfolio": portfolio,
            "analysis": analysis,
            "last_signal": asdict(self.latest_signal) if self.latest_signal and hasattr(self.latest_signal, "__dataclass_fields__") else None,
            "last_decision": decision,
            "price_curve": list(self.price_curve),
            "equity_curve": list(self.equity_curve),
            "recent_fills": list(self.recent_fills),
            "last_sizing_note": self.last_sizing_note,
            "btc_block": bool(getattr(self, "btc_block", False)),
            "btc_filter_snap": getattr(self, "btc_filter_snap", None),
            "last_flow": getattr(self, "last_flow", None),
            "learner_snapshot": self.learner_snapshot,
            "risk_limits": {
                "max_order_size_usdt": _s.max_order_size_usdt,
                "max_daily_loss_usdt": _s.max_daily_loss_usdt,
                "take_profit_pct": _s.take_profit_pct,
                "stop_loss_pct": _s.stop_loss_pct,
                "trailing_stop_pct": _s.trailing_stop_pct,
                "entry_min_score": _s.entry_min_score,
            },
        }
