# Run only the opt-in Binance Spot Testnet E2E test.
# Credentials are read from the ignored local .env.testnet file and never printed.
$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$envPath = Join-Path $repoRoot ".env.testnet"
if (-not (Test-Path $envPath)) {
    throw "Missing .env.testnet. Copy .env.testnet.example to .env.testnet and add dedicated Spot Testnet API keys."
}
$values = @{}
foreach ($line in Get-Content $envPath) {
    $trimmed = $line.Trim()
    if (-not $trimmed -or $trimmed.StartsWith("#")) { continue }
    if ($trimmed -match "^([A-Za-z_][A-Za-z0-9_]*)=(.*)$") {
        $name = $Matches[1]
        $value = $Matches[2].Trim().Trim('"').Trim("'")
        $values[$name] = $value
    }
}
if ($values["BINANCE_TESTNET"] -ne "true") { throw "Refusing to run: BINANCE_TESTNET must be exactly true." }
if ($values["TRADING_MODE"] -ne "paper") { throw "Refusing to run: E2E harness must keep app TRADING_MODE=paper." }
if (-not $values["BINANCE_API_KEY"] -or -not $values["BINANCE_API_SECRET"]) { throw "Dedicated Spot Testnet API key/secret are missing from .env.testnet." }
$amount = 0.0
if (-not [double]::TryParse($values["NEXORA_TESTNET_ORDER_QUOTE_USDT"], [ref]$amount) -or $amount -lt 10 -or $amount -gt 25) { throw "NEXORA_TESTNET_ORDER_QUOTE_USDT must be between 10 and 25." }
$symbol = $values["NEXORA_TESTNET_SYMBOL"]
if (-not $symbol -or $symbol -notmatch "^[A-Za-z0-9]{5,20}$") { throw "NEXORA_TESTNET_SYMBOL is invalid." }
foreach ($name in $values.Keys) { Set-Item -Path "Env:$name" -Value $values[$name] }
$env:NEXORA_RUN_SPOT_TESTNET_E2E = "1"
Set-Location $repoRoot
& .\.venv\Scripts\python.exe -m pytest -q tests\test_spot_testnet_e2e.py -rs
exit $LASTEXITCODE
