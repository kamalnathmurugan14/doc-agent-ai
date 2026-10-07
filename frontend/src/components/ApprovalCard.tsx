import { useState } from "react";
import { decide } from "../hooks/useAgentRun";
import type { Preview } from "../api/client";
import { DiffPreview } from "./DiffPreview";

interface Props {
  actionId: string;
  tool: string;
  args: Record<string, unknown>;
  preview: Preview;
  onDone?: () => void;
}

export function ApprovalCard({ actionId, tool, args, preview, onDone }: Props) {
  const [checked, setChecked] = useState<number[]>(
    (preview.items ?? []).filter((i) => i.ok).map((i) => i.index),
  );
  const [reason, setReason] = useState("");
  const [rejecting, setRejecting] = useState(false);
  const [editing, setEditing] = useState(false);
  const [json, setJson] = useState(JSON.stringify(args, null, 2));
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const send = async (decision: "approve" | "reject") => {
    setBusy(true);
    setErr(null);
    try {
      let edited: unknown;
      if (decision === "approve" && editing) edited = JSON.parse(json);
      await decide(actionId, {
        decision,
        reason: reason || undefined,
        edited_args: edited,
        approved_items: decision === "approve" && preview.items && !editing ? checked : undefined,
      });
      onDone?.();
    } catch (e) {
      setErr(e instanceof SyntaxError ? "The edited arguments are not valid JSON." : (e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const toggle = (i: number) => setChecked((c) => (c.includes(i) ? c.filter((x) => x !== i) : [...c, i]));

  return (
    <section className="card approval" role="group" aria-label="Approval required">
      <h3 style={{ marginTop: 0 }}>
        🛑 Approval required: <code>{tool}</code>
      </h3>
      <DiffPreview preview={preview} checked={checked} onToggle={editing ? undefined : toggle} />
      {editing && (
        <label>
          Arguments (JSON)
          <textarea
            className="mono"
            rows={8}
            value={json}
            onChange={(e) => setJson(e.target.value)}
            aria-label="Edit arguments"
          />
        </label>
      )}
      {rejecting && (
        <label>
          Reason (the agent will see it)
          <input
            type="text"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            aria-label="Rejection reason"
          />
        </label>
      )}
      {err && (
        <p className="error" role="alert">
          {err}
        </p>
      )}
      <div className="row">
        <button
          className="primary"
          type="button"
          disabled={busy || (!editing && !!preview.items && checked.length === 0)}
          onClick={() => send("approve")}
        >
          Approve{preview.items && !editing ? ` (${checked.length})` : ""}
        </button>
        {!rejecting ? (
          <button type="button" disabled={busy} onClick={() => setRejecting(true)}>
            Reject…
          </button>
        ) : (
          <button type="button" disabled={busy} onClick={() => send("reject")}>
            Confirm reject
          </button>
        )}
        <button type="button" disabled={busy} onClick={() => setEditing((e) => !e)}>
          {editing ? "Cancel edit" : "Edit arguments"}
        </button>
      </div>
    </section>
  );
}
