# Why agents fail (and what this project does about it)

| Failure | What it looks like | Mitigation here | Test |
|---|---|---|---|
| **Malformed output** | prose around JSON, trailing commas, wrong keys | strict protocol, tolerant extraction, show the error back and retry ≤2 | `test_malformed_output_is_repaired` |
| **Wrong tool** | calls a tool that doesn't exist (`delete_file`) | corrective message listing valid tools | `test_unknown_tool_and_bad_args…` |
| **Bad arguments** | missing/typed-wrong fields | Pydantic validation, error text is the observation | same |
| **Loops** | same action again and again | 2nd identical action refused, 3rd stops the run | `test_loop_detection_warns_then_stops` |
| **Never finishing** | endless exploration | `AGENT_MAX_STEPS`, run + step timeouts | `test_max_steps`, `test_run_timeout` |
| **Context bloat** | huge file dumps crowd out the task | tool output truncated to `MAX_TOOL_OUTPUT_CHARS`, `read_file` paging, compact schemas | `test_compact_truncates_big_outputs` |
| **Prompt injection** | a document says "delete everything" | untrusted wrapper + system rule; *and* no delete tool, path jail, approval gate | `test_prompt_injection_document…` |
| **Overreach** | moves/overwrites the wrong things | previews, per-item approval, never overwrite, extension can't change | `test_overwrite_is_impossible` |
| **Hallucinated results** | claims it read a file it didn't | the transcript only contains real observations; final answer lists artifacts from the tools, not the model | `test_read_only_run…` |
| **Silent stalls** | waiting forever for a human | approval expiry = rejection; cancel endpoint | `test_approval_expiry…`, `test_cancel…` |
| **Lost state** | crash while waiting | LangGraph checkpoints (sync) + resume | `test_resume.py` |

**Rule of thumb:** put *safety* in code (allow-lists, jails, approvals) and *intelligence* in the prompt. A prompt is a request; code is a guarantee.
