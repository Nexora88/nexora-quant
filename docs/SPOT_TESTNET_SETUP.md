# Spot Testnet setup (owner actions)

This is the only credential setup required before the signed exchange lifecycle test. Use **Binance Spot Testnet credentials only**. Never use a Mainnet API key, even temporarily.

## 1. Create an isolated Spot Testnet account

1. Open the official Binance Spot Testnet portal: https://testnet.binance.vision/
2. Sign in using the supported testnet authentication flow and create/use the dedicated test account.
3. Generate a new API key in the Spot Testnet portal. Do not copy credentials from your normal Binance account.
4. Keep the API secret private. It is shown only at creation time; store it in a password manager until added to GitHub.
5. Fund the test account with at least **20 USDT plus a small fee buffer** using Testnet faucet/test assets.
6. Before the test, make sure the account has **no tradable BTC**, no open BTCUSDT orders, and no open order lists. Do not use this account for manual trading or another bot.

Use the least privilege available for Spot trading. Withdrawals must remain disabled. If the portal offers IP restrictions, use the restrictions it supports; do not enable withdrawal permission to make the test work.

## 2. Add the two GitHub Actions secrets

In https://github.com/Nexora88/nexora-quant:

1. Open **Settings → Secrets and variables → Actions**.
2. Under **Repository secrets**, choose **New repository secret**.
3. Add these exact names, each with its matching Spot Testnet value:

| Secret name | Value |
|---|---|
| `BINANCE_SPOT_TESTNET_API_KEY` | Spot Testnet API key |
| `BINANCE_SPOT_TESTNET_API_SECRET` | Spot Testnet API secret |

Do not add `BINANCE_API_KEY`, `BINANCE_API_SECRET`, or any Mainnet credentials as repository secrets for this workflow. Do not paste either value into ChatGPT, issues, PRs, commits, logs, or screenshots. GitHub masks configured secrets in normal Actions logs, but never deliberately print them.

## 3. Run the signed Testnet lifecycle

After the provenance-hardening PR is merged:

1. Open the repository **Actions** tab.
2. Select **Binance Spot Testnet E2E**.
3. Choose **Run workflow** and keep the branch set to **main**.
4. Wait for the complete run. A skipped test, missing secrets, or failed assertion is not a pass.
5. Open the successful run and download the `spot-testnet-e2e-results` artifact. Preserve the JUnit report and note the run's full commit SHA.

The lifecycle test uses a fixed **20 USDT BTCUSDT market buy**, verifies accounting, creates protective OCO orders, restarts the executor from its SQLite journal, reconciles and cancels the OCO, closes the remaining position, checks actual commissions, and confirms no open orders or residual tradable BTC remain.

The report is useful only together with its GitHub artifact attestation. The local go-live gate verifies the exact report with GitHub CLI and the source SHA from the successful workflow run.

## 4. What happens after Testnet

The Testnet workflow does not complete the 168-hour Paper Trading requirement. Keep the Paper process running continuously, retain its SQLite ledger and logs, and collect at least 50 fee-complete closed trades with positive fee-net expectancy. Then run the repository's overnight paper check and generate the chronological, manifest-verified OOS evidence described in [GO_LIVE_CHECKLIST.md](GO_LIVE_CHECKLIST.md).

Passing Testnet or Paper checks does not enable Mainnet. Mainnet remains disabled and requires a separate, explicit human decision after independent security and account review.
