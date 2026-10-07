"""Strict action protocol:  {"thought": "...", "action": {"tool": "name", "args": {...}}}  or  {"final_answer": "..."}"""

import json
import re
from dataclasses import dataclass


class ParseError(ValueError):
    pass


@dataclass
class Decision:
    thought: str = ""
    tool: str | None = None
    args: dict | None = None
    final: str | None = None
    raw: str = ""


PROTOCOL_HELP = (
    'Reply with exactly ONE JSON object, either an action: {"thought": "why", "action": {"tool": "<tool name>", "args": {...}}} '
    'or, when the task is complete, {"final_answer": "<answer for the user>"}.'
)


def extract_json_object(raw: str) -> dict:
    """Tolerant: strips ``` fences and any prose around the outermost {...}."""
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.I)
    i, j = t.find("{"), t.rfind("}")
    if i == -1 or j <= i:
        raise ParseError("no JSON object found")
    try:
        obj = json.loads(t[i : j + 1])
    except json.JSONDecodeError as exc:
        raise ParseError(f"invalid JSON ({exc.msg} at position {exc.pos})") from exc
    if not isinstance(obj, dict):
        raise ParseError("top-level value must be a JSON object")
    return obj


def parse_decision(raw: str) -> Decision:
    obj = extract_json_object(raw)
    thought = obj.get("thought", "")
    if not isinstance(thought, str):
        raise ParseError("'thought' must be a string")
    if "final_answer" in obj:
        ans = obj["final_answer"]
        if not isinstance(ans, str) or not ans.strip():
            raise ParseError("'final_answer' must be a non-empty string")
        return Decision(thought=thought, final=ans.strip(), raw=raw)
    action = obj.get("action")
    if not isinstance(action, dict):
        raise ParseError("missing 'action' object (or 'final_answer')")
    tool, args = action.get("tool"), action.get("args", {})
    if not isinstance(tool, str) or not tool:
        raise ParseError("'action.tool' must be a tool name string")
    if not isinstance(args, dict):
        raise ParseError("'action.args' must be a JSON object")
    return Decision(thought=thought, tool=tool, args=args, raw=raw)


def parse_plan(raw: str) -> list[str]:
    obj = extract_json_object(raw)
    plan = obj.get("plan")
    if not isinstance(plan, list) or not all(isinstance(x, str) for x in plan) or not plan:
        raise ParseError("'plan' must be a non-empty list of strings")
    return [x.strip() for x in plan[:8]]
