import type { ReactNode } from "react";

const META: Record<string, { icon: string; label: string }> = {
  plan: { icon: "🗺️", label: "Plan" },
  thought: { icon: "💭", label: "Thought" },
  action: { icon: "🔧", label: "Action" },
  observation: { icon: "👁️", label: "Observation" },
  approval: { icon: "🛑", label: "Approval" },
  final: { icon: "✅", label: "Final answer" },
  error: { icon: "⚠️", label: "Error" },
};

interface Props {
  kind: keyof typeof META | string;
  title?: string;
  ms?: number | null;
  error?: boolean;
  children?: ReactNode;
  json?: unknown;
  jsonLabel?: string;
}

/** One card in the timeline. Large JSON is collapsed by default. */
export function StepCard({ kind, title, ms, error, children, json, jsonLabel = "details" }: Props) {
  const m = META[kind] ?? { icon: "•", label: kind };
  return (
    <article className={`step ${kind}${error ? " is-error" : ""}`}>
      <header>
        <span aria-hidden>{m.icon}</span> <strong>{title ?? m.label}</strong>
        {ms != null && <span className="muted"> · {ms} ms</span>}
      </header>
      {children}
      {json !== undefined && json !== null && (
        <details>
          <summary>{jsonLabel}</summary>
          <pre className="output">{JSON.stringify(json, null, 2)}</pre>
        </details>
      )}
    </article>
  );
}
