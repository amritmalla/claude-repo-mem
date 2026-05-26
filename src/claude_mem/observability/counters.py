from __future__ import annotations

from dataclasses import dataclass, asdict


@dataclass
class Counters:
    recall_calls: int = 0
    trace_calls: int = 0
    expand_calls: int = 0
    remember_calls: int = 0
    forget_calls: int = 0
    plan_task_calls: int = 0
    summarize_llm_calls: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


_COUNTERS = Counters()


def get_counters() -> Counters:
    return _COUNTERS


def reset_counters() -> None:
    global _COUNTERS
    _COUNTERS = Counters()
