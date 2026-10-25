# Millisecond decision pipeline

| T (ms) | Stage | Disk I/O |
|--------|--------|----------|
| 0 | WebSocket depth → local L2 book | none |
| +0.5 | Micro-price, weighted OBI, OU, walls, whale (in-RAM) | none |
| +1.2 | Sustained + noise filter + feature votes | none |
| +1.8 | Edge quality, adverse selection, Kelly, risk gate | none |
| +2.5 | `asyncio.create_task` live order (fire-and-forget) | none on hot path |
| background | OCO TP/SL on exchange; IO queue → SQLite batch | async only |

Hot path never awaits Binance REST or SQLite. Protective exits are exchange-hosted (OCO).
