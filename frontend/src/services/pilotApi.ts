import { getJson, postJson } from "./http";
import type {
  CreativeKnowledge,
  CreativeKnowledgeBootstrapResult,
  CreativeKnowledgeList,
  CreativeKnowledgeProposalRequest,
  CreativeKnowledgeStatus,
  WorkspaceNotification,
  WorkspaceNotificationList,
} from "../types/pilotApi";

export const pilotApi = {
  creativeKnowledge: (status?: CreativeKnowledgeStatus, signal?: AbortSignal) => {
    const query = status ? `?status=${encodeURIComponent(status)}` : "";
    return getJson<CreativeKnowledgeList>(`/api/v1/marketing/creative-knowledge${query}`, signal);
  },
  bootstrapCreativeKnowledge: (contributor: string, manifestId = "creative") =>
    postJson<CreativeKnowledgeBootstrapResult>("/api/v1/marketing/creative-knowledge/bootstrap", {
      contributor,
      manifest_id: manifestId,
    }),
  retireCreativeKnowledge: (knowledgeId: string) =>
    postJson<CreativeKnowledge>(
      `/api/v1/marketing/creative-knowledge/${encodeURIComponent(knowledgeId)}/retire`,
    ),
  proposeCreativeKnowledge: (body: CreativeKnowledgeProposalRequest) =>
    postJson<CreativeKnowledge>("/api/v1/marketing/creative-knowledge", body),
  decideCreativeKnowledge: (
    knowledgeId: string,
    decision: "approved" | "rejected",
    reviewer: string,
  ) => postJson<CreativeKnowledge>(
    `/api/v1/marketing/creative-knowledge/${encodeURIComponent(knowledgeId)}/decision`,
    { decision, reviewer },
  ),
  markCreativeKnowledgeConflict: (knowledgeId: string) =>
    postJson<CreativeKnowledge>(
      `/api/v1/marketing/creative-knowledge/${encodeURIComponent(knowledgeId)}/conflict`,
    ),
  notifications: (unreadOnly = false, signal?: AbortSignal) =>
    getJson<WorkspaceNotificationList>(`/api/v1/notifications?unread_only=${unreadOnly}`, signal),
  markNotificationRead: (notificationId: string) =>
    postJson<WorkspaceNotification>(`/api/v1/notifications/${encodeURIComponent(notificationId)}/read`),
};
