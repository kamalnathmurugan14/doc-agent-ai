# Learning notes

## Concepts
- **Tool calling** – the model never runs anything. It *proposes* `{"tool", "args"}` as text; our code validates and executes it, and returns the result as the next message.
- **Plan → act → observe (ReAct)** – think, call a tool, read the result, repeat. `agent/react_loop.py` is the whole idea in ~60 lines.
- **Graph-based agents** – the same loop as nodes and edges (`agent/graph.py`). Benefits: explicit states, checkpoints, interrupts (pause for a human, resume later), easier to visualise. Cost: more machinery.
- **Structured action parsing** – JSON mode helps, but you still need validation + repair. Show the model its own mistake; it usually fixes it.
- **Guardrails** – enforce in code what you can't trust the model to do.
- **Human-in-the-loop** – approval before side effects, with a preview; rejections are *information* for the agent.
- **Deterministic agent tests** – a scripted fake LLM returns canned actions, so every behaviour (loops, rejections, timeouts, injection) is a fast, repeatable unit test. You test the *harness*, not the model.

## Milestones
**M0** scaffold, SQLite models. **M1** safe FS + explorer (+ `download`). **M2** tool framework, read tools (a found bug: a symlink pointing outside `DOCS_ROOT` crashed listing — now skipped and tested). **M3** LLM adapter + strict protocol + parser with repair. **M4** ReAct loop, loop detection, SSE + timeline UI. **M5** real Ollama run on read-only tasks (run it yourself; tests use the scripted model). **M6** write tools + previews + approval manager + approval UI. **M7** classifier adapter (HTTP to project 2 or rules). **M8** RAG adapter (HTTP to project 4 or BM25). **M9** LangGraph runtime with checkpointed interrupt/resume (lesson: *async* checkpoints can be lost in a crash → `durability="sync"`, and create the approval request inside the interrupting node, idempotently). **M10** memory, history replay, dry-run, batch approval. **M11** safety suite, "why agents fail", demo script.

## Exercises
1. Add a tool `compare_documents(a, b)`; give it a `preview`-less `read` risk and see the prompt update automatically.
2. Make `REQUIRE_APPROVAL=` empty and watch the dry-run/guardrails still hold.
3. Change `AGENT_MAX_STEPS` to 3 and try the "organize" task; what does the agent do when it runs out?
4. Replace the BM25 fallback with project 4 (`RAG_SERVICE_URL`) and compare search results for a paraphrased query.
5. Implement editable plans: pause after `plan`, let the user edit the list, feed it back.
