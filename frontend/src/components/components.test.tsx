import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { AgentEvent, Preview, RunTrace, ToolSpec } from "../api/client";
import { traceToEvents } from "../lib";
import { ApprovalCard } from "./ApprovalCard";
import { DiffPreview } from "./DiffPreview";
import { RunTimeline } from "./RunTimeline";
import { StepCard } from "./StepCard";
import { TaskInput } from "./TaskInput";
import { ToolList } from "./ToolList";

afterEach(() => vi.restoreAllMocks());
const ok = (b: unknown = {}) => Promise.resolve(new Response(JSON.stringify(b), { status: 200 }));

const movePreview: Preview = {
  action: "move_files",
  ok_count: 2,
  items: [
    { index: 0, source: "a/jan.txt", destination: "Invoices/jan.txt", ok: true, problem: null },
    { index: 1, source: "a/feb.txt", destination: "Invoices/feb.txt", ok: true, problem: null },
    { index: 2, source: "a/x.txt", destination: "a/y.txt", ok: false, problem: "destination already exists" },
  ],
};

describe("DiffPreview", () => {
  it("shows move items, disables invalid ones and reports toggles", async () => {
    const onToggle = vi.fn();
    render(<DiffPreview preview={movePreview} checked={[0, 1]} onToggle={onToggle} />);
    expect(screen.getByLabelText("Move a/x.txt")).toBeDisabled();
    expect(screen.getByText(/destination already exists/)).toBeInTheDocument();
    await userEvent.click(screen.getByLabelText("Move a/jan.txt"));
    expect(onToggle).toHaveBeenCalledWith(0);
  });
  it("shows rename before/after and new-file previews", () => {
    const { rerender } = render(<DiffPreview preview={{ before: "old.txt", after: "new.txt" }} />);
    expect(screen.getByText("− old.txt")).toBeInTheDocument();
    expect(screen.getByText("+ new.txt")).toBeInTheDocument();
    rerender(
      <DiffPreview
        preview={{
          destination: "_reports/r.md",
          bytes: 12,
          content_head: "# Report",
          note: "never overwritten",
        }}
      />,
    );
    expect(screen.getByText(/new file _reports\/r.md/)).toBeInTheDocument();
    expect(screen.getByText("# Report")).toBeInTheDocument();
  });
});

describe("ApprovalCard", () => {
  it("approves only the ticked batch items", async () => {
    const spy = vi.spyOn(globalThis, "fetch").mockImplementation(() => ok({ status: "approved" }));
    const onDone = vi.fn();
    render(
      <ApprovalCard
        actionId="act_1"
        tool="move_file"
        args={{ moves: [] }}
        preview={movePreview}
        onDone={onDone}
      />,
    );
    expect(screen.getByRole("button", { name: "Approve (2)" })).toBeEnabled();
    await userEvent.click(screen.getByLabelText("Move a/feb.txt")); // untick one
    await userEvent.click(screen.getByRole("button", { name: "Approve (1)" }));
    await waitFor(() => expect(onDone).toHaveBeenCalled());
    const [url, init] = spy.mock.calls[0];
    expect(String(url)).toContain("/agent/approve/act_1");
    expect(JSON.parse(String((init as RequestInit).body))).toMatchObject({
      decision: "approve",
      approved_items: [0],
    });
  });
  it("rejects with a reason", async () => {
    const spy = vi.spyOn(globalThis, "fetch").mockImplementation(() => ok({ status: "rejected" }));
    render(
      <ApprovalCard
        actionId="act_2"
        tool="rename_file"
        args={{ path: "a.txt", new_name: "b.txt" }}
        preview={{ before: "a.txt", after: "b.txt" }}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: "Reject…" }));
    await userEvent.type(screen.getByLabelText("Rejection reason"), "wrong name");
    await userEvent.click(screen.getByRole("button", { name: "Confirm reject" }));
    await waitFor(() => expect(spy).toHaveBeenCalled());
    expect(JSON.parse(String((spy.mock.calls[0][1] as RequestInit).body))).toMatchObject({
      decision: "reject",
      reason: "wrong name",
    });
  });
  it("sends edited arguments and flags invalid JSON", async () => {
    const spy = vi.spyOn(globalThis, "fetch").mockImplementation(() => ok({ status: "approved" }));
    render(
      <ApprovalCard
        actionId="act_3"
        tool="rename_file"
        args={{ path: "a.txt", new_name: "b.txt" }}
        preview={{ before: "a.txt", after: "b.txt" }}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: "Edit arguments" }));
    const box = screen.getByLabelText("Edit arguments");
    await userEvent.clear(box);
    await userEvent.type(box, "not json");
    await userEvent.click(screen.getByRole("button", { name: /^Approve/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent("not valid JSON");
    expect(spy).not.toHaveBeenCalled();
  });
  it("shows API errors", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(() =>
      Promise.resolve(
        new Response(JSON.stringify({ error: { code: "ALREADY_DECIDED", message: "already approved" } }), {
          status: 409,
        }),
      ),
    );
    render(
      <ApprovalCard
        actionId="act_4"
        tool="write_report"
        args={{}}
        preview={{ destination: "_reports/x.md", content_head: "x" }}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: /^Approve/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent("already approved");
  });
});

