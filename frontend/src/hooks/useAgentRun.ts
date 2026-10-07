import { useCallback, useRef, useState } from "react";
import { post, type AgentEvent, type Runtime } from "../api/client";
import { streamPost } from "../api/sse";

export interface RunOptions {
  task: string;
  runtime: Runtime;
  dry_run: boolean;
  plan: boolean;
  scope: { files: string[]; folders: string[] };
}

/** Starts a run and collects its SSE events. Stop = cancel on the server (the run otherwise continues in the background). */
export function useAgentRun() {
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const [runId, setRunId] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const ctrl = useRef<AbortController | null>(null);
  const idRef = useRef<string | null>(null);

  const start = useCallback(async (o: RunOptions) => {
    ctrl.current?.abort();
    const c = new AbortController();
    ctrl.current = c;
    setEvents([]);
    setError(null);
    setRunning(true);
    setRunId(null);
    idRef.current = null;
    try {
      await streamPost(
        "/agent/run",
        { task: o.task, runtime: o.runtime, dry_run: o.dry_run, plan: o.plan, scope: o.scope },
        (e) => {
          if (e.event === "run_started") {
            idRef.current = e.data.run_id;
            setRunId(e.data.run_id);
          }
          setEvents((evs) => [...evs, e]);
        },
        c.signal,
      );
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setRunning(false);
    }
  }, []);

  const stop = useCallback(async () => {
    const id = idRef.current;
    if (id) await post(`/agent/runs/${id}/cancel`).catch(() => undefined);
  }, []);

  return { events, runId, running, error, start, stop };
}

export function decide(
  actionId: string,
  body: { decision: "approve" | "reject"; reason?: string; edited_args?: unknown; approved_items?: number[] },
) {
  return post<{ status: string }>(`/agent/approve/${actionId}`, body);
}
