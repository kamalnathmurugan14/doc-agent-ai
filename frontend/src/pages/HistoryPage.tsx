import { useState } from "react";
import { api, type RunTrace } from "../api/client";
import { RunHistory } from "../components/RunHistory";
import { RunTimeline } from "../components/RunTimeline";
import { traceToEvents } from "../lib";

export function HistoryPage() {
  const [trace, setTrace] = useState<RunTrace | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const open = async (id: string) => {
    try {
      setTrace(await api<RunTrace>(`/agent/runs/${id}`));
      setErr(null);
    } catch (e) {
      setErr((e as Error).message);
    }
  };
  return (
    <>
      <h2>History</h2>
      <RunHistory onOpen={open} activeId={trace?.id} />
      {err && (
        <p className="error" role="alert">
          {err}
        </p>
      )}
      {trace && (
        <section aria-label="Replay">
          <h3>Replay · {trace.task}</h3>
          <p className="muted">
            {trace.status} · {trace.runtime} · {trace.model}
            {trace.error ? ` · ${trace.error}` : ""}
          </p>
          <RunTimeline events={traceToEvents(trace)} readOnly />
        </section>
      )}
    </>
  );
}
