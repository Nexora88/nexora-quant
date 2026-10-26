# Roadmap

## Done (current main)

- L2 sync depth stream + paper/live execution paths
- AnalysisMotor ensemble, TrendFollower, OnlineLearner, TradeMemory
- Compound-oriented defaults (small TP, redeploy free cash)
- L2 event backtest CLI, impact model, AsyncIoQueue, feature store export hooks
- Dashboard API + JWT/token auth hooks
- Deploy templates (systemd / PM2) and go-live checklist

## Next (research)

- Stronger walk-forward on L2 fixtures; shadow-book auto parameter promote
- Optional Redis state for multi-process scale
- Columnar archive (Parquet / ClickHouse) export automation
- Richer dashboard (learner/memory/motor panels)

## Non-goals

- Guaranteed profit or HFT co-location competition
- Unattended mainnet without risk caps and operator monitoring
