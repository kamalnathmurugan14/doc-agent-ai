"""LangGraph state. Everything must be JSON-serialisable because it is checkpointed to SQLite."""

from typing import Any, TypedDict


class GState(TypedDict, total=False):
    messages: list[dict]
    step_count: int
    counts: dict[str, int]  # loop-detection counters
    pending: dict[str, Any] | None  # the action currently being processed
    decision: dict[str, Any] | None  # the human's decision (set after resume)
    done: bool
