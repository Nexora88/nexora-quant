# OpticOdds and Polymarket moneyline research

This offline command compares two snapshots of the **same pregame NBA moneyline**. It does not download data, place orders, connect to a wallet, write to the Binance ledger, or change the trading engine. The comparison is conditional on the game being completed with an official winner, including overtime. It is not an arbitrage test, a forecast, or a recommendation.

## Run the synthetic example

From the repository root, with Python 3.11 or newer:

```sh
python scripts/compare_prediction_markets.py examples/nba_moneyline_snapshot.json --as-of 2026-01-01T00:00:00Z --cost-bps 100
```

The teams, books, and odds in the example are fictional. `--as-of` fixes the observation cutoff for reproducible replay. Omit it for a current snapshot; the command then uses current UTC. The report goes to standard output. Use `-` in place of the filename to read the bundle from standard input.

## Prepare a snapshot bundle

Use [the example bundle](../examples/nba_moneyline_snapshot.json) as the template. Collect the source responses close together and retain their original timestamps:

- **OpticOdds:** Resolve the fixture ID, then collect `/fixtures/odds` with that `fixture_id`, the selected sportsbooks, `market=moneyline`, `is_main=true`, and `odds_format=DECIMAL`. Put the object containing the provider's `data` array under `opticodds`. Each qualifying book must have exactly one main price for each fixture team in the default group.
- **Polymarket Gamma:** Fetch the exact moneyline via `/markets` using its slug. Put the snapshot envelope (`data` array, `retrieved_at`, `is_stale`) under `polymarket_market`. Verify `gameStartTime`, not the settlement deadline, and verify the question and resolution rules.
- **Polymarket CLOB:** Fetch `/book` once for each outcome's `clobTokenIds` entry. Put the two envelopes (`data` object, `retrieved_at`, `is_stale`) under `polymarket_books`. Keep token IDs as strings. When starting from raw provider data, add the original UTC retrieval timestamp and mark whether the quote came from stale-cache fallback; don't substitute the replay time for the retrieval time. The CLOB book timestamp itself is epoch milliseconds; OpticOdds quote timestamps are epoch seconds.
- **Match manifest:** Set the exact fixture ID and market slug, declare the decimal format, and map each Polymarket label to its exact OpticOdds team name. Copy the reviewed Polymarket `description` verbatim to `polymarket_resolution_rules`. In `settlement_review`, record the confirmation that the normal completed-game winner matches and note any differences for cancellations, abandonment, or postponements. A sportsbook void and a Polymarket 50/50 settlement are not equivalent. If the normal-result rules differ, do not create a match manifest.

Each response may also be wrapped in a `result` object. The OpticOdds response may additionally use its `status_code` and nested `data` envelope. The manifest is a human-reviewed mapping: the tool checks exact IDs, start time, two-outcome shape, condition/token identity, and pinned rules text. It does not infer team synonyms or verify sportsbook settlement terms automatically. Never commit captured commercial data without appropriate permission.

## Interpret the output

- **Sportsbook reference:** Convert each complete decimal price pair \(d_1, d_2\) to \(1/d_1, 1/d_2\); divide each by their sum to remove the quoted overround proportionally. Take the median no-vig probability across qualifying books. This is a market reference, not an independently calibrated estimate.
- **Polymarket quote:** Identify the highest bid and lowest ask without assuming input ordering. Consume visible asks from cheapest upward for the requested number of shares and use the volume-weighted ask price. No partial-depth comparison is reported. A snapshot is not a guaranteed execution price.
- **Difference:** `reference_minus_ask_pp` is the sportsbook reference minus the size-weighted Polymarket ask, in percentage points. `reference_minus_cost_adjusted_ask_pp` subtracts the ask plus `--cost-bps` on ask notional. It is `null` unless a cost assumption is explicitly supplied. This is a sensitivity input, not Polymarket's fee schedule or measured net P&L.
- **Quality gates:** Defaults are 10 shares, two complete sportsbooks, 120 seconds maximum observation age, 60 seconds maximum timestamp skew, and 0.10 maximum Polymarket spread. Both outcome books must pass. The command also rejects future timestamps, a missing or stale snapshot, crossed books, amounts below the exchange minimum, and insufficient depth. Review outcome `blockers` and `excluded_sportsbooks` for details before changing the thresholds.

Exit codes: `0` means comparable under the supplied assumptions, `2` means blocked with a JSON report and no price differences, and `1` means invalid input or an unreadable bundle.
