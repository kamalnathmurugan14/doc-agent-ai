"""Throw-away backend for Playwright: temp docs and a scripted demo 'model' (no Ollama needed). Served on :8000."""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import uvicorn  # noqa: E402

from app.adapters.llm import ChatLLM  # noqa: E402
from app.config import Settings  # noqa: E402
from app.deps import Container  # noqa: E402
from app.main import create_app  # noqa: E402


def action(tool: str, thought: str, **args) -> str:
    return json.dumps({"thought": thought, "action": {"tool": tool, "args": args}})


class DemoLLM(ChatLLM):
    model = "demo-model"

    async def chat(self, messages, json_mode=True, temperature=0.1):
        last = messages[-1]["content"]
        if last.startswith("Task:"):
            return action("list_files", "First I look at what documents exist.", path="invoices")
        if last.startswith('Observation from tool "list_files"'):
            return action(
                "move_file",
                "Group the invoices into one folder.",
                moves=[
                    {"source": "invoices/jan.txt", "destination": "Billing/"},
                    {"source": "invoices/feb.txt", "destination": "Billing/"},
                ],
            )
        if last.startswith('Observation from tool "move_file"'):
            n = last.count('"status": "moved"')
            return json.dumps({"final_answer": f"Moved {n} invoice file(s) into Billing/."})
        if "User rejected" in last:
            return json.dumps({"final_answer": "OK, I left everything unchanged."})
        return json.dumps({"final_answer": "Nothing to do."})


tmp = Path(tempfile.mkdtemp())
docs = tmp / "docs"
(docs / "invoices").mkdir(parents=True)
(docs / "invoices" / "jan.txt").write_text("INVOICE INV-1042 Bill to: Acme Total due: $1000", encoding="utf-8")
(docs / "invoices" / "feb.txt").write_text("INVOICE INV-1043 Bill to: Globex Total due: $440", encoding="utf-8")
s = Settings(docs_root=docs, data_dir=tmp / "data", _env_file=None)
uvicorn.run(create_app(s, Container(s, llm=DemoLLM())), host="127.0.0.1", port=8000, log_level="warning")
