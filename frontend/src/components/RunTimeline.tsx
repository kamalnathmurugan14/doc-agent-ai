import { useEffect, useRef } from "react";
import { API_URL, type AgentEvent } from "../api/client";
import { ApprovalCard } from "./ApprovalCard";
import { DiffPreview } from "./DiffPreview";
import { StepCard } from "./StepCard";

interface Props {
  events: AgentEvent[];
  readOnly?: boolean;
  onChanged?: () => void;
}

/** Vertical stream of step cards. Approval cards are interactive until a matching approval_resolved event arrives. */
export function RunTimeline({ events, readOnly, onChanged }: Props) {
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => {
    end.current?.scrollIntoView?.({ block: "end" });
  }, [events.length]);
  const resolved = new Set(
    events.filter((e) => e.event === "approval_resolved").map((e) => e.data.action_id),
  );
  if (events.length === 0)
    return <p className="empty">The agent's thoughts, tool calls and approvals will appear here.</p>;
  return (
    <div className="timeline" aria-label="Run timeline" aria-live="polite">
      {events.map((e, i) => {
        const d = e.data;
        switch (e.event) {
          case "run_started":
            return (
              <p key={i} className="muted">
                ▶ {d.runtime} · {d.model}
                {d.dry_run ? " · DRY RUN (no files will change)" : ""} · max {d.max_steps} steps
              </p>
            );
          case "plan":
            return (
              <StepCard key={i} kind="plan">
                <ol>
                  {(d.steps as string[]).map((s) => (
                    <li key={s}>{s.replace(/^\d+[.)]\s*/, "")}</li>
                  ))}
                </ol>
              </StepCard>
            );
          case "thought":
            return (
              <StepCard key={i} kind="thought" title={`Thought · step ${d.step}`}>
                <p>{d.text || <span className="muted">(no explanation)</span>}</p>
              </StepCard>
            );
          case "action":
            return (
              <StepCard key={i} kind="action" title={`${d.tool}`} json={d.args} jsonLabel="input">
                {d.risk === "write" && <span className="chip warnchip">changes files</span>}
              </StepCard>
            );
          case "observation":
            return (
              <StepCard
                key={i}
                kind="observation"
                title={`Result of ${d.tool}`}
                ms={d.duration_ms}
                error={!!d.error}
                json={d.error ? undefined : d.output}
                jsonLabel="output"
              >
                {d.error && <p className="error">{d.error}</p>}
                {d.output?.dry_run && <p className="chip warnchip">simulated – nothing was changed</p>}
              </StepCard>
            );
          case "approval_required":
            return resolved.has(d.action_id) || readOnly ? (
              <StepCard key={i} kind="approval" title={`Approval requested for ${d.tool}`}>
                <DiffPreview preview={d.preview} />
              </StepCard>
            ) : (
              <ApprovalCard
                key={i}
                actionId={d.action_id}
                tool={d.tool}
                args={d.args}
                preview={d.preview}
                onDone={onChanged}
              />
            );
          case "approval_resolved":
            return (
              <StepCard key={i} kind="approval" title={d.decision === "approve" ? "Approved" : "Rejected"}>
                {d.reason && <p>Reason: {d.reason}</p>}
                {d.edited && <p className="muted">Arguments were edited.</p>}
              </StepCard>
            );
          case "max_steps_reached":
            return (
              <StepCard key={i} kind="error" title="Step limit reached" error>
                <p>The agent used all {d.steps} steps.</p>
              </StepCard>
            );
          case "error":
            return (
              <StepCard key={i} kind="error" title={d.code} error>
                <p className="error">{d.message}</p>
              </StepCard>
            );
          case "final":
            return (
              <StepCard key={i} kind="final">
                <p className="answer">{d.answer}</p>
                {d.artifacts?.length > 0 && (
                  <ul className="plain">
                    {(d.artifacts as string[]).map((a) => (
                      <li key={a}>
                        <code>{a}</code>{" "}
                        <a href={`${API_URL}/fs/download?path=${encodeURIComponent(a)}`}>download</a>{" "}
                        <button type="button" onClick={() => navigator.clipboard?.writeText(a)}>
                          copy path
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </StepCard>
            );
          default:
            return null;
        }
      })}
      <div ref={end} />
    </div>
  );
}
