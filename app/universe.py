"""Large-cap USDT universe screen → top-N depth candidates.

Scan ~30 majors via public 24h tickers (no API key). Rank by quote volume and
mild momentum; only the top DEPTH_TOP_N pairs get concurrent L2 streams.
Execution remains single-position via SymbolRouter.

Math stance: breadth for *selection*, not for simultaneous spam trades.
"""
from __future__ import annotations

import json
import logging
import urllib.request
from dataclasses import dataclass
from typing import Any

log = logging.getLogger(__name__)

DEFAULT_UNIVERSE: tuple[str, ...] = (
    "btcusdt", "ethusdt", "bnbusdt", "solusdt", "xrpusdt",
    "adausdt", "avaxusdt", "dogeusdt", "dotusdt", "linkusdt",
    "ltcusdt", "atomusdt", "nearusdt", "uniusdt", "aaveusdt",
    "aptusdt", "arusdt", "suiusdt", "pepeusdt", "shibusdt",
    "trxusdt", "tonusdt", "xlmusdt", "bchusdt", "filusdt",
    "icpusdt", "etcusdt", "renderusdt", "injusdt", "opousdt",
)

MAINNET_TICKER = "https://api.binance.com/api/v3/ticker/24hr"


@dataclass(slots=True)
class UniverseRow:
    symbol: str
    quote_volume: float
    last_price: float
    price_change_pct: float
    rank_score: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "quote_volume": round(self.quote_volume, 2),
            "last_price": self.last_price,
            "price_change_pct": round(self.price_change_pct, 3),
            "rank_score": round(self.rank_score, 4),
        }


def default_universe() -> list[str]:
    return list(DEFAULT_UNIVERSE)


def fetch_24h_tickers(symbols: list[str] | None = None, *, timeout: float = 12.0) -> list[dict[str, Any]]:
    url = MAINNET_TICKER
    req = urllib.request.Request(url, headers={"User-Agent": "NexoraQuant/universe"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode())
    if not isinstance(data, list):
        return []
    if symbols:
        want = {s.lower() for s in symbols}
        return [r for r in data if str(r.get("symbol", "")).lower() in want]
    return data


def screen_universe(
    *,
    candidates: list[str] | None = None,
    top_n: int = 5,
    min_quote_volume: float = 5_000_000.0,
) -> list[UniverseRow]:
    cands = [s.lower() for s in (candidates or default_universe())]
    try:
        raw = fetch_24h_tickers(cands)
    except Exception as exc:
        log.warning("universe ticker fetch failed: %s — fallback top static", exc)
        return [
            UniverseRow(s, 0.0, 0.0, 0.0, float(len(cands) - i))
            for i, s in enumerate(cands[: max(top_n, 1)])
        ]

    rows: list[UniverseRow] = []
    for r in raw:
        sym = str(r.get("symbol", "")).lower()
        if sym not in cands:
            continue
        try:
            qv = float(r.get("quoteVolume") or 0)
            last = float(r.get("lastPrice") or 0)
            chg = float(r.get("priceChangePercent") or 0)
        except (TypeError, ValueError):
            continue
        if qv < min_quote_volume and sym != "btcusdt":
            continue
        rank = qv * (1.0 + min(0.35, abs(chg) / 100.0))
        rows.append(UniverseRow(sym, qv, last, chg, rank))

    rows.sort(key=lambda x: x.rank_score, reverse=True)
    out = rows[: max(1, top_n)]
    symbols = [x.symbol for x in out]
    if "btcusdt" not in symbols:
        btc = next((x for x in rows if x.symbol == "btcusdt"), None)
        if btc is None:
            btc = UniverseRow("btcusdt", 0.0, 0.0, 0.0, 0.0)
        out = [btc] + [x for x in out if x.symbol != "btcusdt"]
        out = out[: max(top_n + 1, len(out))]
    return out


def depth_watch_from_screen(screened: list[UniverseRow], *, max_depth: int = 5) -> list[str]:
    seen: list[str] = []
    for row in screened:
        s = row.symbol.lower()
        if s not in seen:
            seen.append(s)
        if len(seen) >= max_depth:
            break
    if "btcusdt" not in seen:
        seen.append("btcusdt")
    return seen[: max(max_depth + 1, len(seen))]
