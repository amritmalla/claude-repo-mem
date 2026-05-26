from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
from typing import Optional

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from ..config import Settings
from ..embeddings.base import Embedder
from ..indexer.incremental import incremental_reindex
from ..indexer.walker import SKIP_DIRS, SUPPORTED_EXTS
from ..queue.background import BackgroundQueue
from .debounce import PathDebouncer


class FileWatcher:
    def __init__(
        self,
        settings: Settings,
        *,
        embedder: Optional[Embedder] = None,
        quiet_ms: int = 750,
        queue: Optional[BackgroundQueue] = None,
        llm=None,
    ) -> None:
        self.settings = settings
        self.embedder = embedder
        self.llm = llm
        self._lock = threading.Lock()
        self._debouncer = PathDebouncer(
            on_flush=self._on_flush, quiet_ms=quiet_ms,
        )
        self._observer = Observer()
        self._stop = threading.Event()
        self._tick_thread: Optional[threading.Thread] = None
        self._handler = _ChangeHandler(self._on_change)
        self._quiet_ms = quiet_ms
        self._queue = queue or BackgroundQueue()
        self._owns_queue = queue is None

    def start(self) -> None:
        if self._owns_queue:
            self._queue.start()
        self._observer.schedule(
            self._handler, str(self.settings.repo_root), recursive=True
        )
        self._observer.start()
        self._tick_thread = threading.Thread(target=self._tick_loop, daemon=True)
        self._tick_thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._observer.stop()
        self._observer.join(timeout=2.0)
        if self._tick_thread:
            self._tick_thread.join(timeout=2.0)
        if self._owns_queue:
            self._queue.stop()

    def _on_change(self, path: Path) -> None:
        if not self._is_indexable(path):
            return
        with self._lock:
            self._debouncer.add(str(path))

    def _is_indexable(self, path: Path) -> bool:
        if path.suffix.lower() not in SUPPORTED_EXTS:
            return False
        parts = path.parts
        if ".claude-mem" in parts:
            try:
                i = list(parts).index(".claude-mem")
                if i + 1 >= len(parts) or parts[i + 1] != "memory":
                    return False
            except ValueError:
                pass
        if set(parts) & (SKIP_DIRS - {".claude-mem"}):
            return False
        return True

    def _on_flush(self, paths) -> None:
        paths_list = [Path(p) for p in paths]
        settings = self.settings
        embedder = self.embedder
        llm = self.llm

        def job():
            try:
                incremental_reindex(settings, paths_list, embedder=embedder)
            except Exception as e:  # pragma: no cover — defensive
                print(f"[claude-mem watcher] reindex failed: {e}", file=sys.stderr)
            if llm is not None:
                try:
                    from ..summarizer.backfill import backfill_summaries_sync
                    backfill_summaries_sync(settings, llm=llm, limit=50)
                except Exception as e:  # pragma: no cover — defensive
                    print(f"[claude-mem watcher] backfill failed: {e}", file=sys.stderr)

        self._queue.submit(job)

    def _tick_loop(self) -> None:
        interval = min(0.1, self._quiet_ms / 1000.0 / 4)
        while not self._stop.is_set():
            with self._lock:
                if self._debouncer.is_due():
                    self._debouncer.flush()
            time.sleep(interval)


class _ChangeHandler(FileSystemEventHandler):
    def __init__(self, on_change):
        super().__init__()
        self._on_change = on_change

    def on_modified(self, event):
        if not event.is_directory:
            self._on_change(Path(event.src_path))

    def on_created(self, event):
        if not event.is_directory:
            self._on_change(Path(event.src_path))

    def on_deleted(self, event):
        if not event.is_directory:
            self._on_change(Path(event.src_path))

    def on_moved(self, event):
        if not event.is_directory:
            self._on_change(Path(event.src_path))
            if event.dest_path:
                self._on_change(Path(event.dest_path))
