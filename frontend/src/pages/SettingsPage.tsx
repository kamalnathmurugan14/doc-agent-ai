import { api, type Health } from "../api/client";
import { useAsync } from "../hooks/useAsync";

const dot = (ok: boolean) => (ok ? "✔" : "✘");

export function SettingsPage() {
  const h = useAsync(() => api<Health>("/health"), []);
  return (
    <>
      <h2>Settings</h2>
      <div className="card">
        {h.loading && <p className="muted">Loading…</p>}
        {h.error && (
          <p className="error" role="alert">
            {h.error}
          </p>
        )}
        {h.data && (
          <ul className="plain">
            <li>
              API: <strong>{h.data.status}</strong> v{h.data.version}
            </li>
            <li>
              Ollama {dot(h.data.ollama)} model <code>{h.data.model}</code>
              {!h.data.ollama && (
                <>
                  {" "}
                  — run <code>ollama serve</code> and <code>ollama pull {h.data.model}</code>
                </>
              )}
            </li>
            <li>
              Search adapter: <code>{h.data.retriever.name}</code> {dot(h.data.retriever.ok)}
            </li>
            <li>
              Classifier adapter: <code>{h.data.classifier.name}</code> {dot(h.data.classifier.ok)}
            </li>
            <li>
              Approval required for:{" "}
              {h.data.require_approval.length ? (
                h.data.require_approval.join(", ")
              ) : (
                <strong>nothing (writes run without asking!)</strong>
              )}
            </li>
          </ul>
        )}
        <p className="muted">
          Change these in <code>backend/.env</code> (<code>REQUIRE_APPROVAL</code>,{" "}
          <code>RAG_SERVICE_URL</code>, <code>CLASSIFIER_SERVICE_URL</code>, <code>AGENT_MAX_STEPS</code>…)
          and restart the backend.
        </p>
        <button type="button" onClick={h.reload}>
          Re-check
        </button>
      </div>
    </>
  );
}
