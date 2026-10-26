"""Non-blocking SQLite write path via asyncio queue + background worker."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

log = logging.getLogger(__name__)


class AsyncIoQueue:
    """Fire-and-forget state/trade persistence; never block the depth loop.

    Under burst L2 load, queue depth is exposed for monitoring. When full,
    oldest state snapshots are dropped (trades prefer sync fallback).
    """

    def __init__(self, store: Any, *, maxsize: int = 2000) -> None:
        self.store = store
        self._maxsize = max(1, int(maxsize))
        self._q: asyncio.Queue | None = None
        self._task: asyncio.Task | None = None
        self._dropped = 0
        self._peak = 0
        self._writes = 0
        self._stopping = False

    def start(self) -> None:
        self._stopping = False
        self._q = asyncio.Queue(maxsize=self._maxsize)
        self._task = asyncio.create_task(self._worker(), name="nexora-io-queue")

    def stats(self) -> dict[str, Any]:
        depth = self._q.qsize() if self._q is not None else 0
        self._peak = max(self._peak, depth)
        return {
            "queue_depth": depth,
            "queue_peak": self._peak,
            "queue_max": self._maxsize,
            "dropped_state": self._dropped,
            "writes": self._writes,
        }

    def enqueue_state(self, key: str, state: dict[str, Any]) -> None:
        if self._q is None:
            self.store.save_state(key, state)
            return
        item = ("state", key, state)
        try:
            self._q.put_nowait(item)
        except asyncio.QueueFull:
            try:
                old = self._q.get_nowait()
                if old and old[0] == "state":
                    self._dropped += 1
                else:
                    self._q.put_nowait(old)
            except Exception:
                pass
            try:
                self._q.put_nowait(item)
            except asyncio.QueueFull:
                self._dropped += 1
                log.warning("IO queue full; state snapshot dropped key=%s", key)

    def enqueue_trade(self, trade: dict[str, Any], *, event_key: str) -> None:
        if self._q is None:
            self.store.append_trade(trade, event_key=event_key)
            return
        item = ("trade", event_key, trade)
        try:
            self._q.put_nowait(item)
        except asyncio.QueueFull:
            log.error("IO queue full on trade — sync fallback")
            self.store.append_trade(trade, event_key=event_key)
            self._writes += 1

    async def _worker(self) -> None:
        assert self._q is not None
        while not self._stopping:
            try:
                item = await asyncio.wait_for(self._q.get(), timeout=0.25)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            try:
                kind = item[0]
                if kind == "state":
                    _, key, payload = item
                    self.store.save_state(key, payload)
                elif kind == "trade":
                    _, event_key, trade = item
                    self.store.append_trade(trade, event_key=event_key)
                self._writes += 1
            except Exception:
                log.exception("IO queue write failed")
            finally:
                try:
                    self._q.task_done()
                except Exception:
                    pass

    async def stop(self) -> None:
        self._stopping = True
        if self._q is not None:
            while True:
                try:
                    item = self._q.get_nowait()
                except asyncio.QueueEmpty:
                    break
                try:
                    if item[0] == "state":
                        self.store.save_state(item[1], item[2])
                    elif item[0] == "trade":
                        self.store.append_trade(item[2], event_key=item[1])
                    self._writes += 1
                except Exception:
                    log.exception("IO drain failed")
                finally:
                    try:
                        self._q.task_done()
                    except Exception:
                        pass
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
