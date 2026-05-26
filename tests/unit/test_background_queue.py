import threading
import time
from claude_mem.queue.background import BackgroundQueue


def test_submit_runs_job():
    q = BackgroundQueue()
    q.start()
    try:
        fired = threading.Event()
        q.submit(fired.set)
        assert fired.wait(timeout=2.0)
    finally:
        q.stop()


def test_submit_runs_jobs_in_order_single_worker():
    q = BackgroundQueue()
    q.start()
    try:
        out: list[int] = []
        for i in range(5):
            q.submit(lambda i=i: out.append(i))
        q.drain(timeout=5.0)
        assert out == [0, 1, 2, 3, 4]
    finally:
        q.stop()


def _raise():
    raise RuntimeError("boom")


def test_exception_does_not_kill_worker():
    q = BackgroundQueue()
    q.start()
    try:
        q.submit(_raise)
        fired = threading.Event()
        q.submit(fired.set)
        assert fired.wait(timeout=2.0)
    finally:
        q.stop()


def test_drain_waits_for_idle():
    q = BackgroundQueue()
    q.start()
    try:
        seen: list[str] = []

        def slow():
            time.sleep(0.05)
            seen.append("a")

        q.submit(slow)
        q.drain(timeout=2.0)
        assert seen == ["a"]
    finally:
        q.stop()
