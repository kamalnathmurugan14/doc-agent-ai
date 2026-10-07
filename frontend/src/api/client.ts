// Tiny typed fetch wrapper. Every backend error has the shape { error: { code, message } }.
export const API_URL: string = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  constructor(
    public code: string,
    message: string,
    public status: number,
  ) {
    super(message);
  }
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, init);
  } catch {
    throw new ApiError("NETWORK", "Cannot reach the backend. Is it running on " + API_URL + "?", 0);
  }
  if (res.status === 204) return undefined as T;
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new ApiError(
      body?.error?.code ?? "HTTP_" + res.status,
      body?.error?.message ?? res.statusText,
      res.status,
    );
  }
  return body as T;
}

export const post = <T>(path: string, body?: unknown) =>
  api<T>(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body ?? {}),
  });

export const qs = (params: Record<string, string | number | undefined>) =>
  new URLSearchParams(
    Object.entries(params)
      .filter(([, v]) => v !== undefined && v !== "")
      .map(([k, v]) => [k, String(v)]),
  ).toString();

// Free-form JSON coming from tool inputs/outputs (shape depends on the tool).
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type Json = any;

// ---- types -------------------------------------------------------------
export interface Entry {
  name: string;
  type: "dir" | "file";
  size: number;
  modified: string;
  path: string;
}
export interface Tree {
  path: string;
  entries: Entry[];
}
export type Runtime = "react" | "langgraph";
export type RunStatus = "running" | "waiting_approval" | "completed" | "failed" | "cancelled" | "max_steps";
export interface AgentEvent {
  event: string;
  data: Record<string, Json>;
}
export interface MoveItem {
  index: number;
  source: string;
  destination: string;
  ok: boolean;
  problem: string | null;
}
export interface Preview {
  action?: string;
  destination?: string;
  bytes?: number;
  content_head?: string;
  note?: string;
  before?: string;
  after?: string;
  items?: MoveItem[];
  ok_count?: number;
}
export interface ToolSpec {
  name: string;
  description: string;
  risk: "read" | "write";
  kind: string;
  requires_approval: boolean;
  input_schema: { properties?: Record<string, { type?: string; description?: string }>; required?: string[] };
}
export interface RunSummary {
  id: string;
  task: string;
  status: RunStatus;
  runtime: Runtime;
  model: string;
  dry_run: boolean;
  started_at: string;
  finished_at: string | null;
  final_answer: string | null;
  error: string | null;
}
export interface TraceStep {
  idx: number;
  type: string;
  tool_name: string | null;
  tool_input: Json;
  tool_output: Json;
  error: string | null;
  duration_ms: number | null;
}
export interface PendingAction {
  id: string;
  tool_name: string;
  args: Record<string, unknown>;
  preview: Preview;
  status: string;
}
export interface RunTrace extends RunSummary {
  steps: TraceStep[];
  pending_actions: PendingAction[];
}
export interface Health {
  status: string;
  version: string;
  ollama: boolean;
  model: string;
  require_approval: string[];
  retriever: { name: string; ok: boolean };
  classifier: { name: string; ok: boolean };
}
