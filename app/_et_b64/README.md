# engine_tick body parts

`body.z0` + `body.z1` are zlib+base64 halves of the full `handle_tick` module.
`app/engine_tick.py` decodes them on import.

Includes:
- fee-aware edge gate + paper/live cost symmetry
- expectancy gate (halt entries if fee-net expectancy < 0 after N closes)
- single-source hourly anti-churn via `state.record_fill`
- maker entry path, circuit breaker, ATR targets, time_stop, peak trail

Do not hand-edit these halves. Rebuild from source then re-split if changing tick logic.
