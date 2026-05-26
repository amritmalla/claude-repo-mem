from __future__ import annotations

from typing import Optional

from ..llm.base import LLMClient, LLMError
from ..units.model import Unit
from .prompts import CODE_SYSTEM, DOCS_SYSTEM, USER_TEMPLATE


async def summarize_unit(unit: Unit, llm: LLMClient) -> Optional[str]:
    if unit.layer == "memory":
        return None
    body = unit.metadata or unit.t1_header
    if not body or len(body) < 80:
        return None
    system = CODE_SYSTEM if unit.layer == "code" else DOCS_SYSTEM
    user = USER_TEMPLATE.format(kind=unit.kind, body=body[:8000])
    try:
        from ..observability.counters import get_counters
        try:
            get_counters().summarize_llm_calls += 1
        except Exception:
            pass
        return await llm.complete(system=system, user=user, max_tokens=200, temperature=0.0)
    except LLMError:
        return None
