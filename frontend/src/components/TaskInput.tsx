import { useState, type FormEvent } from "react";
import type { Runtime } from "../api/client";

export const EXAMPLES = [
  "Find all contracts that expire this year, summarize each, and write a report.",
  "Organize my files into folders by category (propose first).",
  "Find duplicate files and propose a clean-up plan.",
  "Summarize everything in the invoices folder into one report with totals.",
];

interface Props {
  running: boolean;
  runtime: Runtime;
  onRuntime: (r: Runtime) => void;
  dryRun: boolean;
  onDryRun: (v: boolean) => void;
  plan: boolean;
  onPlan: (v: boolean) => void;
  onRun: (task: string) => void;
  onStop: () => void;
  scopeLabel: string;
}

export function TaskInput({
  running,
  runtime,
  onRuntime,
  dryRun,
  onDryRun,
  plan,
  onPlan,
  onRun,
  onStop,
  scopeLabel,
}: Props) {
  const [task, setTask] = useState("");
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (task.trim() && !running) onRun(task.trim());
  };
  return (
    <form className="card" onSubmit={submit}>
      <label htmlFor="task">What should the agent do?</label>
      <textarea
        id="task"
        rows={3}
        value={task}
        onChange={(e) => setTask(e.target.value)}
        placeholder="Describe a task over your documents…"
        disabled={running}
      />
      <div className="row" aria-label="Examples">
        {EXAMPLES.map((ex) => (
          <button key={ex} type="button" className="chip" onClick={() => setTask(ex)} disabled={running}>
            {ex.length > 46 ? ex.slice(0, 44) + "…" : ex}
          </button>
        ))}
      </div>
      <div className="row" style={{ marginTop: 10 }}>
        <div className="segmented" role="group" aria-label="Runtime">
          <button
            type="button"
            aria-pressed={runtime === "react"}
            onClick={() => onRuntime("react")}
            disabled={running}
          >
            ReAct loop
          </button>
          <button
            type="button"
            aria-pressed={runtime === "langgraph"}
            onClick={() => onRuntime("langgraph")}
            disabled={running}
          >
            LangGraph
          </button>
        </div>
        <label className="row">
          <input
            type="checkbox"
            checked={dryRun}
            onChange={(e) => onDryRun(e.target.checked)}
            disabled={running}
          />{" "}
          Dry run
        </label>
        <label className="row">
          <input
            type="checkbox"
            checked={plan}
            onChange={(e) => onPlan(e.target.checked)}
            disabled={running}
          />{" "}
          Plan first
        </label>
        <span className="muted">Scope: {scopeLabel}</span>
        <span style={{ flex: 1 }} />
        {running ? (
          <button type="button" onClick={onStop}>
            ■ Stop
          </button>
        ) : (
          <button className="primary" type="submit" disabled={!task.trim()}>
            ▶ Run
          </button>
        )}
      </div>
    </form>
  );
}
