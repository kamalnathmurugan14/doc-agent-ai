# 5-step demo script (≈ 4 minutes)
1. **Setup** – `ollama serve`, backend + frontend running; open **Agent**. Show the explorer and the **Tools** page (9 tools, 3 risky ones, no delete).
2. **Read-only task** – click the example "Summarize everything in the invoices folder…" with *ReAct loop*; narrate the Thought → Action → Observation cards and the JSON input/output.
3. **Human approval** – the agent proposes `write_report`: show the preview, **Edit arguments** to change the title, then **Approve**; open the download link. Run "Organize my files…" and untick one of the proposed moves before approving.
4. **Guardrails** – re-run with **Dry run**; then ask it to "delete everything" (it has no tool) or let it read `misc/injection_test.txt`; press **Reject…** with a reason and show the agent adapting.
5. **Two runtimes + history** – switch to **LangGraph**, run again, then open **History** and replay both traces side by side. Mention that a LangGraph run survives a server restart while waiting for approval.
