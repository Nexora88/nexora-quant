"""Offline NBA moneyline research. No provider credentials or order interfaces."""
from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from math import isfinite
from statistics import median
from typing import Any


@dataclass(frozen=True)
class ComparisonPolicy:
    shares: float = 10
    min_books: int = 2
    max_age_seconds: float = 120
    max_skew_seconds: float = 60
    max_spread: float = 0.10
    cost_bps: float | None = None

    def __post_init__(self) -> None:
        if type(self.min_books) is not int or self.min_books < 1:
            raise ValueError("min_books must be a positive integer")
        for key in ("shares", "max_age_seconds", "max_skew_seconds", "max_spread"):
            value = getattr(self, key)
            if type(value) not in (int, float) or _number(value, key) <= 0:
                raise ValueError(f"{key} must be a positive finite number")
        if self.shares > 1e9 or self.max_spread > 1:
            raise ValueError("shares must be <= 1e9 and max_spread must be <= 1")
        if self.cost_bps is not None and (
            type(self.cost_bps) not in (int, float)
            or not 0 <= _number(self.cost_bps, "cost_bps") <= 10_000
        ):
            raise ValueError("cost_bps must be in [0, 10000]")


def _object(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be an object")
    return value


def _list(value: Any, field: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{field} must be an array")
    return value


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value


def _number(value: Any, field: str) -> float:
    try:
        if isinstance(value, bool):
            raise ValueError
        result = float(value)
        if isfinite(result):
            return result
    except (TypeError, ValueError, OverflowError):
        pass
    raise ValueError(f"{field} must be a finite number")


def _iso_time(value: Any, field: str) -> datetime:
    time = datetime.fromisoformat(_text(value, field))
    if time.tzinfo is None:
        raise ValueError(f"{field} must have a timezone")
    return time.astimezone(UTC)


def _epoch(value: Any, field: str, *, milliseconds: bool = False) -> datetime:
    stamp = _number(value, field)
    try:
        return datetime.fromtimestamp(stamp / 1000 if milliseconds else stamp, tz=UTC)
    except (OSError, OverflowError, ValueError) as exc:
        raise ValueError(f"{field} is outside the supported date range") from exc


def _source(value: Any, field: str) -> dict[str, Any]:
    wrapper = _object(value, field)
    return _object(wrapper.get("result", wrapper), field)


def _opticodds_snapshot(value: Any) -> dict[str, Any]:
    snapshot = _source(value, "opticodds")
    if "status_code" in snapshot:
        if snapshot["status_code"] != 200:
            raise ValueError("OpticOdds snapshot was not successful")
        if isinstance(snapshot.get("data"), dict):
            return snapshot["data"]
    return snapshot


def _matching_row(snapshot: dict[str, Any], key: str, value: str) -> dict[str, Any]:
    rows = [_object(row, key) for row in _list(snapshot.get("data"), "data")]
    matches = [row for row in rows if row.get(key) == value]
    if len(matches) != 1:
        raise ValueError(f"expected exactly one provider row for {key}={value}")
    return matches[0]


def _labels(value: Any, field: str) -> list[str]:
    if isinstance(value, str):
        value = json.loads(value)
    items = [_text(item, field) for item in _list(value, field)]
    if len(items) != 2 or len(set(items)) != 2:
        raise ValueError(f"{field} must contain two distinct values")
    return items


def _teams(fixture: dict[str, Any]) -> list[str]:
    teams = []
    for side in ("home", "away"):
        rows = _list(fixture.get(f"{side}_competitors"), f"{side}_competitors")
        if len(rows) != 1:
            raise ValueError(f"expected one {side} team")
        teams.append(_text(_object(rows[0], side).get("name"), f"{side} team"))
    if len(set(teams)) != 2:
        raise ValueError("fixture teams must be distinct")
    return teams


def _time_issue(time: datetime, as_of: datetime, max_age: float) -> str | None:
    age = (as_of - time).total_seconds()
    if age < 0:
        return "future_timestamp"
    if age > max_age:
        return "stale_timestamp"
    return None


def _book_quote(
    book: dict[str, Any], fetched: datetime, as_of: datetime, policy: ComparisonPolicy
) -> tuple[dict[str, Any], list[str], list[datetime]]:
    updated = _epoch(book.get("timestamp"), "order book timestamp", milliseconds=True)
    evidence = {"retrieved_at": fetched.isoformat(), "updated_at": updated.isoformat()}
    issues = []
    for name, time in (("retrieval", fetched), ("update", updated)):
        if issue := _time_issue(time, as_of, policy.max_age_seconds):
            issues.append(f"{name}_{issue}")
    if updated > fetched:
        issues.append("book_update_after_retrieval")

    levels = {}
    for side in ("bids", "asks"):
        prices = {}
        for row in _list(book.get(side), side):
            level = _object(row, side)
            price = _number(level.get("price"), f"{side} price")
            size = _number(level.get("size"), f"{side} size")
            if not 0 < price < 1 or size <= 0 or price in prices:
                raise ValueError(f"invalid or duplicate {side} level")
            prices[price] = size
        levels[side] = prices
    bids, asks = levels["bids"], levels["asks"]
    if not bids or not asks:
        return evidence, [*issues, "empty_book_side"], [updated, fetched]

    bid, ask = max(bids), min(asks)
    spread = ask - bid
    evidence.update(best_bid=bid, best_ask=ask, spread=spread)
    if spread < 0:
        issues.append("crossed_book")
    elif spread - policy.max_spread > 1e-12:
        issues.append("spread_above_limit")

    minimum_size = _number(book.get("min_order_size"), "minimum order size")
    if minimum_size <= 0:
        raise ValueError("minimum order size must be positive")
    if policy.shares < minimum_size:
        issues.append("size_below_market_minimum")

    remaining = policy.shares
    gross = 0.0
    for price, size in sorted(asks.items()):
        consumed = min(remaining, size)
        gross += consumed * price
        remaining -= consumed
        if remaining <= 0:
            break
    if remaining > max(1e-12, policy.shares * 1e-12):
        issues.append("insufficient_ask_depth")
    if not issues:
        evidence["ask_vwap"] = gross / policy.shares
    return evidence, issues, [updated, fetched]


def _sportsbook_reference(
    odds: list[Any], teams: list[str], as_of: datetime, book_times: list[datetime],
    policy: ComparisonPolicy,
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    by_book = defaultdict(list)
    for item in odds:
        row = _object(item, "OpticOdds price")
        if row.get("market_id") == "moneyline" and row.get("is_main") is True:
            name = _text(row.get("sportsbook"), "sportsbook")
            by_book[name.casefold()].append(row)

    included, rejected = [], {}
    for _, rows in sorted(by_book.items()):
        name = rows[0]["sportsbook"]
        by_team = {row["selection"]: row for row in rows if isinstance(row.get("selection"), str)}
        if (len(rows) != 2 or set(by_team) != set(teams)
                or any(row.get("grouping_key") != "default" or row.get("points") is not None
                       or row.get("selection_line") is not None for row in rows)):
            rejected[name] = "not_exactly_one_main_price_per_team"
            continue
        try:
            prices = [_number(by_team[team].get("price"), "decimal odds") for team in teams]
            times = [_epoch(by_team[team].get("timestamp"), "odds timestamp") for team in teams]
            ids = [_text(by_team[team].get("id"), "quote ID") for team in teams]
            if any(price <= 1 for price in prices) or len(set(ids)) != 2:
                raise ValueError
        except ValueError:
            rejected[name] = "invalid_odds_or_timestamp"
            continue
        issue = next(
            (problem for time in times
             if (problem := _time_issue(time, as_of, policy.max_age_seconds))),
            None,
        )
        if issue:
            rejected[name] = issue
            continue
        timeline = times + book_times
        if (max(timeline) - min(timeline)).total_seconds() > policy.max_skew_seconds:
            rejected[name] = "quote_skew_above_limit"
            continue
        raw = [1 / price for price in prices]
        total = sum(raw)
        included.append({
            "sportsbook": name,
            "overround_pct": (total - 1) * 100,
            "quotes": {
                team: {
                    "id": quote_id,
                    "decimal_odds": price,
                    "timestamp": time.isoformat(),
                    "no_vig_probability": implied / total,
                }
                for team, quote_id, price, time, implied in zip(teams, ids, prices, times, raw)
            },
        })
    return included, rejected


def compare_moneyline(
    bundle: dict[str, Any], *, as_of: datetime, policy: ComparisonPolicy | None = None
) -> dict[str, Any]:
    """Compare explicitly matched NBA snapshots or return a report with blockers."""
    policy = policy or ComparisonPolicy()
    if as_of.utcoffset() is None:
        raise ValueError("as_of must have a timezone")
    as_of = as_of.astimezone(UTC)
    mapping = _object(bundle.get("match"), "match")
    if mapping.get("opticodds_odds_format") != "DECIMAL":
        raise ValueError("OpticOdds snapshot must be requested with odds_format=DECIMAL")
    fixture_id = _text(mapping.get("opticodds_fixture_id"), "opticodds_fixture_id")
    slug = _text(mapping.get("polymarket_slug"), "polymarket_slug")
    review = _text(mapping.get("settlement_review"), "settlement_review")
    fixture = _matching_row(_opticodds_snapshot(bundle.get("opticodds")), "id", fixture_id)
    gamma = _source(bundle.get("polymarket_market"), "polymarket_market")
    market = _matching_row(gamma, "slug", slug)
    league = _object(fixture.get("league"), "fixture league")
    if league.get("id") != "nba" or market.get("sportsMarketType") != "moneyline":
        raise ValueError("only NBA two-team moneyline comparisons are supported")
    start = _iso_time(fixture.get("start_date"), "fixture start")
    if start != _iso_time(market.get("gameStartTime"), "market game start"):
        raise ValueError("provider game start times do not match")
    description = _text(market.get("description"), "market resolution rules")
    if description != mapping.get("polymarket_resolution_rules"):
        raise ValueError("Polymarket resolution rules differ from the reviewed rules")

    teams = _teams(fixture)
    labels = _labels(market.get("outcomes"), "outcomes")
    tokens = _labels(market.get("clobTokenIds"), "clobTokenIds")
    if not all(token.isascii() and token.isdecimal() for token in tokens):
        raise ValueError("CLOB token IDs must be decimal strings")
    aliases = _object(mapping.get("outcome_to_opticodds_team"), "outcome mapping")
    mapped_teams = [_text(team, "mapped team") for team in aliases.values()]
    if set(aliases) != set(labels) or sorted(mapped_teams) != sorted(teams):
        raise ValueError("outcome mapping must match both fixture teams exactly once")
    condition_id = _text(market.get("conditionId"), "conditionId")
    books = {}
    for item in _list(bundle.get("polymarket_books"), "polymarket_books"):
        snapshot = _source(item, "polymarket book")
        book = _object(snapshot.get("data"), "order book")
        token = _text(book.get("asset_id"), "order book asset_id")
        if token not in tokens or token in books or book.get("market") != condition_id:
            raise ValueError("order books must match the condition and unique outcome tokens")
        books[token] = (snapshot, book)

    blockers = []
    if fixture.get("status") != "unplayed" or fixture.get("is_live") is not False or as_of >= start:
        blockers.append("fixture_not_pregame")
    if any(market.get(key) is not expected for key, expected in (
        ("active", True), ("closed", False), ("acceptingOrders", True),
    )):
        blockers.append("polymarket_not_open")
    if gamma.get("is_stale") is not False:
        blockers.append("polymarket_market_not_confirmed_fresh")
    market_retrieved = _iso_time(gamma.get("retrieved_at"), "market retrieval")
    if issue := _time_issue(market_retrieved, as_of, policy.max_age_seconds):
        blockers.append(f"polymarket_market_{issue}")

    outcomes = {}
    book_times = []
    for label, token in zip(labels, tokens):
        quote, issues = {}, []
        if token not in books:
            issues.append("missing_order_book")
        else:
            snapshot, book = books[token]
            fetched = _iso_time(snapshot.get("retrieved_at"), "order book retrieval")
            quote, issues, times = _book_quote(book, fetched, as_of, policy)
            book_times.extend(times)
            if snapshot.get("is_stale") is not False:
                issues.append("order_book_not_confirmed_fresh")
        outcomes[label] = {
            "opticodds_team": aliases[label], "token_id": token,
            "order_book": quote, "blockers": issues,
            "sportsbook_no_vig_probability": None,
            "reference_minus_ask_pp": None,
            "reference_minus_cost_adjusted_ask_pp": None,
        }
    if any(row["blockers"] for row in outcomes.values()):
        blockers.append("polymarket_book_quality_failed")
    if book_times and (max(book_times) - min(book_times)).total_seconds() > policy.max_skew_seconds:
        blockers.append("polymarket_book_skew_above_limit")
    included, rejected = _sportsbook_reference(
        _list(fixture.get("odds"), "fixture odds"), teams, as_of, book_times, policy,
    )
    if len(included) < policy.min_books:
        blockers.append("insufficient_sportsbook_coverage")

    if not blockers:
        for row in outcomes.values():
            team = row["opticodds_team"]
            reference = median(book["quotes"][team]["no_vig_probability"] for book in included)
            ask = row["order_book"]["ask_vwap"]
            row["sportsbook_no_vig_probability"] = reference
            row["reference_minus_ask_pp"] = (reference - ask) * 100
            if policy.cost_bps is not None:
                row["reference_minus_cost_adjusted_ask_pp"] = (
                    reference - ask * (1 + policy.cost_bps / 10_000)
                ) * 100

    return {
        "schema_version": 1,
        "mode": "offline_research_only",
        "status": "blocked" if blockers else "comparable",
        "as_of": as_of.isoformat(),
        "fixture_start": start.isoformat(),
        "settlement_basis": "completed_game_including_overtime_only",
        "settlement_review": review,
        "opticodds_fixture_id": fixture_id,
        "polymarket_slug": slug,
        "polymarket_condition_id": condition_id,
        "polymarket_market_retrieved_at": market_retrieved.isoformat(),
        "polymarket_resolution_rules": description,
        "policy": asdict(policy),
        "blockers": blockers,
        "sportsbooks": included,
        "excluded_sportsbooks": rejected,
        "outcomes": outcomes,
    }
