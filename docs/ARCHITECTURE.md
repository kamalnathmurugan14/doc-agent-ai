# Architecture

| Module | Responsibility |
|---|---|
| `tools/*` | Typed tools: `name`, LLM description, Pydantic input, `risk` (read/write), `kind` (for `REQUIRE_APPROVAL`), `run()`, and `preview()` for write tools. `registry.py` is the allow-list. |
| `adapters/*` | `ChatLLM`, `Retriever`, `Classifier` interfaces with HTTP (projects 4/2), built-in fallback (BM25 / keyword rules) and fake implementations. Chosen from `.env`. |
| `agent/base.py` | `AgentCore`: everything about one run except the control flow — prompts, `decide()` (JSON parse + repair), `prepare()` (validate tool/args, loop guard), approvals, `execute()`, event+step persistence, finishing. `AgentRuntime` is the interface. |
| `agent/react_loop.py` | Runtime A: a plain `while` loop (~60 lines) — the clearest way to learn the mechanics. |
| `agent/graph.py` | Runtime B: LangGraph `plan -> act -> (approval) -> observe -> act …`; `interrupt()` pauses at the approval node; SQLite checkpoints (`durability="sync"`); resume with `Command(resume=…)`. |
| `agent/parser.py`, `guardrails.py`, `planner_prompt.py` | Strict action protocol; loop counters + untrusted-data wrapper; system prompt generated from the registry. |
| `services/run_service.py` | Runs are background asyncio tasks (a closed tab doesn't kill them); live `RunBus` replays history to late subscribers; cancel; startup recovery; resume of orphaned LangGraph runs. |
| `services/approval_service.py` | `pending_actions` rows + one future per action; expiry = rejection; edits and per-item selection. |

## One step, both runtimes
1. **decide** – messages → Ollama (JSON mode) → `parse_decision`; invalid output is shown back to the model and retried (≤2).
2. **prepare** – unknown tool / invalid args → corrective observation; repeated action → warn (2nd) / stop (3rd).
3. **approval?** – write tool whose kind is in `REQUIRE_APPROVAL` and not dry-run: build the preview, persist a pending action, emit `approval_required`, pause.
4. **execute** – the tool runs with a timeout; dry-run returns the preview instead; errors become observations.
5. **observe** – output is truncated, wrapped as untrusted data, appended to the transcript; step counter +1.

## Decisions & trade-offs
- **Two runtimes, one core.** The same guardrails and prompts back both, so the UI toggle compares *control flow*, not behaviour.
- **Background runs + event bus** instead of tying the run to the SSE connection: approvals can take minutes, and reloading the page must not kill the agent.
- **LangGraph durability:** the default checkpoint mode is asynchronous; a crash right after an approval request lost the state in a test. We use `durability="sync"` and create the pending action *inside* the approval node (after the previous node's checkpoint), idempotently, because LangGraph re-executes a node from the top when it resumes.
- **ReAct is not resumable** (its loop lives in memory); after a restart it is marked failed and its pending action expires — an honest limitation, documented.
- **Rejections are data.** "User rejected: reason" goes back as an observation so the agent can adapt instead of crashing.
- **Batch tool for moves** (`moves: [...]`): one approval card per proposal, per-item checkboxes, and the server re-validates every item at execution time (state may have changed).
- **No delete tool at all** is a stronger guarantee than a delete tool behind approval.
- **Observations are untrusted.** Wrapping + instructions lower prompt-injection risk; the hard guarantees come from code, not from the prompt.
