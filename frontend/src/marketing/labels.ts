import type { DashboardApproval } from "../types/pilotApi";

export const dashboardStreamLabels: Record<DashboardApproval["workstream"], string> = {
  creative: "Content / Creative",
  performance: "Performance",
};

export const decisionPrompt = (type: string) => ({
  creative: "Approve this exact Creative set?",
}[type] ?? "Review this decision?");

export const businessStage = (stage: string) => ({
  plan_review: "Plan ready for review",
  output_review: "Output ready for review",
  needs_attention: "Needs attention",
  completed: "Completed",
  working: "AI is working",
}[stage] ?? "AI is working");