describe("RunTimeline", () => {
  const ev = (event: string, data: Record<string, unknown>): AgentEvent => ({ event, data });
  const base = [
    ev("run_started", { runtime: "react", model: "m", dry_run: true, max_steps: 5 }),
    ev("plan", { steps: ["1. list files", "2. report"] }),
    ev("thought", { text: "I should list the files", step: 1 }),
    ev("action", { tool: "list_files", args: { path: "" }, step: 1, risk: "read" }),
    ev("observation", { tool: "list_files", step: 1, duration_ms: 12, output: { count: 2 } }),
    ev("observation", { tool: "read_file", step: 2, error: "File not found" }),
  ];
  it("renders every step type with errors highlighted", () => {
    render(
      <RunTimeline
        events={[
          ...base,
          ev("max_steps_reached", { steps: 5 }),
          ev("final", { answer: "All done", artifacts: ["_reports/r.md"] }),
        ]}
      />,
    );
    expect(screen.getByText(/DRY RUN/)).toBeInTheDocument();
    expect(screen.getByText("list files")).toBeInTheDocument();
    expect(screen.getByText("I should list the files")).toBeInTheDocument();
    expect(screen.getByText("Result of list_files")).toBeInTheDocument();
    expect(screen.getByText("File not found")).toHaveClass("error");
    expect(screen.getByText("Step limit reached")).toBeInTheDocument();
    expect(screen.getByText("All done")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "download" })).toHaveAttribute(
      "href",
      expect.stringContaining("/fs/download?path=_reports%2Fr.md"),
    );
  });
  it("shows an interactive approval card until it is resolved", () => {
    const req = ev("approval_required", {
      action_id: "a1",
      tool: "rename_file",
      args: {},
      preview: { before: "x", after: "y" },
    });
    const { rerender } = render(<RunTimeline events={[...base, req]} />);
    expect(screen.getByRole("group", { name: "Approval required" })).toBeInTheDocument();
    rerender(
      <RunTimeline
        events={[
          ...base,
          req,
          ev("approval_resolved", { action_id: "a1", decision: "reject", reason: "no" }),
        ]}
      />,
    );
    expect(screen.queryByRole("group", { name: "Approval required" })).toBeNull();
    expect(screen.getByText("Rejected")).toBeInTheDocument();
    expect(screen.getByText("Reason: no")).toBeInTheDocument();
  });
  it("is read-only in replay mode and has an empty state", () => {
    const { rerender } = render(<RunTimeline events={[]} />);
    expect(screen.getByText(/will appear here/)).toBeInTheDocument();
    rerender(
      <RunTimeline
        readOnly
        events={[
          ev("approval_required", {
            action_id: "a1",
            tool: "rename_file",
            args: {},
            preview: { before: "x", after: "y" },
          }),
        ]}
      />,
    );
    expect(screen.queryByRole("button", { name: /Approve/ })).toBeNull();
  });
});

