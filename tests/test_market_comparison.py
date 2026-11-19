from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest

from app.market_comparison import ComparisonPolicy, compare_moneyline

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples/nba_moneyline_snapshot.json"
AS_OF = datetime.fromisoformat("2026-01-01T00:00:00Z")


@pytest.fixture
def bundle():
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))


def test_no_vig_median_depth_and_optional_cost(bundle):
    # Check full connector wrappers, array/string variants and unsorted price levels.
    market = bundle["polymarket_market"]["data"][0]
    market["outcomes"] = json.loads(market["outcomes"])
    bundle["opticodds"] = {"result": {"status_code": 200, "data": bundle["opticodds"]}}
    bundle["polymarket_market"] = {"result": bundle["polymarket_market"]}
    report = compare_moneyline(bundle, as_of=AS_OF, policy=ComparisonPolicy(cost_bps=100))
    assert report["status"] == "comparable"
    assert report["settlement_basis"] == "completed_game_including_overtime_only"
    assert len(report["sportsbooks"]) == 2
    comets = report["outcomes"]["Comets"]
    meteors = report["outcomes"]["Meteors"]
    p = (2.10 / (1.80 + 2.10) + 2.05 / (1.85 + 2.05)) / 2
    vwap = (4 * 0.51 + 6 * 0.53) / 10
    assert comets["token_id"] == "1234567890123456789012345678901234567890"
    assert comets["order_book"]["best_bid"] == 0.5
    assert comets["order_book"]["best_ask"] == 0.51
    assert comets["order_book"]["ask_vwap"] == pytest.approx(vwap)
    assert comets["sportsbook_no_vig_probability"] == pytest.approx(p)
    assert meteors["sportsbook_no_vig_probability"] == pytest.approx(1 - p)
    assert comets["reference_minus_ask_pp"] == pytest.approx((p - vwap) * 100)
    assert comets["reference_minus_cost_adjusted_ask_pp"] == pytest.approx((p - vwap * 1.01) * 100)
    assert report["sportsbooks"][0]["overround_pct"] == pytest.approx((1 / 1.8 + 1 / 2.1 - 1) * 100)


def _set(bundle, path, value):
    node = bundle
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value


@pytest.mark.parametrize(("path", "value", "message"), [
    (("polymarket_market", "data", 0, "gameStartTime"), "2026-01-01T02:00:00Z", "do not match"),
    (("polymarket_market", "data", 0, "description"), "Changed settlement", "reviewed rules"),
    (("polymarket_market", "data", 0, "sportsMarketType"), "spreads", "only NBA"),
    (("polymarket_market", "data", 0, "clobTokenIds"), [2301, "3"], "non-empty string"),
    (("match", "outcome_to_opticodds_team", "Meteors"), "Example Comets", "exactly once"),
    (("match", "opticodds_odds_format"), "AMERICAN", "odds_format=DECIMAL"),
    (("opticodds", "status_code"), 429, "snapshot was not successful"),
    (("polymarket_books", 0, "data", "market"), "0xother", "condition"),
    (("polymarket_books", 0, "data", "asset_id"), "not-a-token", "unique outcome tokens"),
    (("polymarket_books", 0, "data", "asks", 0, "size"), "nan", "finite number"),
])
def test_wrong_identity_or_malformed_data_is_an_error(bundle, path, value, message):
    _set(bundle, path, value)
    with pytest.raises(ValueError, match=message):
        compare_moneyline(bundle, as_of=AS_OF)


