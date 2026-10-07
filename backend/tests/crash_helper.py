"""Run in a SUBPROCESS by test_resume.py: start a LangGraph run, wait until it needs approval, then die abruptly (os._exit)."""

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.adapters.classifier import FakeClassifier  # noqa: E402
from app.adapters.retriever import Bm25Retriever  # noqa: E402
from app.config import Settings  # noqa: E402
from app.deps import Container  # noqa: E402
from tests.conftest import ScriptedLLM, act  # noqa: E402

docs, data = Path(sys.argv[1]), Path(sys.argv[2])
settings = Settings(docs_root=docs, data_dir=data, _env_file=None)
llm = ScriptedLLM([act("rename_file", path="root.txt", new_name="renamed.txt")])
container = Container(settings, llm=llm, retriever=Bm25Retriever(settings), classifier=FakeClassifier())


async def main() -> None:
    live = await container.runs.start("rename the root file", "langgraph")
    async for ev in live.bus.subscribe():
        if ev["event"] == "approval_required":
            print(f"READY {ev['data']['action_id']} {live.run_id}", flush=True)
            os._exit(0)  # simulate a crash: no cleanup handlers, no CancelledError handling


asyncio.run(main())
