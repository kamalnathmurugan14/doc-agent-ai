import { useState } from "react";
import { api, qs, type RunSummary, type RunStatus } from "../api/client";
import { useAsync } from "../hooks/useAsync";

const STATUSES: ("" | RunStatus)[] = [
  "",
  "completed",
  "failed",
  "cancelled",
  "max_steps",
  "waiting_approval",
  "running",
];

export function RunHistory({ onOpen, activeId }: { onOpen: (id: string) => void; activeId?: string | null }) {
  const [status, setStatus] = useState("");
  const runs = useAsync(() => api<{ runs: RunSummary[] }>("/agent/runs?" + qs({ status })), [status]);
  return (
    <section className="card" aria-label="Run history">
      <div className="row">
        <label>
          Status{" "}
          <select value={status} onChange={(e) => setStatus(e.target.value)}>
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {s || "all"}
              </option>
            ))}
          </select>
        </label>
        <button type="button" onClick={runs.reload}>
          Refresh
        </button>
      </div>
      {runs.loading && <p className="muted">Loading…</p>}
      {runs.error && (
        <p className="error" role="alert">
          {runs.error}
        </p>
      )}
      {runs.data?.runs.length === 0 && <p className="empty">No runs yet.</p>}
      {!!runs.data?.runs.length && (
        <table>
          <thead>
            <tr>
              <th>task</th>
              <th>runtime</th>
              <th>status</th>
              <th>started</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {runs.data.runs.map((r) => (
              <tr key={r.id} className={r.id === activeId ? "active-row" : ""}>
                <td>
                  {r.task.length > 70 ? r.task.slice(0, 68) + "…" : r.task}
                  {r.dry_run && " (dry run)"}
                </td>
                <td>{r.runtime}</td>
                <td>
                  <span className={`chip status-${r.status}`}>{r.status}</span>
                </td>
                <td className="muted">{new Date(r.started_at).toLocaleString()}</td>
                <td>
                  <button type="button" onClick={() => onOpen(r.id)}>
                    Replay
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