describe("TaskInput", () => {
  const props = {
    running: false,
    runtime: "react" as const,
    onRuntime: vi.fn(),
    dryRun: false,
    onDryRun: vi.fn(),
    plan: false,
    onPlan: vi.fn(),
    onRun: vi.fn(),
    onStop: vi.fn(),
    scopeLabel: "all documents",
  };
  it("fills the task from an example chip and runs it", async () => {
    const onRun = vi.fn();
    render(<TaskInput {...props} onRun={onRun} />);
    expect(screen.getByRole("button", { name: /Run/ })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: /Find duplicate files/ }));
    await userEvent.click(screen.getByRole("button", { name: /Run/ }));
    expect(onRun).toHaveBeenCalledWith("Find duplicate files and propose a clean-up plan.");
  });
  it("switches runtime, toggles dry-run, and shows Stop while running", async () => {
    const onRuntime = vi.fn(),
      onDryRun = vi.fn(),
      onStop = vi.fn();
    const { rerender } = render(<TaskInput {...props} onRuntime={onRuntime} onDryRun={onDryRun} />);
    await userEvent.click(screen.getByRole("button", { name: "LangGraph" }));
    await userEvent.click(screen.getByLabelText("Dry run"));
    expect(onRuntime).toHaveBeenCalledWith("langgraph");
    expect(onDryRun).toHaveBeenCalledWith(true);
    rerender(<TaskInput {...props} running onStop={onStop} />);
    await userEvent.click(screen.getByRole("button", { name: /Stop/ }));
    expect(onStop).toHaveBeenCalled();
    expect(screen.getByLabelText("What should the agent do?")).toBeDisabled();
  });
});

describe("ToolList / StepCard / traceToEvents", () => {
  it("lists tools with risk and approval badges", () => {
    const tools: ToolSpec[] = [
      {
        name: "read_file",
        description: "Read",
        risk: "read",
        kind: "read",
        requires_approval: false,
        input_schema: { properties: { path: { type: "string", description: "File" } }, required: ["path"] },
      },
      {
        name: "move_file",
        description: "Move",
        risk: "write",
        kind: "move",
        requires_approval: true,
        input_schema: { properties: { moves: { type: "array" } } },
      },
    ];
    render(<ToolList tools={tools} />);
    expect(screen.getByText("needs approval")).toBeInTheDocument();
    expect(screen.getByText("write")).toBeInTheDocument();
    expect(screen.getByText(/string · required/)).toBeInTheDocument();
  });
  it("StepCard collapses JSON", () => {
    render(<StepCard kind="action" title="read_file" json={{ path: "a" }} jsonLabel="input" />);
    expect(screen.getByText("input")).toBeInTheDocument();
  });
  it("converts a stored trace into replayable events", () => {
    const t = {
      id: "run_1",
      runtime: "react",
      model: "m",
      dry_run: false,
      task: "t",
      status: "completed",
      steps: [
        {
          idx: 0,
          type: "thought",
          tool_name: null,
          tool_input: null,
          tool_output: { text: "hm" },
          error: null,
          duration_ms: null,
        },
        {
          idx: 1,
          type: "action",
          tool_name: "list_files",
          tool_input: { path: "" },
          tool_output: null,
          error: null,
          duration_ms: null,
        },
        {
          idx: 2,
          type: "observation",
          tool_name: "list_files",
          tool_input: null,
          tool_output: { count: 1 },
          error: null,
          duration_ms: 5,
        },
        {
          idx: 3,
          type: "approval",
          tool_name: "rename_file",
          tool_input: {},
          tool_output: { status: "approved", reason: null },
          error: null,
          duration_ms: null,
        },
        {
          idx: 4,
          type: "final",
          tool_name: null,
          tool_input: null,
          tool_output: { answer: "done", artifacts: [] },
          error: null,
          duration_ms: null,
        },
      ],
      pending_actions: [],
    } as unknown as RunTrace;
    expect(traceToEvents(t).map((e) => e.event)).toEqual([
      "run_started",
      "thought",
      "action",
      "observation",
      "approval_resolved",
      "final",
    ]);
  });
});
