import { api, type ToolSpec } from "../api/client";
import { ToolList } from "../components/ToolList";
import { useAsync } from "../hooks/useAsync";

export function ToolsPage() {
  const tools = useAsync(() => api<{ tools: ToolSpec[] }>("/tools"), []);
  return (
    <>
      <h2>Tools</h2>
      <p className="muted">
        The complete allow-list. There is deliberately no delete tool and no shell access.
      </p>
      {tools.loading && <p className="muted">Loading…</p>}
      {tools.error && (
        <p className="error" role="alert">
          {tools.error}
        </p>
      )}
      {tools.data && <ToolList tools={tools.data.tools} />}
    </>
  );
}
