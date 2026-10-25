"""Non-blocking SQLite write queue for the hot path."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Literal

from app.storage import PaperStore

log = logging.getLogger(__name__)

JobKind = Literal["state", "trade", "shutdown"]


@dataclass(slots=True)
class IoJob:
    kind: JobKind
    key: str = ""
    payload: dict[str, Any] | None = None
    event_key: str = ""


class AsyncIoQueue:
    def __init__(self, store: PaperStore, *, maxsize: int = 2048) -> None:
        self.store = store
        self._q: asyncio.Queue[IoJob] = asyncio.Queue(maxsize=maxsize)
        self._task: asyncio.Task | None = None
        self._stopped = False

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._stopped = False
            self._task = asyncio.create_task(self._worker(), name="nexora-io-queue")

    async def stop(self) -> None:
        self._stopped = True
        try:
            self._q.put_nowait(IoJob(kind="shutdown"))
        except asyncio.QueueFull:
            pass
        if self._task:
            try:
                await asyncio.wait_for(self._task, timeout=5.0)
            except (asyncio.TimeoutError, Exception):
                self._task.cancel()
        try:
            self.store.flush()
        except Exception:
            log.exception("final flush failed")

    def enqueue_state(self, key: str, state: dict[str, Any]) -> None:
        try:
            self._q.put_nowait(IoJob(kind="state", key=key, payload=state))
        except asyncio.QueueFull:
            log.warning("IO queue full; dropping state write")

    def enqueue_trade(self, trade: dict[str, Any], *, event_key: str) -> None:
        try:
            self._q.put_nowait(IoJob(kind="trade", key="", payload=trade, event_key=event_key))
        except asyncio.QueueFull:
            log.warning("IO queue full; dropping trade write")

    async def _worker(self) -> None:
        while True:
            job = await self._q.get()
            try:
                if job.kind == "shutdown":
                    while not self._q.empty():
                        j = self._q.get_nowait()
                        self._apply(j)
                    self.store.flush()
                    return
                self._apply(job)
                for _ in range(16):
                    try:
                        j = self._q.get_nowait()
                    except asyncio.QueueEmpty:
                        break
                    if j.kind == "shutdown":
                        self.store.flush()
                        return
                    self._apply(j)
            except Exception:
                log.exception("IO worker job failed kind=%s", job.kind)
            finally:
                self._q.task_done()

    def _apply(self, job: IoJob) -> None:
        if job.kind == "state" and job.payload is not None:
            self.store.save_state(job.key, job.payload)
        elif job.kind == "trade" and job.payload is not None:
            self.store.append_trade(job.payload, event_key=job.event_key)
