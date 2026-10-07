import { API_URL, ApiError } from "./client";

export interface SseEvent {
  event: string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  data: any;
}

/** POST a JSON body and read the Server-Sent Events response incrementally (EventSource only supports GET). */
export async function streamPost(
  path: string,
  body: unknown,
  onEvent: (e: SseEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  let res: Response;
  try {
    res = await fetch(API_URL + path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal,
    });
  } catch (e) {
    if ((e as Error).name === "AbortError") return;
    throw new ApiError("NETWORK", "Cannot reach the backend. Is it running on " + API_URL + "?", 0);
  }
  if (!res.ok) {
    const j = await res.json().catch(() => ({}));
    throw new ApiError(
      j?.error?.code ?? "HTTP_" + res.status,
      j?.error?.message ?? res.statusText,
      res.status,
    );
  }
  const reader = res.body!.getReader();
  const dec = new TextDecoder();
  let buf = "";
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true }).replace(/\r\n/g, "\n");
      let i: number;
      while ((i = buf.indexOf("\n\n")) >= 0) {
        const ev = parseBlock(buf.slice(0, i));
        buf = buf.slice(i + 2);
        if (ev) onEvent(ev);
      }
    }
  } catch (e) {
    if ((e as Error).name !== "AbortError") throw e;
  }
}

export function parseBlock(block: string): SseEvent | null {
  let event = "message";
  const data: string[] = [];
  for (const line of block.split("\n")) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) data.push(line.slice(5).trim());
  }
  if (data.length === 0) return null;
  try {
    return { event, data: JSON.parse(data.join("\n")) };
  } catch {
    return null;
  }
}
