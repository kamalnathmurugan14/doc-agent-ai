import { useCallback, useState, type DragEvent } from "react";
import { api, qs, type Entry, type Tree } from "../api/client";
import { useAsync } from "../hooks/useAsync";

interface Props {
  /** Show a checkbox on every file AND folder. Folders are selected as "path/" (trailing slash). */
  selectable?: boolean;
  selected?: string[];
  onSelectionChange?: (paths: string[]) => void;
  onOpenFile?: (e: Entry) => void;
  /** Called after an upload so the parent can e.g. trigger indexing. */
  onUploaded?: (saved: string[]) => void;
}

/** Selection key: folders end with a slash so the parent can tell them apart from files. */
export const key = (e: Entry) => (e.type === "dir" ? e.path + "/" : e.path);

const fmtSize = (n: number) =>
  n < 1024 ? `${n} B` : n < 1048576 ? `${(n / 1024).toFixed(1)} KB` : `${(n / 1048576).toFixed(1)} MB`;
const ICON: Record<string, string> = { pdf: "📕", docx: "📘", txt: "📄", md: "📝" };

/** Reusable explorer: breadcrumb, folder navigation, refresh, optional checkboxes, drag-and-drop upload. */
export function FileExplorer({
  selectable,
  selected = [],
  onSelectionChange,
  onOpenFile,
  onUploaded,
}: Props) {
  const [path, setPath] = useState("");
  const [over, setOver] = useState(false);
  const [msg, setMsg] = useState<{ kind: "ok" | "err"; text: string } | null>(null);
  const { data, error, loading, reload } = useAsync(() => api<Tree>("/fs/tree?" + qs({ path })), [path]);

  const upload = useCallback(
    async (files: FileList | File[]) => {
      const form = new FormData();
      Array.from(files).forEach((f) => form.append("files", f));
      try {
        const res = await api<{ saved: string[] }>("/fs/upload?" + qs({ path }), {
          method: "POST",
          body: form,
        });
        setMsg({ kind: "ok", text: `Saved ${res.saved.join(", ")}` });
        reload();
        onUploaded?.(res.saved);
      } catch (e) {
        setMsg({ kind: "err", text: (e as Error).message });
      }
    },
    [path, reload, onUploaded],
  );

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setOver(false);
    if (e.dataTransfer.files.length) void upload(e.dataTransfer.files);
  };
  const toggle = (p: string) =>
    onSelectionChange?.(selected.includes(p) ? selected.filter((x) => x !== p) : [...selected, p]);
  const crumbs = path ? path.split("/") : [];

  return (
    <section className="explorer card" aria-label="File explorer">
      <div className="row">
        <nav aria-label="Breadcrumb" className="row" style={{ flex: 1, gap: 4 }}>
          <button type="button" className="chip" onClick={() => setPath("")}>
            docs root
          </button>
          {crumbs.map((c, i) => (
            <span key={i}>
              /{" "}
              <button
                type="button"
                className="chip"
                onClick={() => setPath(crumbs.slice(0, i + 1).join("/"))}
              >
                {c}
              </button>
            </span>
          ))}
        </nav>
        <button type="button" onClick={reload} aria-label="Refresh">
          ⟳ Refresh
        </button>
      </div>
      {loading && <p className="muted">Loading…</p>}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {data && data.entries.length === 0 && (
        <p className="empty">This folder has no supported files yet. Drop some below.</p>
      )}
      {data && data.entries.length > 0 && (
        <ul>
          {data.entries.map((e) => (
            <li key={e.path}>
              <div className="item">
                {selectable && (
                  <input
                    type="checkbox"
                    aria-label={`Select ${e.name}`}
                    checked={selected.includes(key(e))}
                    onChange={() => toggle(key(e))}
                  />
                )}
                <span aria-hidden>
                  {e.type === "dir" ? "📁" : (ICON[e.name.split(".").pop() ?? ""] ?? "📄")}
                </span>
                <button
                  type="button"
                  className="link"
                  onClick={() => (e.type === "dir" ? setPath(e.path) : onOpenFile?.(e))}
                >
                  {e.name}
                </button>
                <span className="muted" style={{ marginLeft: "auto" }}>
                  {e.type === "file" && fmtSize(e.size) + " · "}
                  {new Date(e.modified).toLocaleDateString()}
                </span>
              </div>
            </li>
          ))}
        </ul>
      )}
      <div
        className={`dropzone${over ? " over" : ""}`}
        onDragOver={(e) => {
          e.preventDefault();
          setOver(true);
        }}
        onDragLeave={() => setOver(false)}
        onDrop={onDrop}
      >
        Drag &amp; drop files here, or{" "}
        <label style={{ color: "var(--accent)", cursor: "pointer", textDecoration: "underline" }}>
          browse
          <input
            type="file"
            multiple
            className="sr-only"
            onChange={(e) => e.target.files && void upload(e.target.files)}
          />
        </label>
        <div className="muted">pdf, docx, txt, md</div>
      </div>
      {msg && (
        <p role="status" className={msg.kind === "err" ? "error" : ""}>
          {msg.text}
        </p>
      )}
    </section>
  );
}
