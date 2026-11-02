import { getJson, postJson } from "./http";
import type {
  CreativeKnowledge,
  CreativeKnowledgeBootstrapResult,
  CreativeKnowledgeList,
  CreativeKnowledgeProposalRequest,
  CreativeKnowledgeStatus,
  ResearchCrawlCreateRequest,
  ResearchCrawlJob,
  ResearchCrawlList,
  ResearchRecordBulkReviewResult,
  ResearchRecordDeleteResult,
  ResearchRecordDetail,
  ResearchRecordPage,
  ResearchRecordReviewRequest,
  SourceBrands,
  WorkspaceNotification,
  WorkspaceNotificationList,
} from "../types/pilotApi";

export const pilotApi = {
  researchCrawls: (signal?: AbortSignal) =>
    getJson<ResearchCrawlList>("/api/v1/marketing/research-crawls", signal),
  createResearchCrawl: (body: ResearchCrawlCreateRequest) =>
    postJson<ResearchCrawlJob>("/api/v1/marketing/research-crawls", body),
  researchRecords: (query: string, signal?: AbortSignal) =>
    getJson<ResearchRecordPage>(`/api/v1/marketing/research-records?${query}`, signal),
  reanalyzeResearchRecord: (recordKey: string) =>
    postJson<ResearchRecordDetail["record"]>(
      `/api/v1/marketing/research-records/${encodeURIComponent(recordKey)}/reanalyze`,
      {},
    ),
  reviewResearchRecords: (recordKeys: string[], body: ResearchRecordReviewRequest) =>
    postJson<ResearchRecordBulkReviewResult>("/api/v1/marketing/research-records/review", {
      ...body,
      record_keys: recordKeys,
    }),
  deleteResearchRecords: (recordKeys: string[]) =>
    postJson<ResearchRecordDeleteResult>("/api/v1/marketing/research-records/delete", {
      record_keys: recordKeys,
    }),
  creativeKnowledge: (status?: CreativeKnowledgeStatus, signal?: AbortSignal) => {
    const query = status ? `?status=${encodeURIComponent(status)}` : "";
    return getJson<CreativeKnowledgeList>(`/api/v1/marketing/creative-knowledge${query}`, signal);
  },
  bootstrapCreativeKnowledge: (contributor: string) =>
    postJson<CreativeKnowledgeBootstrapResult>("/api/v1/marketing/creative-knowledge/bootstrap", {
      contributor,
      manifest_id: "creative",
    }),
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
  sourceBrands: (signal?: AbortSignal) => getJson<SourceBrands>("/api/v1/data-sources/brands", signal),
  retryExecutionCommand: <T>(commandId: string) => postJson<T>(`/api/v1/execution/commands/${commandId}/retry`),
  cancelExecutionCommand: <T>(commandId: string) => postJson<T>(`/api/v1/execution/commands/${commandId}/cancel`),
};
