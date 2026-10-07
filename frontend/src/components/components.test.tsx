import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { quote } from "../test/fixtures";
import type { WorkflowEvent } from "../types";
import { QuoteView } from "./QuoteView";
import { WorkflowRail } from "./WorkflowRail";
import { Confidence, Money, Provenance, StatusPill } from "./ui";

describe("shared UI", () => {
  it("labels provenance and distinguishes each kind by class", () => {
    const { container } = render(<><Provenance kind="detected" /><Provenance kind="estimated" /><Provenance kind="user_provided" /><Provenance kind={undefined} /></>);
    expect(container.querySelectorAll(".prov.detected, .prov.estimated, .prov.user_provided, .prov.unknown")).toHaveLength(4);
    expect(screen.getByText("Provided by client")).toBeInTheDocument();
    expect(screen.getByText("Unknown")).toBeInTheDocument();
  });
  it("formats rupees with Indian grouping and handles missing values", () => {
    const { container, rerender } = render(<Money value={1234567} />);
    expect(container.textContent).toBe("₹12,34,567");
    rerender(<Money value={null} />);
    expect(container.textContent).toBe("n/a");
  });
  it("shows confidence tone and status text", () => {
    const { container } = render(<><Confidence value={0.4} /><StatusPill status="awaiting_approval" /></>);
    expect(container.querySelector(".pill.bad")).toHaveTextContent("confidence 0.40");
    expect(screen.getByText("awaiting approval")).toBeInTheDocument();
  });
});

const ev = (node: string, status: WorkflowEvent["status"], summary = ""): WorkflowEvent => ({ id: node, run_id: "r", node, status, summary, detail: {}, latency_ms: 12, created_at: "" });

describe("WorkflowRail", () => {
  const steps = [{ node: "intake", label: "Intake" }, { node: "plan", label: "Scope planning" }, { node: "pricing", label: "Pricing" }, { node: "approval_wait", label: "Human approval" }];
  it("maps category planner nodes onto the generic planning step and marks states", () => {
    const { container } = render(<WorkflowRail steps={steps} labels={{}} running events={[ev("intake", "completed", "New customer"), ev("plan_kitchen_renovation", "completed", "Planned 9 lines"), ev("pricing", "failed", "No catalog")]} />);
    expect(screen.getByText("Planned 9 lines")).toBeInTheDocument();
    expect(container.querySelectorAll("li.completed")).toHaveLength(2);
    expect(container.querySelectorAll("li.failed")).toHaveLength(1);
    expect(container.querySelectorAll("li.pending")).toHaveLength(1);
  });
  it("shows an in-progress spinner only on the first pending step, and none when idle", () => {
    const { container, rerender } = render(<WorkflowRail steps={steps} labels={{}} running events={[ev("intake", "completed")]} />);
    expect(container.querySelectorAll(".spinner")).toHaveLength(1);
    rerender(<WorkflowRail steps={steps} labels={{}} running={false} events={[ev("intake", "completed")]} />);
    expect(container.querySelectorAll(".spinner")).toHaveLength(0);
  });
  it("says when a step is waiting for a person", () => {
    render(<WorkflowRail steps={steps} labels={{}} running={false} events={[ev("approval_wait", "waiting", "Waiting")]} />);
    expect(screen.getByText("waiting for a person")).toBeInTheDocument();
  });
});

describe("QuoteView", () => {
  it("renders figures, reconciles the breakdown, lists flags and the disclaimer", () => {
    render(<QuoteView quote={quote} tier="standard" />);
    expect(screen.getByText("Quote v2")).toBeInTheDocument();
    expect(screen.getByText("revises v1")).toBeInTheDocument();
    expect(screen.getAllByText("₹8,512").length).toBeGreaterThan(0);
    expect(screen.getByText("Floor area was assumed.")).toBeInTheDocument();
    expect(screen.getByText("needs review")).toBeInTheDocument();
    expect(screen.getByText("Estimate only.")).toBeInTheDocument();
    expect(screen.getByText(/computed by the pricing engine, not by the AI/)).toBeInTheDocument();
  });
  it("lets the user switch options and hides the fitted option when absent", async () => {
    const picks: string[] = [];
    render(<QuoteView quote={quote} tier="standard" onTier={(t) => picks.push(t)} />);
    expect(screen.queryByText("Fitted to your budget")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Premium/ }));
    expect(picks).toEqual(["premium"]);
    expect(screen.getByRole("button", { name: /Standard/ })).toHaveAttribute("aria-pressed", "true");
  });
  it("can collapse the line items", async () => {
    render(<QuoteView quote={quote} tier="standard" />);
    expect(screen.getByText("kitchen_cabinets item")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Hide lines" }));
    expect(screen.queryByText("kitchen_cabinets item")).not.toBeInTheDocument();
  });
});
