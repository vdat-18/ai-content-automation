export type SourceBrands = {
  brands: string[];
};

export type WorkspaceNotification = {
  notification_id: string;
  scope_type: string;
  scope_id: string;
  kind: string;
  title: string;
  detail: string;
  action_path: string | null;
  read_at: string | null;
  created_at: string;
  updated_at: string;
  payload: Record<string, unknown> | null;
};

export type WorkspaceNotificationList = {
  items: WorkspaceNotification[];
  total: number;
  unread: number;
};

export type ResearchCrawlResult = {
  final_url: string;
  platform: string;
  http_status: number;
  content_type: string;
  title: string | null;
  description: string | null;
  text: string;
  headings: Record<string, string[]>;
  metadata: Record<string, string>[];
  json_ld: unknown[];
  links: { url: string; text: string }[];
  image_urls: string[];
  video_urls: string[];
  records: ResearchCrawlRecord[];
  records_complete: boolean | null;
  raw_artifact_ref: string;
  raw_size_bytes: number;
};

export type ResearchCrawlRecord = {
  record_id: string;
  record_type: string;
  title: string | null;
  text: string;
  source_url: string | null;
  metadata: Record<string, unknown>;
  links: { url: string; text: string }[];
  image_urls: string[];
  video_urls: string[];
};

export type ResearchCrawlJob = {
  job_id: string;
  workspace_id: string;
  brand_id: string;
  project_id: string | null;
  source_url: string;
  media_mode: ResearchMediaMode;
  analysis_model_id: string | null;
  status: "queued" | "pending" | "running" | "retry_wait" | "completed" | "failed";
  command_id: string | null;
  brand_context: {
    brand_id: string;
    version: string;
    source_versions: string[];
    product_facts: string[];
    supporting_facts: string[];
  } | null;
  progress: ResearchCrawlProgress;
  result: ResearchCrawlResult | null;
  error_code: string | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
};

export type ResearchCrawlProgress = {
  phase: "queued" | "opening_browser" | "navigating" | "loading_results" | "scrolling" | "extracting" | "saving" | "capturing_media" | "classifying" | "completed" | "failed";
  discovered_records: number;
  processed_records: number;
  source_records_discovered: number;
  media_candidates: number;
  duplicate_records: number;
  media_captured: number;
  media_analysis_completed: number;
  saved_records: number;
  new_records: number;
  updated_records: number;
  unchanged_records: number;
  failed_records: number;
  accepted_records: number;
  rejected_records: number;
  auto_filtered_records: number;
  analysis_unavailable_records: number;
  image_count: number;
  video_count: number;
  scroll_count: number;
  expected_records: number | null;
  stop_reason: string | null;
  navigation_step: number;
  navigation_action: string | null;
  navigation_confidence: number | null;
};

export type ResearchCrawlList = {
  items: ResearchCrawlJob[];
  total: number;
};

export type ResearchCrawlCreateRequest = {
  workspace_id: string;
  brand_id: string;
  project_id?: string;
  source_url: string;
  media_mode: ResearchMediaMode;
};

export type ResearchMediaMode = "images" | "videos" | "images_and_videos";

export type ResearchReviewDecision = "approve" | "reject" | "review_later";

export type ResearchRecordReviewRequest = {
  decision: ResearchReviewDecision;
  reviewer_alias?: string;
  reason?: string;
};

export type ResearchReferenceProfile = {
  summary: string;
  relevance_to_project: string;
  primary_subject: string;
  content_goal: string;
  reference_types: string[];
  product_categories: string[];
  visual_style: string[];
  composition: string[];
  setting: string[];
  colors: string[];
  camera_motion: string[];
  text_treatment: string[];
  temporal_structure: string[];
  audio: string[];
  hook: string;
  message: string;
  creative_takeaways: string[];
  do_not_copy: string[];
  observed_facts: string[];
  inferences: string[];
  media_notes: string[];
  applicability_constraints: string[];
};

