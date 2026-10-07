import { useState } from "react";
import type { Runtime } from "../api/client";
import { FileExplorer } from "../components/FileExplorer";
import { RunTimeline } from "../components/RunTimeline";
import { TaskInput } from "../components/TaskInput";
import { useAgentRun } from "../hooks/useAgentRun";

export function AgentPage() {
  const run = useAgentRun();
  const [runtime, setRuntime] = useState<Runtime>("react");
  const [dryRun, setDryRun] = useState(false);
  const [plan, setPlan] = useState(false);
  const [scope, setScope] = useState<string[]>([]);
  const waiting =
    run.events.some((e) => e.event === "approval_required") &&
    !run.events.some((e) => ["final", "error"].includes(e.event));
  const pendingApproval = (() => {
    const req = run.events.filter((e) => e.event === "approval_required").length;
    const res = run.events.filter((e) => e.event === "approval_resolved").length;
    return waiting && req > res;
  })();

  return (
    <>
      <h2>Agent</h2>
      <div className="agent">
        <div>
          <FileExplorer selectable selected={scope} onSelectionChange={setScope} />
          <p className="muted">Tick files or folders to restrict the agent; leave empty for everything.</p>
        </div>
        <div>
          <TaskInput
            running={run.running}
            runtime={runtime}
            onRuntime={setRuntime}
            dryRun={dryRun}
            onDryRun={setDryRun}
            plan={plan}
            onPlan={setPlan}
            scopeLabel={scope.length ? `${scope.length} selected` : "all documents"}
            onStop={run.stop}
            onRun={(task) =>
              run.start({
                task,
                runtime,
                dry_run: dryRun,
                plan,
                scope: {
                  files: scope.filter((p) => !p.endsWith("/")),
                  folders: scope.filter((p) => p.endsWith("/")).map((p) => p.slice(0, -1)),
                },
              })
            }
          />
          {run.running && (
            <p role="status" className="badge">
              {pendingApproval ? "⏸ Waiting for approval" : "⏳ Running…"}
            </p>
          )}
          {run.error && (
            <p className="error" role="alert">
              {run.error}
            </p>
          )}
          <RunTimeline events={run.events} />
        </div>
      </div>
    </>
  );
}
