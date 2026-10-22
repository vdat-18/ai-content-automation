import type { DashboardApproval } from "../types/pilotApi";

export const dashboardStreamLabels: Record<DashboardApproval["workstream"], string> = {
  creative: "Content / Creative",
  performance: "Performance",
};

export const decisionPrompt = (type: string) => ({
  creative_loop_demand: "Approve this experiment plan?",
  creative_loop_creative: "Approve this exact Creative set?",
  creative_loop_lesson: "Approve this learning for the next cycle?",
  creative: "Approve this exact Creative set?",
  performance_decision: "Approve this Performance recommendation?",
  creative_feedback: "Approve this learning for the next cycle?",
}[type] ?? "Review this decision?");

export const businessStage = (stage: string) => ({
  plan_review: "Plan ready for review",
  output_review: "Output ready for review",
  waiting_results: "Waiting for results",
  learning_review: "Learning ready for review",
  needs_attention: "Needs attention",
  completed: "Completed",
  working: "AI is working",
}[stage] ?? "AI is working");
