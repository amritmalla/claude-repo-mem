from __future__ import annotations

import time
from typing import Callable, Iterable, Optional


class PathDebouncer:
    """Collect path strings; fire `on_flush(paths)` after a quiet period.

    Pure data; does not own a timer thread. Caller polls `is_due()` and calls
    `flush()` (or just calls `flush()` directly to force a fire).
    """

    def __init__(
        self,
        *,
        on_flush: Callable[[Iterable[str]], None],
        quiet_ms: int = 750,
        now_fn: Callable[[], float] = time.monotonic,
    ) -> None:
        self._on_flush = on_flush
        self._quiet_s = quiet_ms / 1000.0
        self._now = now_fn
        self._paths: set[str] = set()
        self._last_add_at: Optional[float] = None

    def add(self, path: str) -> None:
        self._paths.add(path)
        self._last_add_at = self._now()

    def is_due(self) -> bool:
        if not self._paths or self._last_add_at is None:
            return False
        return (self._now() - self._last_add_at) >= self._quiet_s

    def flush(self) -> None:
        if not self._paths:
            return
        paths = self._paths
        self._paths = set()
        self._last_add_at = None
        self._on_flush(paths)