@pytest.mark.parametrize(("path", "value", "reason"), [
    (("polymarket_books", 0, "is_stale"), True, "order_book_not_confirmed_fresh"),
    (("polymarket_books", 0, "data", "timestamp"), "1767225195000", "update_stale_timestamp"),
    (("polymarket_books", 0, "data", "timestamp"), "1767225596500", "book_update_after_retrieval"),
    (("polymarket_books", 0, "data", "asks"), [], "empty_book_side"),
    (("polymarket_books", 0, "data", "asks"), [{"price": "0.49", "size": "30"}], "crossed_book"),
    (("polymarket_books", 0, "data", "asks"), [{"price": "0.63", "size": "30"}], "spread_above_limit"),
    (("polymarket_books", 0, "data", "asks"), [{"price": "0.51", "size": "4"}], "insufficient_ask_depth"),
    (("polymarket_books", 0, "data", "min_order_size"), "20", "size_below_market_minimum"),
])
def test_poor_book_blocks_both_outcomes(bundle, path, value, reason):
    _set(bundle, path, value)
    report = compare_moneyline(bundle, as_of=AS_OF)
    assert report["status"] == "blocked"
    assert "polymarket_book_quality_failed" in report["blockers"]
    assert reason in report["outcomes"]["Comets"]["blockers"]
    assert all(row["reference_minus_ask_pp"] is None for row in report["outcomes"].values())


def test_missing_book_and_closed_or_started_market(bundle):
    bundle["polymarket_books"].pop()
    bundle["polymarket_market"]["data"][0]["acceptingOrders"] = False
    bundle["opticodds"]["data"][0]["status"] = "live"
    report = compare_moneyline(bundle, as_of=AS_OF)
    assert report["status"] == "blocked"
    assert {"fixture_not_pregame", "polymarket_not_open"} <= set(report["blockers"])
    assert report["outcomes"]["Meteors"]["blockers"] == ["missing_order_book"]


def test_no_vig_requires_complete_fresh_synchronous_pairs(bundle):
    rows = bundle["opticodds"]["data"][0]["odds"]
    rows[0]["timestamp"] = 1767225300
    rows[2]["timestamp"] = 1767225500
    report = compare_moneyline(bundle, as_of=AS_OF)
    assert report["status"] == "blocked"
    assert report["excluded_sportsbooks"] == {
        "Example Book A": "stale_timestamp", "Example Book B": "quote_skew_above_limit",
    }
    assert "insufficient_sportsbook_coverage" in report["blockers"]
    rows.pop(0)
    rows[1]["timestamp"] = 1767225592
    rows.append({**rows[0], "sportsbook": "example book a"})
    report = compare_moneyline(bundle, as_of=AS_OF, policy=ComparisonPolicy(min_books=1))
    assert report["status"] == "comparable"
    assert report["excluded_sportsbooks"] == {"Example Book A": "not_exactly_one_main_price_per_team"}
    assert report["outcomes"]["Comets"]["reference_minus_cost_adjusted_ask_pp"] is None


def test_future_observations_are_not_accepted_for_replay(bundle):
    report = compare_moneyline(bundle, as_of=datetime.fromisoformat("2025-12-31T23:59:44Z"))
    assert report["status"] == "blocked"
    assert "polymarket_market_future_timestamp" in report["blockers"]
    assert "retrieval_future_timestamp" in report["outcomes"]["Comets"]["blockers"]
    assert set(report["excluded_sportsbooks"].values()) == {"future_timestamp"}


@pytest.mark.parametrize("kwargs", [
    {"shares": float("inf")}, {"min_books": True}, {"cost_bps": -1}, {"max_spread": 1.1},
])
def test_invalid_policy_is_rejected(kwargs):
    with pytest.raises(ValueError):
        ComparisonPolicy(**kwargs)


def test_cli_comparable_blocked_and_invalid(bundle):
    command = [sys.executable, str(ROOT / "scripts/compare_prediction_markets.py")]
    good = subprocess.run([*command, str(EXAMPLE), "--as-of", AS_OF.isoformat()],
                          capture_output=True, text=True, check=True)
    assert json.loads(good.stdout)["status"] == "comparable"
    stale = subprocess.run([*command, "-", "--as-of", "2026-01-01T00:10:00Z"],
                           input=json.dumps(bundle), capture_output=True, text=True)
    assert stale.returncode == 2
    assert json.loads(stale.stdout)["status"] == "blocked"
    bad = subprocess.run([*command, "-", "--as-of", "2026-01-01T00:00:00"],
                         input=json.dumps(bundle), capture_output=True, text=True)
    assert bad.returncode == 1
    assert "as_of must have a timezone" in bad.stderr
    assert not bad.stdout