export type ResearchScreening = {
  status: "completed" | "failed";
  model: string;
  content_hash: string;
  config_hash: string;
  context_version: string;
  usable: boolean;
  reason_code: string;
  reason: string;
  confidence: number;
  profile: ResearchReferenceProfile | null;
  error_code: string | null;
  attempt_count: number;
  last_attempted_at: string | null;
};

export type StoredResearchRecord = Omit<ResearchCrawlRecord, "record_id"> & {
  record_key: string;
  workspace_id: string;
  brand_id: string;
  platform: string;
  external_id: string;
  status: string | null;
  advertiser: string | null;
  destination_domain: string | null;
  content_hash: string;
  first_seen_at: string;
  last_seen_at: string;
  latest_run_id: string;
  media_assets: {
    media_id: string;
    media_kind: "image" | "video";
    source_url_fingerprint: string;
    source_url: string;
    status: "available" | "failed";
    artifact_ref: string | null;
    content_type: string | null;
    sha256: string | null;
    size_bytes: number | null;
    error_code: string | null;
  }[];
  media_content_hash: string;
  classification: {
    status: "completed" | "failed";
    taxonomy_version: string;
    model: string;
    content_hash: string;
    labels: Record<string, string>;
    probabilities: Record<string, Record<string, number>>;
    confidence: Record<string, number>;
    error_code: string | null;
  } | null;
  screening_status: "kept" | "auto_filtered" | "unavailable";
  screening: ResearchScreening | null;
  review_status: "pending_review" | "approved" | "rejected";
  reviewer_alias: string | null;
  reviewed_at: string | null;
  review_reason: string | null;
};

export type ResearchRecordPage = {
  items: StoredResearchRecord[];
  total: number;
  page: number;
  page_size: number;
};

export type ResearchRecordBulkReviewResult = {
  items: StoredResearchRecord[];
  total: number;
};

export type ResearchRecordDeleteResult = {
  deleted: number;
};

export type ResearchRecordDetail = {
  record: StoredResearchRecord;
};

export type CreativeKnowledgeStatus =
  | "draft"
  | "proposed"
  | "approved"
  | "rejected"
  | "expired"
  | "conflict";

export type CreativeKnowledgeType =
  | "fact"
  | "hard_rule"
  | "team_default"
  | "practice"
  | "hypothesis"
  | "lesson"
  | "qa_check"
  | "decision"
  | "feedback";

export type CreativeKnowledgeAuthority =
  | "owner"
  | "admin"
  | "lead"
  | "team"
  | "individual"
  | "external";

export type CreativeKnowledgeStage =
  | "persona"
  | "preparation"
  | "orchestration"
  | "review"
  | "revision"
  | "learning"
  | "performance";

export type CreativeKnowledgeScope = {
  niche_id: string | null;
  brand_id: string | null;
  product_archetype: string | null;
  product_family_id: string | null;
  variant_id: string | null;
  platform: string | null;
  market: string | null;
  asset_type: string | null;
  task_type: string | null;
};

export type CreativeKnowledge = {
  knowledge_id: string;
  knowledge_type: CreativeKnowledgeType;
  title: string;
  content: string;
  scope: CreativeKnowledgeScope;
  status: CreativeKnowledgeStatus;
  authority: CreativeKnowledgeAuthority;
  source_refs: string[];
  evidence_refs: string[];
  applies_to: CreativeKnowledgeStage[];
  contributor: string | null;
  non_conclusions: string[];
  approved_by: string | null;
  approved_at: string | null;
  created_at: string;
};

export type CreativeKnowledgeList = {
  items: CreativeKnowledge[];
  total: number;
};

export type CreativeKnowledgeBootstrapResult = {
  bootstrap_id: string;
  checksum: string;
  applied: boolean;
  items: CreativeKnowledge[];
  total: number;
};

export type CreativeKnowledgeProposalRequest = {
  knowledge_id?: string;
  knowledge_type: CreativeKnowledgeType;
  title: string;
  content: string;
  scope: Partial<CreativeKnowledgeScope>;
  authority: CreativeKnowledgeAuthority;
  source_refs: string[];
  evidence_refs: string[];
  applies_to: CreativeKnowledgeStage[];
  contributor?: string;
  non_conclusions: string[];
};
