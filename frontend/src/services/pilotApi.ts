import { ApiError, deleteRequest, getJson, postJson } from "./http";
import type {
  AIUsageSummary,
  AIUsageEvent,
  AIUsageEventPage,
  AIUsageRunPage,
  CreativeJobDetail,
  CreativeJobSummary,
  CreativeKnowledge,
  CreativeKnowledgeBootstrapResult,
  CreativeKnowledgeList,
  CreativeKnowledgeProposalRequest,
  CreativeKnowledgeStatus,
  CreativeReviewContext,
  DashboardSnapshot,
  MarketingCreativeAutomationCapabilities,
  DataSourceStatus,
  DataSourceSyncAccepted,
  GmcRun,
  MediaAsset,
  MediaAssetKind,
  MarketingCreativeAutomationBatch,
  MarketingCreativeAutomationDetail,
  MarketingCreativeAutomationList,
  MarketingCreativeAutomationRequest,
  ProductFamilyCatalog,
  ResearchCrawlCreateRequest,
  ResearchCrawlJob,
  ResearchCrawlList,
  ResearchKeywordSuggestionList,
  ResearchRecordBulkReviewResult,
  ResearchRecordDeleteResult,
  ResearchRecordDetail,
  ResearchRecordPage,
  ShortlistedResearchReference,
  ResearchRecordReviewRequest,
  SourcePerformanceCandidates,
  WorkspaceNotification,
  WorkspaceNotificationList,
} from "../types/pilotApi";

type ListResponse<T> = { items: T[]; total: number };

function uploadMediaAsset(
  file: File,
  mediaKind: MediaAssetKind,
  onProgress?: (percent: number) => void,
): Promise<MediaAsset> {
  return new Promise((resolve, reject) => {
    const request = new XMLHttpRequest();
    request.open("POST", "/api/v1/media-assets");
    request.responseType = "json";
    request.upload.onprogress = (event) => {
      if (event.lengthComputable) {
        onProgress?.(Math.round((event.loaded / event.total) * 100));
      }
    };
    request.onerror = () => reject(new ApiError("Media upload could not reach the API", 0));
    request.onload = () => {
      const payload = request.response as MediaAsset | { detail?: string } | null;
      if (request.status >= 200 && request.status < 300 && payload && "asset_id" in payload) {
        resolve(payload);
        return;
      }
      reject(
        new ApiError(
          payload && "detail" in payload && typeof payload.detail === "string"
            ? payload.detail
            : `API returned ${request.status}`,
          request.status,
        ),
      );
    };
    const form = new FormData();
    form.set("media_kind", mediaKind);
    form.set("upload", file, file.name);
    request.send(form);
  });
}

