import type { MoveItem, Preview } from "../api/client";

interface Props {
  preview: Preview;
  /** Batch moves: which items are ticked, and a change handler (omit for read-only replay). */
  checked?: number[];
  onToggle?: (index: number) => void;
}

/** Shows exactly what an approved action would change: new file content, a rename, or a list of moves with per-item checkboxes. */
export function DiffPreview({ preview, checked, onToggle }: Props) {
  if (preview.items) {
    return (
      <div className="diff" aria-label="Proposed moves">
        <table>
          <thead>
            <tr>
              <th />
              <th>from</th>
              <th>to</th>
              <th>status</th>
            </tr>
          </thead>
          <tbody>
            {preview.items.map((it: MoveItem) => (
              <tr key={it.index} className={it.ok ? "" : "bad"}>
                <td>
                  {onToggle && (
                    <input
                      type="checkbox"
                      aria-label={`Move ${it.source}`}
                      disabled={!it.ok}
                      checked={!!checked?.includes(it.index)}
                      onChange={() => onToggle(it.index)}
                    />
                  )}
                </td>
                <td>
                  <code className="del">{it.source}</code>
                </td>
                <td>
                  <code className="add">{it.destination}</code>
                </td>
                <td>{it.ok ? "ok" : `✘ ${it.problem}`}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }
  if (preview.before !== undefined) {
    return (
      <div className="diff">
        <code className="del">− {preview.before}</code>
        <br />
        <code className="add">+ {preview.after}</code>
      </div>
    );
  }
  return (
    <div className="diff">
      <p>
        <code className="add">+ new file {preview.destination}</code>{" "}
        <span className="muted">({preview.bytes} bytes)</span>
      </p>
      <pre className="output">{preview.content_head}</pre>
      {preview.note && <p className="muted">{preview.note}</p>}
    </div>
  );
}
