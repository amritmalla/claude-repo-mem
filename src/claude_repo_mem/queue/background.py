from __future__ import annotations

import queue
import sys
import threading
import time
from typing import Callable, Optional


_SENTINEL = object()


class BackgroundQueue:
    """Single-worker daemon-thread executor. Drop-in for fire-and-forget work."""

    def __init__(self) -> None:
        self._q: "queue.Queue[object]" = queue.Queue()
        self._worker: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._idle = threading.Event()
        self._idle.set()

    def start(self) -> None:
        if self._worker is not None:
            return
        self._stop.clear()
        self._worker = threading.Thread(target=self._run, daemon=True)
        self._worker.start()

    def submit(self, fn: Callable[[], None]) -> None:
        self._idle.clear()
        self._q.put(fn)

    def drain(self, timeout: float = 30.0) -> None:
        deadline = time.monotonic() + timeout
        while True:
            if self._q.empty() and self._idle.is_set():
                return
            if time.monotonic() > deadline:
                raise TimeoutError("BackgroundQueue.drain timeout")
            time.sleep(0.01)

    def stop(self) -> None:
        if self._worker is None:
            return
        self._stop.set()
        self._q.put(_SENTINEL)
        self._worker.join(timeout=2.0)
        self._worker = None

    def _run(self) -> None:
        while not self._stop.is_set():
            item = self._q.get()
            if item is _SENTINEL:
                self._idle.set()
                return
            try:
                item()
            except Exception as e:  # pragma: no cover
                print(f"[claude-repo-mem queue] job failed: {e}", file=sys.stderr)
            finally:
                if self._q.empty():
                    self._idle.set()