export const pilotApi = {
  dashboard: (signal?: AbortSignal) => getJson<DashboardSnapshot>("/api/v1/dashboard/snapshot", signal),
  aiUsage: (query: string, signal?: AbortSignal) => getJson<AIUsageSummary>(`/api/v1/ai-usage/summary?${query}`, signal),
  aiUsageEvents: (query: string, signal?: AbortSignal) => getJson<AIUsageEventPage>(`/api/v1/ai-usage/events?${query}`, signal),
  aiUsageEvent: (eventId: string, signal?: AbortSignal) => getJson<AIUsageEvent>(`/api/v1/ai-usage/events/${encodeURIComponent(eventId)}`, signal),
  aiUsageRuns: (query: string, signal?: AbortSignal) => getJson<AIUsageRunPage>(`/api/v1/ai-usage/runs?${query}`, signal),
  uploadMediaAsset,
  gmcRuns: (signal?: AbortSignal) => getJson<ListResponse<GmcRun>>("/api/v1/performance/gmc/runs", signal),
  dataSources: (signal?: AbortSignal) => getJson<ListResponse<DataSourceStatus>>("/api/v1/data-sources", signal),
  researchCrawls: (signal?: AbortSignal) =>
    getJson<ResearchCrawlList>("/api/v1/marketing/research-crawls", signal),
  researchKeywordSuggestions: (brandId: string, signal?: AbortSignal) =>
    getJson<ResearchKeywordSuggestionList>(
      `/api/v1/marketing/research-crawls/keyword-suggestions?brand_id=${encodeURIComponent(brandId)}`,
      signal,
    ),
  createResearchCrawl: (body: ResearchCrawlCreateRequest) =>
    postJson<ResearchCrawlJob>("/api/v1/marketing/research-crawls", body),
  researchRecords: (query: string, signal?: AbortSignal) =>
    getJson<ResearchRecordPage>(`/api/v1/marketing/research-records?${query}`, signal),
  shortlistResearchReferences: (brandId: string, product: string, limit: number, signal?: AbortSignal) =>
    getJson<ShortlistedResearchReference[]>(
      `/api/v1/marketing/research-records/shortlist?brand_id=${encodeURIComponent(brandId)}&product=${encodeURIComponent(product)}&limit=${limit}`,
      signal,
    ),
  researchRecord: (recordKey: string, signal?: AbortSignal) =>
    getJson<ResearchRecordDetail>(`/api/v1/marketing/research-records/${encodeURIComponent(recordKey)}`, signal),
  reviewResearchRecord: (recordKey: string, body: ResearchRecordReviewRequest) =>
    postJson<ResearchRecordDetail["record"]>(
      `/api/v1/marketing/research-records/${encodeURIComponent(recordKey)}/review`,
      body,
    ),
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
  deleteResearchRecord: (recordKey: string) =>
    deleteRequest(`/api/v1/marketing/research-records/${encodeURIComponent(recordKey)}`),
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
      manifest_id: "creative_v3_2026_10_22",
    }),
  proposeCreativeKnowledge: (body: CreativeKnowledgeProposalRequest) =>
    postJson<CreativeKnowledge>("/api/v1/marketing/creative-knowledge", body),
  decideCreativeKnowledge: (
    knowledgeId: string,
    version: number,
    decision: "approved" | "rejected",
    reviewer: string,
  ) => postJson<CreativeKnowledge>(
    `/api/v1/marketing/creative-knowledge/${encodeURIComponent(knowledgeId)}/versions/${version}/decision`,
    { decision, reviewer },
  ),
  markCreativeKnowledgeConflict: (knowledgeId: string, version: number) =>
    postJson<CreativeKnowledge>(
      `/api/v1/marketing/creative-knowledge/${encodeURIComponent(knowledgeId)}/versions/${version}/conflict`,
    ),
  productFamilies: (query = "", limit = 24, signal?: AbortSignal) => {
    const params = new URLSearchParams({ limit: String(limit) });
    if (query.trim()) params.set("query", query.trim());
    return getJson<ProductFamilyCatalog>(`/api/v1/data-sources/product-families?${params}`, signal);
  },
  notifications: (unreadOnly = false, signal?: AbortSignal) =>
    getJson<WorkspaceNotificationList>(`/api/v1/notifications?unread_only=${unreadOnly}`, signal),
  markNotificationRead: (notificationId: string) =>
    postJson<WorkspaceNotification>(`/api/v1/notifications/${encodeURIComponent(notificationId)}/read`),
  createMarketingCreativeAutomation: (body: MarketingCreativeAutomationRequest) =>
    postJson<MarketingCreativeAutomationBatch>("/api/v1/marketing/creative-automations", body),
  marketingCreativeAutomations: (signal?: AbortSignal) =>
    getJson<MarketingCreativeAutomationList>("/api/v1/marketing/creative-automations", signal),
  marketingCreativeAutomationCapabilities: (signal?: AbortSignal) =>
    getJson<MarketingCreativeAutomationCapabilities>("/api/v1/marketing/creative-automations/capabilities", signal),
  marketingCreativeAutomation: (requestId: string, signal?: AbortSignal) =>
    getJson<MarketingCreativeAutomationDetail>(`/api/v1/marketing/creative-automations/${encodeURIComponent(requestId)}`, signal),
  decideMarketingCreativeAutomation: (requestId: string, body: object) =>
    postJson<MarketingCreativeAutomationDetail>(`/api/v1/marketing/creative-automations/${encodeURIComponent(requestId)}/review-decision`, body),
  generateMarketingCreativeAgain: (requestId: string, body: object) =>
    postJson<MarketingCreativeAutomationDetail>(`/api/v1/marketing/creative-automations/${encodeURIComponent(requestId)}/generate-again`, body),
  takeOverMarketingCreativeManually: (requestId: string, body: object) =>
    postJson<MarketingCreativeAutomationDetail>(`/api/v1/marketing/creative-automations/${encodeURIComponent(requestId)}/manual-takeover`, body),
  createMarketingCreativeAdsDraft: (requestId: string, body: object) =>
    postJson<MarketingCreativeAutomationDetail>(`/api/v1/marketing/creative-automations/${encodeURIComponent(requestId)}/ads-draft`, body),
  approveMarketingCreativeAdsDraft: (requestId: string, body: object) =>
    postJson<MarketingCreativeAutomationDetail>(`/api/v1/marketing/creative-automations/${encodeURIComponent(requestId)}/ads-draft/approval`, body),
  activateMarketingCreativeAdsDraft: (requestId: string, body: object) =>
    postJson<MarketingCreativeAutomationDetail>(`/api/v1/marketing/creative-automations/${encodeURIComponent(requestId)}/ads-draft/activate`, body),
  sourcePerformanceCandidates: ({ brand, limit = 20 }: { brand?: string; limit?: number } = {}, signal?: AbortSignal) => {
    const query = new URLSearchParams({ limit: String(limit) });
    if (brand) query.set("brand", brand);
    return getJson<SourcePerformanceCandidates>(`/api/v1/data-sources/performance-candidates?${query}`, signal);
  },
  syncDataSource: (sourceId: string) => postJson<DataSourceSyncAccepted>(`/api/v1/data-sources/${encodeURIComponent(sourceId)}/sync`),
  syncAllDataSources: () => postJson<DataSourceSyncAccepted>("/api/v1/data-sources/sync-all"),
  creativeIntakes: <T>(signal?: AbortSignal) => getJson<ListResponse<T>>("/api/v1/creative/intakes", signal),
  creativeJobs: (signal?: AbortSignal) => getJson<ListResponse<CreativeJobSummary>>("/api/v1/creative/jobs?decision=all", signal),
  creativeJob: (jobId: string, signal?: AbortSignal) => getJson<CreativeJobDetail>(`/api/v1/creative/jobs/${encodeURIComponent(jobId)}`, signal),
  creativeReviewContext: (webUrl: string, signal?: AbortSignal) => getJson<CreativeReviewContext>(webUrl, signal),
  creativeIntakePipeline: <T>(runId: string, signal?: AbortSignal) => getJson<T>(`/api/v1/creative/intakes/${runId}/pipeline`, signal),
  decideCreative: <T>(jobId: string, body: object) => postJson<T>(`/api/v1/creative/jobs/${jobId}/decision`, body),
  performanceDecisions: <T>(signal?: AbortSignal) => getJson<ListResponse<T>>("/api/v1/performance/decisions", signal),
  decidePerformance: <T>(runId: string, body: object) => postJson<T>(`/api/v1/performance/decisions/${runId}/decision`, body),
  creativeFeedback: <T>(signal?: AbortSignal) => getJson<ListResponse<T>>("/api/v1/creative-feedback", signal),
  decideCreativeFeedback: <T>(runId: string, body: object) => postJson<T>(`/api/v1/creative-feedback/${runId}/decision`, body),
  creativeLoops: <T>(signal?: AbortSignal) => getJson<ListResponse<T>>("/api/v1/marketing/creative-loops", signal),
  creativeLoopTimeline: <T>(runId: string) => getJson<T>(`/api/v1/marketing/creative-loops/${runId}/timeline`),
  creativeLoopCommands: <T>(runId: string) => getJson<ListResponse<T>>(`/api/v1/execution/commands?workflow_run_id=${encodeURIComponent(runId)}`),
  startCreativeLoop: <T>(inputSnapshotId: string) => postJson<T>("/api/v1/marketing/creative-loops/commands/start", { input_snapshot_id: inputSnapshotId }),
  postCreativeLoop: <T>(runId: string, path: string, body?: object) => postJson<T>(`/api/v1/marketing/creative-loops/${runId}/${path}`, body),
  retryExecutionCommand: <T>(commandId: string) => postJson<T>(`/api/v1/execution/commands/${commandId}/retry`),
  cancelExecutionCommand: <T>(commandId: string) => postJson<T>(`/api/v1/execution/commands/${commandId}/cancel`),
};
