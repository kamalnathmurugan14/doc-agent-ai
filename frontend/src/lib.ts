import type { AgentEvent, RunTrace } from "./api/client";

/** Convert a stored trace (steps table) back into timeline events so a finished run can be replayed read-only. */
export function traceToEvents(t: RunTrace): AgentEvent[] {
  const evs: AgentEvent[] = [
    {
      event: "run_started",
      data: { run_id: t.id, runtime: t.runtime, model: t.model, dry_run: t.dry_run, max_steps: "?" },
    },
  ];
  let step = 0;
  for (const s of t.steps) {
    if (s.type === "plan") evs.push({ event: "plan", data: { steps: s.tool_output } });
    else if (s.type === "thought") {
      step += 1;
      evs.push({ event: "thought", data: { text: s.tool_output?.text ?? "", step } });
    } else if (s.type === "action")
      evs.push({ event: "action", data: { tool: s.tool_name, args: s.tool_input, step, risk: null } });
    else if (s.type === "observation")
      evs.push({
        event: "observation",
        data: {
          tool: s.tool_name,
          step,
          duration_ms: s.duration_ms,
          ...(s.error ? { error: s.error } : { output: s.tool_output }),
        },
      });
    else if (s.type === "approval") {
      const status = s.tool_output?.status;
      if (status === "pending")
        evs.push({
          event: "approval_required",
          data: {
            action_id: s.tool_output.action_id,
            tool: s.tool_name,
            args: s.tool_input,
            preview: s.tool_output.preview,
          },
        });
      else
        evs.push({
          event: "approval_resolved",
          data: {
            action_id: "",
            decision: status === "approved" ? "approve" : "reject",
            reason: s.tool_output?.reason,
            edited: false,
          },
        });
    } else if (s.type === "final")
      evs.push({
        event: "final",
        data: { answer: s.tool_output?.answer ?? "", artifacts: s.tool_output?.artifacts ?? [] },
      });
    else if (s.type === "error")
      evs.push({ event: "error", data: { code: s.tool_output?.code ?? "ERROR", message: s.error ?? "" } });
  }
  return evs;
}

export const statusLabel = (s: string) => s.replace("_", " ");
