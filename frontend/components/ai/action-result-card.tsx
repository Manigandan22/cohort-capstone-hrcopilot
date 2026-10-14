"use client";

import { CheckCircle2, CircleSlash, ShieldQuestion } from "lucide-react";

import { Button } from "@/components/ui/button";
import type { AIActionResult } from "@/lib/api";

const TOOL_LABELS: Record<string, string> = {
  apply_leave: "Apply for leave",
  approve_leave: "Approve leave",
  reject_leave: "Reject leave",
  create_ticket: "Create ticket",
  assign_ticket: "Assign ticket",
  update_ticket_status: "Update ticket status",
  create_announcement: "Create announcement",
  assign_employee_to_project: "Assign to project",
  create_project: "Create project",
};

export function ActionResultCard({
  result,
  busy,
  onDecision,
}: {
  result: AIActionResult;
  busy: boolean;
  onDecision: (approve: boolean) => void;
}) {
  if (result.status === "ANSWERED") return null;
  const label = result.tool ? TOOL_LABELS[result.tool] ?? result.tool : "Action";

  if (result.status === "CONFIRMATION_REQUIRED") {
    return (
      <div className="mt-3 rounded-lg border border-amber-300 bg-amber-50 p-3">
        <div className="flex items-center gap-2 text-sm font-medium text-amber-900">
          <ShieldQuestion className="h-4 w-4" /> Confirm: {label}
        </div>
        <p className="mt-1 text-xs text-amber-800">Nothing has been changed yet. This action runs only after you confirm.</p>
        <div className="mt-3 flex gap-2">
          <Button size="sm" disabled={busy} onClick={() => onDecision(true)}>
            {busy ? "Working..." : "Confirm"}
          </Button>
          <Button size="sm" variant="outline" disabled={busy} onClick={() => onDecision(false)}>
            Cancel
          </Button>
        </div>
      </div>
    );
  }

  const completed = result.status === "COMPLETED";
  return (
    <div
      className={`mt-3 flex items-center gap-2 rounded-lg border p-3 text-sm ${
        completed ? "border-emerald-300 bg-emerald-50 text-emerald-900" : "border-slate-200 bg-slate-50 text-slate-700"
      }`}
    >
      {completed ? <CheckCircle2 className="h-4 w-4" /> : <CircleSlash className="h-4 w-4" />}
      <span className="font-medium">{label}</span>
      <span>· {completed ? "Done" : "Cancelled"}</span>
    </div>
  );
}
