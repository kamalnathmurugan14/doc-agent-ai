"""Builds the system prompt (tool list generated from the registry) and the planning prompt."""

from jinja2 import DictLoader, Environment
from jinja2.sandbox import SandboxedEnvironment

from app.agent.parser import PROTOCOL_HELP
from app.config import PROMPTS_DIR
from app.tools.registry import Registry


def args_signature(schema: dict) -> str:
    """{'path': 'string, required - File path...', ...} as a compact one-liner."""
    props, req = schema.get("properties", {}), set(schema.get("required", []))
    parts = []
    for name, p in props.items():
        t = p.get("type") or "|".join(x.get("type", "any") for x in p.get("anyOf", [])) or "any"
        if t == "array":
            t = "list"
        parts.append(
            f"{name} ({t}{', required' if name in req else ''}){' - ' + p['description'] if p.get('description') else ''}"
        )
    return "; ".join(parts) if parts else "none"


def _env() -> Environment:
    return SandboxedEnvironment(
        loader=DictLoader({"tool_line": (PROMPTS_DIR / "tool_descriptions.md").read_text(encoding="utf-8")}),
        autoescape=False,
    )


def build_system_prompt(
    registry: Registry, max_steps: int, scope: str | None, dry_run: bool, memory: list[dict]
) -> str:
    tools = [
        {
            "name": t.name,
            "risk": t.risk,
            "description": t.description,
            "args": args_signature(t.input_model.model_json_schema()),
        }
        for t in registry.tools.values()
    ]
    tmpl = _env().from_string((PROMPTS_DIR / "system_agent.md").read_text(encoding="utf-8"))
    return tmpl.render(
        protocol=PROTOCOL_HELP, tools=tools, max_steps=max_steps, scope=scope, dry_run=dry_run, memory=memory
    )


def build_plan_request(task: str) -> str:
    return (
        f"Task: {task}\n\nBefore acting, write a short plan of 2-6 numbered sub-goals. "
        'Reply with ONE JSON object: {"plan": ["1. ...", "2. ..."]}'
    )
