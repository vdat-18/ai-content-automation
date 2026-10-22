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
  MediaLabCatalog,
  MediaLabImageCapabilities,
  MediaLabImageOrchestrationStatus,
  MediaLabImageOrchestrationTrace,
  MediaLabImagePlanningJob,
  MediaLabImageReferenceRequest,
  MediaLabImageRun,
  MediaLabImageSource,
  MediaLabRun,
  MediaLabVideoAd,
  MediaLabVideoCapabilities,
  MediaLabVideoOrchestrationStatus,
  MediaLabVideoOrchestrationTrace,
  MediaLabVideoPlanningJob,
  MediaLabVideoSourceRequest,
  MediaLabVideoVerificationStagePlan,
  MediaLabVideoRun,
  MediaLabVideoSource,
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
  modelLabModels: (signal?: AbortSignal) => getJson<{ items: { id: string; label: string; model: string }[] }>("/api/v1/model-lab/models", signal),
  modelLabChat: (modelId: string, messages: { role: string; content: string }[], signal?: AbortSignal) => postJson<{ text: string; model: string }>("/api/v1/model-lab/chat", { model_id: modelId, messages }, signal),
  mediaLabModes: (signal?: AbortSignal) => getJson<MediaLabCatalog>("/api/v1/media-lab/modes", signal),
  uploadMediaAsset,
  createMediaLabRun: (body: object) => postJson<MediaLabRun>("/api/v1/media-lab/runs", body),
  mediaLabRun: (runId: string, signal?: AbortSignal) => getJson<MediaLabRun>(`/api/v1/media-lab/runs/${encodeURIComponent(runId)}`, signal),
  mediaLabImageCapabilities: (signal?: AbortSignal) => getJson<MediaLabImageCapabilities>("/api/v1/media-lab/image-capabilities", signal),
  mediaLabImageOrchestration: (signal?: AbortSignal) => getJson<MediaLabImageOrchestrationStatus>("/api/v1/media-lab/image-orchestration", signal),
  prepareMediaLabImage: (body: { source_run_id: string; user_request: string; sources: MediaLabImageSource[] }) => postJson<MediaLabImagePlanningJob>("/api/v1/media-lab/image-plan-jobs", body),
  mediaLabImagePlanningJob: (jobId: string, signal?: AbortSignal) => getJson<MediaLabImagePlanningJob>(`/api/v1/media-lab/image-plan-jobs/${encodeURIComponent(jobId)}`, signal),
  acceptMediaLabImageDraft: (jobId: string) => postJson<MediaLabImagePlanningJob>(`/api/v1/media-lab/image-plan-jobs/${encodeURIComponent(jobId)}/draft`),
  mediaLabImageRuns: (signal?: AbortSignal) => getJson<{ items: MediaLabImageRun[]; total: number }>("/api/v1/media-lab/image-runs", signal),
  deleteMediaLabImageRun: (runId: string) => deleteRequest(`/api/v1/media-lab/image-runs/${encodeURIComponent(runId)}`),
  createMediaLabImageRun: (body: { intent: string; prompt: string; references: MediaLabImageReferenceRequest[]; orchestration: MediaLabImageOrchestrationTrace; seed?: number; output_preset_id?: string; output_format: "png" | "jpeg" | "webp" }) => postJson<MediaLabImageRun>("/api/v1/media-lab/image-runs", body),
  mediaLabImageRun: (runId: string, signal?: AbortSignal) => getJson<MediaLabImageRun>(`/api/v1/media-lab/image-runs/${encodeURIComponent(runId)}`, signal),
  mediaLabImageComparison: (runId: string, signal?: AbortSignal) => getJson<{ root_run_id: string; candidates: MediaLabImageRun[] }>(`/api/v1/media-lab/image-runs/${encodeURIComponent(runId)}/comparison`, signal),
  reviewMediaLabImageRun: (runId: string, decision: "approved" | "rejected") => postJson<MediaLabImageRun>(`/api/v1/media-lab/image-runs/${encodeURIComponent(runId)}/review`, { decision }),
  createMediaLabVideoAd: (body: { source_run_id: string; user_request: string; brand: string; sku: string; angle: string; source_asset_ids: string[]; target_duration_seconds: number; aspect_ratio: "1:1" | "9:16" | "16:9"; candidate_count: number; cta_text?: string; logo_asset_id?: string }) => postJson<MediaLabVideoAd>("/api/v1/media-lab/video-ads", body),
  mediaLabVideoAds: (signal?: AbortSignal) => getJson<{ items: MediaLabVideoAd[]; total: number }>("/api/v1/media-lab/video-ads", signal),
  deleteMediaLabVideoAd: (jobId: string) => deleteRequest(`/api/v1/media-lab/video-ads/${encodeURIComponent(jobId)}`),
  mediaLabVideoAd: (jobId: string, signal?: AbortSignal) => getJson<MediaLabVideoAd>(`/api/v1/media-lab/video-ads/${encodeURIComponent(jobId)}`, signal),
  cancelMediaLabVideoAd: (jobId: string) => postJson<MediaLabVideoAd>(`/api/v1/media-lab/video-ads/${encodeURIComponent(jobId)}/cancel`),
  mediaLabVideoOrchestration: (signal?: AbortSignal) => getJson<MediaLabVideoOrchestrationStatus>("/api/v1/media-lab/video-orchestration", signal),
  mediaLabVideoCapabilities: (signal?: AbortSignal) => getJson<MediaLabVideoCapabilities>("/api/v1/media-lab/video-capabilities", signal),
  prepareMediaLabVideo: (body: { source_run_id: string; user_request: string; sources: MediaLabVideoSource[] }) => postJson<MediaLabVideoPlanningJob>("/api/v1/media-lab/video-plan-jobs", body),
  mediaLabVideoPlanningJob: (jobId: string, signal?: AbortSignal) => getJson<MediaLabVideoPlanningJob>(`/api/v1/media-lab/video-plan-jobs/${encodeURIComponent(jobId)}`, signal),
  mediaLabVideoRuns: (signal?: AbortSignal) => getJson<{ items: MediaLabVideoRun[]; total: number }>("/api/v1/media-lab/video-runs", signal),
  deleteMediaLabVideoRun: (runId: string) => deleteRequest(`/api/v1/media-lab/video-runs/${encodeURIComponent(runId)}`),
  createMediaLabVideoRun: (body: { intent: string; prompt: string; sources: MediaLabVideoSourceRequest[]; verification_plan: MediaLabVideoVerificationStagePlan[]; duration_seconds: number; orchestration: MediaLabVideoOrchestrationTrace; seed?: number; output_preset_id?: string; output_format: "mp4" }) => postJson<MediaLabVideoRun>("/api/v1/media-lab/video-runs", body),
  mediaLabVideoRun: (runId: string, signal?: AbortSignal) => getJson<MediaLabVideoRun>(`/api/v1/media-lab/video-runs/${encodeURIComponent(runId)}`, signal),
  mediaLabVideoComparison: (runId: string, signal?: AbortSignal) => getJson<{ root_run_id: string; candidates: MediaLabVideoRun[] }>(`/api/v1/media-lab/video-runs/${encodeURIComponent(runId)}/comparison`, signal),
  reviewMediaLabVideoRun: (runId: string, decision: "approved" | "rejected") => postJson<MediaLabVideoRun>(`/api/v1/media-lab/video-runs/${encodeURIComponent(runId)}/review`, { decision }),
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
      manifest_id: "creative_v2_2026_09_29",
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
