export type DashboardApproval = {
  approval_id: string;
  workstream: "creative" | "performance";
  kind: string;
  title: string;
  detail: string;
  status: "pending";
  brand_id: string | null;
  entity_id: string;
  version_ref: string | null;
  created_at: string;
  action_path: string;
  decision_type: string;
};

export type DashboardWorkflow = {
  workflow_id: string;
  workstream: DashboardApproval["workstream"];
  title: string;
  detail: string;
  state: string;
  status: "running" | "waiting" | "completed" | "failed";
  brand_id: string | null;
  entity_id: string;
  updated_at: string;
  action_path: string;
  business_stage: string;
};

export type DashboardException = {
  exception_id: string;
  workstream: DashboardApproval["workstream"];
  title: string;
  detail: string;
  queue: "operations" | "policy";
  severity: "warning" | "blocking";
  status: "open";
  brand_id: string | null;
  entity_id: string;
  evidence_refs: string[];
  created_at: string;
  action_path: string;
};

export type DashboardSnapshot = {
  summary: {
    pending_approvals: number;
    open_workflows: number;
    active_commands: number;
    open_exceptions: number;
    failed_commands: number;
  };
  approvals: DashboardApproval[];
  workflows: DashboardWorkflow[];
  exceptions: DashboardException[];
  generated_at: string;
};

export type AIUsageBreakdown = {
  key: string;
  attempts: number;
  succeeded: number;
  failed: number;
  incomplete: number;
  request_count: number;
  input_tokens: number;
  output_tokens: number;
  output_count: number;
  output_bytes: number;
  token_reported_attempts: number;
  duration_reported_attempts: number;
  total_duration_ms: number;
  linked_attempts: number;
  unpriced_attempts: number;
  costs: AIUsageCost[];
};

export type AIUsageCost = { currency: string; amount: string };

export type AIUsageEvent = {
  event_id: string;
  workstream: string;
  operation: string;
  backend: string;
  model: string;
  model_revision: string | null;
  status: "started" | "succeeded" | "failed";
  request_count: number;
  input_tokens: number | null;
  output_tokens: number | null;
  output_count: number | null;
  output_bytes: number | null;
  cost_amount: string | null;
  cost_currency: string | null;
  error_code: string | null;
  source_run_id: string | null;
  workflow_run_id: string | null;
  job_id: string | null;
  version_id: string | null;
  brand_id: string | null;
  batch_id: string | null;
  run_id: string | null;
  parent_event_id: string | null;
  attempt_number: number | null;
  provider_request_id: string | null;
  started_at: string;
  completed_at: string | null;
  duration_ms: number | null;
};

export type AIUsageEventPage = {
  items: AIUsageEvent[];
  total: number;
  limit: number;
  offset: number;
};

export type AIUsageRun = {
  run_id: string;
  batch_id: string | null;
  brand_id: string | null;
  status: "running" | "attention" | "failed" | "succeeded";
  attempts: number;
  succeeded: number;
  failed: number;
  incomplete: number;
  input_tokens: number;
  output_tokens: number;
  output_count: number;
  output_bytes: number;
  total_duration_ms: number;
  costs: AIUsageCost[];
  models: string[];
  operations: string[];
  started_at: string;
  completed_at: string | null;
};

export type AIUsageRunPage = {
  items: AIUsageRun[];
  total: number;
  limit: number;
  offset: number;
};

export type AIUsageSummary = Omit<AIUsageBreakdown, "key"> & {
  by_model: AIUsageBreakdown[];
  by_workstream: AIUsageBreakdown[];
  by_operation: AIUsageBreakdown[];
  by_backend: AIUsageBreakdown[];
  by_day: AIUsageBreakdown[];
  p50_duration_ms: number | null;
  p95_duration_ms: number | null;
  recent_failures: AIUsageEvent[];
  from_time: string;
  to_time: string;
};

export type GmcRun = {
  run_id: string;
  source_run_id: string;
  brand_id: string;
  store_id: string;
  status: string;
  source_ref: string;
  source_checksum_sha256: string;
  source_size_bytes: number;
  schema_version: string;
  mapping_version: string;
  total_rows: number;
  accepted_rows: number;
  rejected_rows: number;
  matched_rows: number;
  gmc_only_rows: number;
  conflicting_rows: number;
  duplicate_rows: number;
  created_at: string;
  issues: { code: string; severity: string; detail: string; source_ref: string | null }[];
};

export type DataSourceStatus = {
  source_id: string;
  provider: "shopify" | "lark" | "google" | "meta_ads" | "google_ads" | "pinterest_ads" | "google_merchant" | "klaviyo";
  name: string;
  category: string;
  purpose: string;
  status: "healthy" | "error" | "not_synced";
  last_sync_at: string | null;
  record_count: number;
  changed: boolean | null;
  snapshot_id: string | null;
  artifact_ref: string | null;
  error_code: string | null;
  error_message: string | null;
  credential_expires_at?: string | null;
  sync_command_id: string | null;
  sync_status: "pending" | "running" | "retry_wait" | "cancel_requested" | null;
};

export type DataSourceSyncAccepted = {
  command_id: string;
  source_ids: string[];
  status: string;
  created: boolean;
};

export type MediaLabMode = "text_to_image" | "product_to_image" | "multi_reference_to_image" | "revise_image" | "text_to_video" | "image_to_video" | "reference_video_to_video";

export type MediaLabModeInfo = {
  id: MediaLabMode;
  label: string;
  model: string;
  media_type: "image" | "video";
  description: string;
  input_count: number;
  input_kind: "image" | "video" | null;
  supports_resolution: boolean;
  supports_duration: boolean;
  available: boolean;
};

export type MediaLabCatalog = {
  enabled: boolean;
  items: MediaLabModeInfo[];
  notice: string | null;
};

export type MediaAssetKind = "image" | "video";

export type MediaAsset = {
  asset_id: string;
  media_kind: MediaAssetKind;
  state: "processing" | "ready" | "failed";
  origin: "upload" | "media_lab_image_output" | "media_lab_video_output";
  checksum_sha256: string;
  size_bytes: number;
  detected_content_type: string | null;
  working_content_type: string | null;
  preview_content_type: string | null;
  width: number | null;
  height: number | null;
  duration_milliseconds: number | null;
  codec: string | null;
  source_run_id: string | null;
  parent_asset_ids: string[];
  preprocessing_version: string;
  transform_metadata: Record<string, string>;
  error_code: string | null;
  preview_url: string;
  original_url: string;
};

export type MediaLabRun = {
  run_id: string;
  mode: MediaLabMode;
  status: "queued" | "running" | "succeeded" | "failed" | "cancelled";
  model: string;
  media_type: "image" | "video";
  seed: number;
  width: number | null;
  height: number | null;
  duration_seconds: number | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  output_url: string | null;
  error_code: string | null;
};

export type MediaLabImageIntent = "create_from_text" | "create_from_references" | "edit_existing";
export type MediaLabImageRole = "product_source" | "style_reference" | "previous_output";
export type MediaLabImageOutputFormat = "png" | "jpeg" | "webp";
export type MediaLabImageSource = { kind: "media_asset"; asset_id: string };

export type MediaLabImageReferenceRequest = {
  role: MediaLabImageRole;
  priority: number;
  must_preserve: string[];
  allowed_changes: string[];
  identity_group: string | null;
  source: MediaLabImageSource;
};

export type MediaLabImageOrchestrationStatus = {
  enabled: boolean;
  model: string | null;
  max_image_sources: number;
  quality_review_enabled: boolean;
  max_regenerations: number;
  notice: string | null;
};

export type MediaLabImageOrchestrationTrace = {
  user_request: string;
  capability_id: string;
  summary: string;
  planner_model: string;
  planner_prompt_version: string;
  planner_prompt_hash: string;
  planner_config_hash: string;
  plan_hash: string;
};

export type MediaLabImagePlanReference = {
  source_index: number;
  role: MediaLabImageRole;
  priority: number;
  must_preserve: string[];
  allowed_changes: string[];
  identity_group: string | null;
};

export type MediaLabImagePlan = {
  state: "ready" | "needs_input";
  summary: string;
  questions: string[];
  uncertainties: string[];
  capability_id: string | null;
  intent: MediaLabImageIntent | null;
  production_prompt: string | null;
  references: MediaLabImagePlanReference[];
  orchestration: MediaLabImageOrchestrationTrace;
};

export type MediaLabImagePlanningJob = {
  job_id: string;
  source_run_id: string;
  state: "planning" | "ready" | "needs_input" | "failed";
  source_asset_ids: string[];
  user_request: string;
  plan: MediaLabImagePlan | null;
  error_code: string | null;
  created_at: string;
  updated_at: string;
};

export type MediaLabImageCapability = {
  capability_id: string;
  intent: MediaLabImageIntent;
  label: string;
  description: string;
  required_roles: MediaLabImageRole[];
  minimum_style_reference_count: number;
  maximum_style_reference_count: number;
  supports_output_size: boolean;
  candidate_count: number;
  output_presets: { preset_id: string; label: string; aspect_ratio: string; width: number; height: number }[];
  supported_output_formats: MediaLabImageOutputFormat[];
  available: boolean;
};

export type MediaLabImageCapabilities = {
  enabled: boolean;
  items: MediaLabImageCapability[];
  notice: string | null;
};

export type MediaLabImageReference = {
  reference_id: string;
  role: MediaLabImageRole;
  priority: number;
  must_preserve: string[];
  allowed_changes: string[];
  source_origin: "upload" | "media_lab_output";
  source_checksum_sha256: string;
  source_run_id: string | null;
  asset_id: string | null;
  identity_group: string | null;
  preview_url: string | null;
  url: string;
};

export type MediaLabImageQualityIssue = {
  category: string;
  severity: "minor" | "major" | "critical";
  description: string;
};

export type MediaLabImageQualityReview = {
  decision: "pass" | "regenerate" | "human_review";
  summary: string;
  issues: MediaLabImageQualityIssue[];
  repair_instructions: string[];
  uncertainties: string[];
  reviewer_model: string;
  reviewer_prompt_version: string;
  reviewer_prompt_hash: string;
  reviewer_config_hash: string;
  review_hash: string;
  repair_prompt: string | null;
  repair_prompt_version: string | null;
  repair_prompt_hash: string | null;
};

export type MediaLabImageRetryAttempt = {
  run_id: string;
  seed: number | null;
  production_prompt: string;
  output_asset_id: string | null;
  output_checksum_sha256: string | null;
  review_decision: "pass" | "regenerate" | "human_review" | null;
  review_summary: string | null;
  repair_instructions: string[];
  repair_prompt: string | null;
};

export type MediaLabImageRetryMemory = {
  root_run_id: string;
  attempts: MediaLabImageRetryAttempt[];
};

export type MediaLabImageRun = {
  run_id: string;
  intent: MediaLabImageIntent;
  production_prompt: string;
  generation_state: "queued" | "running" | "succeeded" | "failed" | "interrupted";
  review_state: "not_ready" | "awaiting_human_review" | "approved" | "rejected";
  quality_review_state:
    | "not_requested"
    | "reviewing"
    | "passed"
    | "regenerating"
    | "requires_human_review"
    | "unavailable";
  quality_review: MediaLabImageQualityReview | null;
  quality_review_error_code: string | null;
  regenerated_run_id: string | null;
  retry_of_run_id: string | null;
  regeneration_count: number;
  model: string | null;
  checkpoint_observation: string | null;
  graph_template_hash: string | null;
  seed: number | null;
  references: MediaLabImageReference[];
  width: number | null;
  height: number | null;
  candidate_count: number;
  output_preset_id: string | null;
  aspect_ratio: string | null;
  output_format: MediaLabImageOutputFormat;
  parent_run_id: string | null;
  orchestration: MediaLabImageOrchestrationTrace | null;
  provider_job_id: string | null;
  queue_position: number | null;
  queue_wait_milliseconds: number | null;
  provider_delay_milliseconds: number | null;
  provider_execution_milliseconds: number | null;
  output_asset_id: string | null;
  output_checksum_sha256: string | null;
  output_url: string | null;
  master_output_url: string | null;
  retry_memory: MediaLabImageRetryMemory | null;
  error_code: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  reviewed_at: string | null;
};
export type MediaLabVideoIntent = "create_from_text" | "create_from_images";
export type MediaLabVideoOutputFormat = "mp4";
export type MediaLabVideoRole =
  | "product"
  | "style"
  | "background"
  | "character"
  | "keyframe"
  | "storyboard";
export type MediaLabVideoSourceUsage = "generation" | "verification" | "both";
export type MediaLabVideoVerificationStageName =
  | "tracking"
  | "product_fidelity"
  | "temporal_quality";
export type MediaLabVideoSource = { kind: "media_asset"; asset_id: string };

export type MediaLabVideoSourceRequest = {
  source_index: number;
  role: MediaLabVideoRole;
  usage: MediaLabVideoSourceUsage;
  priority: number;
  must_preserve: string[];
  allowed_changes: string[];
  identity_group: string | null;
  is_primary_identity: boolean;
  source: MediaLabVideoSource;
};

export type MediaLabVideoVerificationStagePlan = {
  stage: MediaLabVideoVerificationStageName;
  reason: string;
};

export type MediaLabVideoOrchestrationStatus = {
  enabled: boolean;
  model: string | null;
  max_image_sources: number;
  max_generation_image_sources: number;
  quality_review_enabled: boolean;
  max_regenerations: number;
  notice: string | null;
};

export type MediaLabVideoOrchestrationTrace = {
  user_request: string;
  capability_id: string;
  summary: string;
  planner_model: string;
  planner_prompt_version: string;
  planner_prompt_hash: string;
  planner_config_hash: string;
  plan_hash: string;
};

export type MediaLabVideoPlanSource = {
  source_index: number;
  role: MediaLabVideoRole;
  usage: MediaLabVideoSourceUsage;
  priority: number;
  must_preserve: string[];
  allowed_changes: string[];
  identity_group: string | null;
  is_primary_identity: boolean;
};

export type MediaLabVideoPlan = {
  state: "ready" | "needs_input";
  summary: string;
  questions: string[];
  uncertainties: string[];
  capability_id: string | null;
  intent: MediaLabVideoIntent | null;
  production_prompt: string | null;
  sources: MediaLabVideoPlanSource[];
  verification_plan: MediaLabVideoVerificationStagePlan[];
  orchestration: MediaLabVideoOrchestrationTrace;
};

export type MediaLabVideoPlanningJob = {
  job_id: string;
  source_run_id: string;
  state: "planning" | "ready" | "needs_input" | "failed";
  source_asset_ids: string[];
  user_request: string;
  plan: MediaLabVideoPlan | null;
  error_code: string | null;
  created_at: string;
  updated_at: string;
};

export type MediaLabVideoCapability = {
  capability_id: string;
  intent: MediaLabVideoIntent;
  label: string;
  description: string;
  minimum_generation_images: number;
  maximum_generation_images: number;
  supported_duration_seconds: number[];
  candidate_count: number;
  output_presets: { preset_id: string; label: string; aspect_ratio: string; megapixels: number }[];
  supported_output_formats: MediaLabVideoOutputFormat[];
  default_output_preset_id: string | null;
  available: boolean;
};

export type MediaLabVideoCapabilities = {
  enabled: boolean;
  items: MediaLabVideoCapability[];
  notice: string | null;
};

export type MediaLabVideoResolvedSource = {
  source_id: string;
  source_index: number;
  role: MediaLabVideoRole;
  usage: MediaLabVideoSourceUsage;
  priority: number;
  must_preserve: string[];
  allowed_changes: string[];
  identity_group: string | null;
  is_primary_identity: boolean;
  source_origin: "upload" | "media_lab_image_output";
  source_checksum_sha256: string;
  source_run_id: string | null;
  asset_id: string | null;
  preview_url: string | null;
  url: string;
};

export type MediaLabVideoQualityIssue = {
  category: string;
  severity: "minor" | "major" | "critical";
  description: string;
};

export type MediaLabVideoReviewFrame = {
  label: string;
  timestamp_milliseconds: number;
  checksum_sha256: string;
  url: string;
};

export type MediaLabVideoVerificationObservation = {
  observation_id: string;
  stage: string;
  category: string;
  status: "pass" | "fail" | "unknown" | "unavailable";
  severity: "minor" | "major" | "critical";
  description: string;
  confidence: number | null;
  start_timestamp_milliseconds: number | null;
  end_timestamp_milliseconds: number | null;
  evidence_refs: string[];
};

export type MediaLabVideoVerificationStage = {
  stage: string;
  status: "pass" | "fail" | "unknown" | "unavailable";
  model: string;
  model_version: string;
  observations: MediaLabVideoVerificationObservation[];
  metadata: Record<string, string>;
};

export type MediaLabVideoVerification = {
  status: "pass" | "fail" | "unknown" | "unavailable";
  verifier_version: string;
  config_hash: string;
  request_hash: string;
  stages: MediaLabVideoVerificationStage[];
  suspicious_timestamps_milliseconds: number[];
  uncertainties: string[];
  report_hash: string;
};

export type MediaLabVideoQualityReview = {
  decision: "pass" | "regenerate" | "human_review";
  summary: string;
  issues: MediaLabVideoQualityIssue[];
  repair_instructions: string[];
  uncertainties: string[];
  reviewer_model: string;
  reviewer_prompt_version: string;
  reviewer_prompt_hash: string;
  reviewer_config_hash: string;
  review_hash: string;
  sampled_frames: MediaLabVideoReviewFrame[];
  temporal_sampling_rate_fps: number | null;
  temporal_duration_milliseconds: number | null;
  repair_prompt: string | null;
  repair_prompt_version: string | null;
  repair_prompt_hash: string | null;
  verification: MediaLabVideoVerification | null;
};

export type MediaLabVideoRetryAttempt = {
  run_id: string;
  seed: number | null;
  production_prompt: string;
  output_asset_id: string | null;
  output_checksum_sha256: string | null;
  duration_seconds: number;
  output_preset_id: string | null;
  review_decision: "pass" | "regenerate" | "human_review" | null;
  review_summary: string | null;
  repair_instructions: string[];
  repair_prompt: string | null;
  verifier_status: "pass" | "fail" | "unknown" | "unavailable" | null;
  suspicious_timestamps_milliseconds: number[];
};

export type MediaLabVideoRetryMemory = {
  root_run_id: string;
  attempts: MediaLabVideoRetryAttempt[];
};

export type MediaLabVideoRun = {
  run_id: string;
  intent: MediaLabVideoIntent;
  production_prompt: string;
  generation_state: "queued" | "running" | "succeeded" | "failed" | "interrupted";
  review_state: "not_ready" | "awaiting_human_review" | "approved" | "rejected";
  quality_review_state:
    | "not_requested"
    | "reviewing"
    | "passed"
    | "regenerating"
    | "requires_human_review"
    | "unavailable";
  quality_review: MediaLabVideoQualityReview | null;
  quality_review_error_code: string | null;
  verification_state: "not_requested" | "verifying" | "verified" | "failed";
  verification: MediaLabVideoVerification | null;
  verification_frames: MediaLabVideoReviewFrame[];
  verification_error_code: string | null;
  regenerated_run_id: string | null;
  retry_of_run_id: string | null;
  regeneration_count: number;
  model: string | null;
  checkpoint_observation: string | null;
  graph_template_hash: string | null;
  seed: number | null;
  sources: MediaLabVideoResolvedSource[];
  verification_plan: MediaLabVideoVerificationStagePlan[];
  duration_seconds: number;
  candidate_count: number;
  output_preset_id: string | null;
  aspect_ratio: string | null;
  megapixels: number | null;
  output_format: MediaLabVideoOutputFormat;
  actual_width: number | null;
  actual_height: number | null;
  actual_duration_milliseconds: number | null;
  orchestration: MediaLabVideoOrchestrationTrace | null;
  provider_job_id: string | null;
  queue_position: number | null;
  queue_wait_milliseconds: number | null;
  provider_delay_milliseconds: number | null;
  provider_execution_milliseconds: number | null;
  output_asset_id: string | null;
  output_checksum_sha256: string | null;
  output_url: string | null;
  retry_memory: MediaLabVideoRetryMemory | null;
  error_code: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  reviewed_at: string | null;
};
export type MediaLabVideoAdState =
  | "planning"
  | "needs_input"
  | "generating_shots"
  | "selecting_segments"
  | "assembling"
  | "completed"
  | "failed"
  | "cancel_requested"
  | "cancelled";

export type MediaLabVideoAdSource = {
  source_index: number;
  role: MediaLabVideoRole;
  usage: MediaLabVideoSourceUsage;
  priority: number;
  must_preserve: string[];
  allowed_changes: string[];
  identity_group: string | null;
  is_primary_identity: boolean;
};

export type MediaLabVideoAdShot = {
  shot_id: string;
  purpose: string;
  prompt: string;
  intent: MediaLabVideoIntent;
  source_indexes: number[];
  generation_duration_seconds: number;
  usable_duration_seconds: number;
  on_screen_text: string | null;
};

export type MediaLabVideoAdCandidate = {
  shot_id: string;
  candidate_index: number;
  run_id: string;
  seed: number | null;
};

export type MediaLabVideoAdSegment = {
  shot_id: string;
  candidate_index: number;
  run_id: string;
  trim_start_seconds: number;
  trim_end_seconds: number;
  score: number;
  observations: string[];
};

export type MediaLabVideoAd = {
  job_id: string;
  source_run_id: string;
  state: MediaLabVideoAdState;
  user_request: string;
  brand: string;
  sku: string;
  angle: string;
  target_duration_seconds: number;
  aspect_ratio: string;
  candidate_count: number;
  cta_text: string | null;
  summary: string | null;
  planner_prompt_version: string | null;
  plan_hash: string | null;
  questions: string[];
  uncertainties: string[];
  sources: MediaLabVideoAdSource[];
  shots: MediaLabVideoAdShot[];
  candidates: MediaLabVideoAdCandidate[];
  selected_segments: MediaLabVideoAdSegment[];
  output_asset_id: string | null;
  output_checksum_sha256: string | null;
  output_url: string | null;
  actual_width: number | null;
  actual_height: number | null;
  actual_duration_milliseconds: number | null;
  error_code: string | null;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
};

export type ProductPerformanceCandidate = {
  source_id: string;
  snapshot_id: string;
  brand: string | null;
  product_item_id: string;
  sku_id: string | null;
  sku_mapping_status: string;
  window_start: string | null;
  window_end: string | null;
  currency: string | null;
  record_count: number;
  impressions: string | null;
  clicks: string | null;
  spend: string | null;
  conversions: string | null;
  conversion_value: string | null;
  roas: string | null;
};

export type CreativePerformanceCandidate = {
  source_id: string;
  snapshot_id: string;
  brand: string | null;
  ad_id: string;
  ad_name: string | null;
  creative_lineage_status: string;
  window_label: string;
  currency: string | null;
  impressions: string | null;
  clicks: string | null;
  spend: string | null;
  purchases: string | null;
  add_to_cart: string | null;
  purchase_conversion_value: string | null;
  roas: string | null;
  cost_per_atc: string | null;
};

export type SourcePerformanceCandidates = {
  brands: string[];
  product_total: number;
  mapped_sku_total: number;
  creative_total: number;
  unlinked_creative_total: number;
  products: ProductPerformanceCandidate[];
  creatives: CreativePerformanceCandidate[];
};

export type CreativeJobSummary = {
  job_id: string;
  source_run_id: string | null;
  status: string;
  idea_id: string | null;
  context_ref: string | null;
  total_cost: string | null;
  version_count: number;
  latest_version: string | null;
  latest_score: string | null;
  pending_approval: boolean;
  display_title: string;
  thumbnail_web_url: string | null;
};

export type CreativeJobVersion = {
  version_id: string;
  attempt_number: number;
  creative_set_id: string | null;
  variation_id: string | null;
  variation_attempt_number: number | null;
  artifact_url: string | null;
  artifact_path: string | null;
  artifact_web_url: string | null;
  review_context_web_url: string | null;
  cost: string | null;
  input_ref: string;
  input_hash: string | null;
  prompt_version: string | null;
  rubric_version: string | null;
  policy_version: string | null;
  workflow_version: string | null;
  generator_version: string | null;
  qa_passed: boolean | null;
  qa_score: string | null;
  qa_issues: string[];
  qa_warnings: string[];
  qa_feedback: string | null;
  qa_outcome: string | null;
  qa_retryable: boolean;
  qa_requires_human_review: boolean;
  qa_repair_actions: string[];
  qa_evidence_refs: string[];
  qa_reviewer_version: string | null;
  created_at: string;
};

export type CreativeJobDetail = {
  job_id: string;
  source_run_id: string | null;
  status: string;
  context_ref: string | null;
  idea_id: string | null;
  brief_ref: string | null;
  brief_artifact_id: string | null;
  brief_web_url: string | null;
  preparation_hash: string | null;
  creative_set_id: string | null;
  total_cost: string | null;
  versions: CreativeJobVersion[];
  card: {
    work_item_id: string;
    candidate_summary: string;
    final_version_ref: string;
    final_version_refs: string[];
    thumbnail_ref: string | null;
    thumbnail_web_url: string | null;
    warnings: string[];
    score: string | null;
    evidence_refs: string[];
    decision: string | null;
    reviewer_id: string | null;
    decided_at: string | null;
    reason: string | null;
  } | null;
  audit_count: number;
  lineage: {
    entry_type: string;
    ref: string;
    parent_ref: string | null;
    details: Record<string, unknown>;
    recorded_at: string;
  }[];
};

export type CreativeReviewContext = {
  brand: string;
  sku: string;
  objective: string;
  idea_id: string;
  heading: string;
  subtext: string | null;
  visual_direction: string;
  variation_key: string | null;
  evidence_refs: string[];
  awareness_stage: string | null;
  angle: string | null;
  offer: string | null;
  production_level: string | null;
  output_spec: { width: number; height: number; file_format: string; aspect_ratio: string | null };
  output_stage: "visual_only" | "rendered_static";
  assets: { role: string; index: number; sha256: string; web_url: string }[];
  product_preservation?: {
    source_checksum: string;
    mask_web_url: string;
    cutout_web_url: string;
    model: string;
    model_version: string;
    bounding_box: number[];
  };
  raw_background?: {
    sha256: string;
    web_url: string;
    width: number;
    height: number;
    file_format: string;
  };
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

export type MarketingCreativeMediaCapability = {
  status: string;
  provider_id: string | null;
  configuration_version: string | null;
  fidelity_mode: "generative" | "exact_source_transform" | null;
  supported_aspect_ratios: ("1:1" | "4:5" | "9:16" | "16:9" | "4:3" | "3:4" | "3:2" | "2:3")[];
  supported_formats: string[];
  max_reference_images: number | null;
  supported_generation_durations_seconds: number[];
  supports_native_voice: boolean;
  supports_native_music: boolean;
  max_final_duration_seconds: number | null;
  models: MarketingCreativeVideoModelCapability[];
  image_models: MarketingCreativeImageModelCapability[];
};

export type MarketingCreativeImageModelCapability = {
  provider_id: string;
  model_id: string;
  display_name: string;
  fidelity_mode: "generative" | "exact_source_transform";
  supported_modes: ("single_image_edit" | "multi_image_edit")[];
  supported_aspect_ratios: ("1:1" | "4:5" | "9:16" | "16:9" | "4:3" | "3:4" | "3:2" | "2:3")[];
  supported_resolutions: ("1k" | "1.5k" | "2k")[];
  supported_qualities: ("auto" | "low" | "medium" | "high" | "xhigh" | "max")[];
  supported_formats: ("png" | "jpeg" | "webp")[];
  supported_image_sizes: string[];
  supported_backgrounds: ("auto" | "opaque" | "transparent")[];
  supported_moderation: ("auto" | "low")[];
  supported_input_fidelities: ("low" | "high")[];
  supports_output_compression: boolean;
  max_reference_images: number;
  supports_text_rendering: boolean;
  supports_logo_input: boolean;
  cost_per_output_by_setting: Record<string, string>;
  input_image_cost: string;
};

export type MarketingCreativeVideoModelCapability = {
  model_id: string;
  display_name: string;
  fidelity_mode: "generative" | "exact_source_transform";
  supported_aspect_ratios: ("1:1" | "4:5" | "9:16" | "16:9" | "4:3" | "3:4" | "3:2" | "2:3")[];
  supported_resolutions: ("480p" | "720p" | "1080p")[];
  supported_generation_durations_seconds: number[];
  max_reference_images: number;
  max_product_images: number;
  reference_to_video_resolutions: ("480p" | "720p" | "1080p")[];
  supports_native_voice: boolean;
  supports_native_music: boolean;
};

export type MarketingCreativeAutomationCapabilities = {
  image: MarketingCreativeMediaCapability;
  video: MarketingCreativeMediaCapability;
  agent_models: string[];
  default_agent_model_id: string;
  agent_reasoning_levels: Record<string, ("auto" | "minimal" | "low" | "medium" | "high")[]>;
  default_agent_reasoning_level: "auto" | "minimal" | "low" | "medium" | "high";
};

export type ProductFamilyVariant = {
  variant_id: string;
  sku: string | null;
  title: string;
  selected_options: Record<string, string>;
  price: string | null;
  currency: string;
  media_ids: string[];
};

export type ProductFamilyCandidate = {
  source_id: string;
  snapshot_id: string;
  brand: string;
  product_id: string;
  family_key: string;
  handle: string;
  title: string;
  status: string | null;
  published_at: string | null;
  image_url: string | null;
  variant_count: number;
  variants: ProductFamilyVariant[];
  media: {
    media_id: string;
    url: string;
    position: number;
    variant_ids: string[];
    alt: string | null;
    width: number | null;
    height: number | null;
  }[];
};

export type ProductFamilyCatalog = { items: ProductFamilyCandidate[]; total: number };

export type MarketingCreativeProductSelection = {
  source_id: string;
  product_id: string;
  family_key: string;
  selection_scope: "product_family" | "variant";
  variant_id?: string;
  media_selection_mode: "agent" | "manual";
  selected_media_ids: string[];
};

export type MarketingCreativeReferenceAssignment = {
  output_key: string;
  reference_ids: string[];
};

export type MarketingCreativeVariantReferenceAssignment = {
  source_id: string;
  product_id: string;
  variant_id: string;
  reference_ids: string[];
};

export type MarketingCreativeAutomationRequest = {
  product_selections: MarketingCreativeProductSelection[];
  brand: string;
  market?: "US";
  platform: string;
  objective: string;
  agent_model_id?: string;
  agent_reasoning_effort?: "auto" | "minimal" | "low" | "medium" | "high";
  image_count: number;
  video_count: number;
  image_provider_id?: string;
  image_model_id?: string;
  image_resolution?: "1k" | "1.5k" | "2k";
  image_quality?: "auto" | "low" | "medium" | "high" | "xhigh" | "max";
  image_background?: "auto" | "opaque" | "transparent";
  image_moderation?: "auto" | "low";
  image_input_fidelity?: "low" | "high";
  image_output_compression?: number;
  video_model_id?: string;
  video_resolution?: "480p" | "720p" | "1080p";
  video_duration_seconds?: number;
  video_generate_audio?: boolean;
  execution_mode: "brief_only" | "generate_once";
  aspect_ratio: "1:1" | "4:5" | "9:16" | "16:9" | "4:3" | "3:4" | "3:2" | "2:3";
  sku_tier: "hero" | "winner" | "scale" | "long_tail" | "overflow";
  requested_by: string;
  notes?: string;
  include_text: boolean;
  headline?: string;
  subtext?: string;
  cta_text?: string;
  brand_instructions?: string;
  campaign_theme?: string;
  human_persona?: string;
  human_angle?: string;
  human_hooks: string[];
  human_offer?: string;
  human_claims: string[];
  include_logo: boolean;
  logo_asset_id?: string;
  use_research_references: boolean;
  reference_selection_mode: "none" | "human";
  selected_reference_ids: string[];
  output_reference_assignments: MarketingCreativeReferenceAssignment[];
  variant_reference_assignments: MarketingCreativeVariantReferenceAssignment[];
  creative_set_strategy: "single" | "multi_angle" | "layout_variations" | "background_variations" | "copy_variations" | "carousel";
  high_brand_risk: boolean;
  automation_override: boolean;
  idempotency_key: string;
  output_profiles: {
    profile_id: string;
    media_kind: "image" | "video";
    aspect_ratio: "1:1" | "4:5" | "9:16" | "16:9" | "4:3" | "3:4" | "3:2" | "2:3";
    file_format: "png" | "jpeg" | "webp" | "mp4";
    count: number;
    image_size?: string;
  }[];
};

export type MarketingCreativeAutomationItem = {
  request_id: string;
  batch_id: string | null;
  sku_id: string;
  source_id: string | null;
  product_id: string | null;
  family_key: string | null;
  selection_scope: "product_family" | "variant";
  selected_variant_id: string | null;
  product_media_selection_mode: "agent" | "manual" | "featured";
  selected_product_media_ids: string[];
  route: "manual" | "assisted" | "automated";
  routing_reasons: string[];
  status: string;
  intake_run_id: string | null;
  creative_job_id: string | null;
  package_ref: string | null;
  workflow_ref: string | null;
  review_id: string | null;
  asset_count: number;
  ads_draft_id: string | null;
  issues: { code: string; detail: string; component: string | null }[];
  image_count: number;
  video_count: number;
  image_provider_id: string | null;
  image_model_id: string | null;
  image_resolution: string | null;
  image_quality: string | null;
  image_generation_mode: string | null;
  video_duration_seconds: number | null;
  video_model_id: string | null;
  video_resolution: string | null;
  video_generate_audio: boolean | null;
  video_duration_min_seconds: number;
  video_duration_max_seconds: number;
  video_scene_duration_max_seconds: number;
  audio_selected_by_agent: boolean;
  execution_mode: "brief_only" | "generate_once";
  provider_status: string;
  output_profiles: {
    profile_id: string;
    media_kind: "image" | "video";
    aspect_ratio: string;
    file_format: string;
    count: number;
    image_size?: string | null;
  }[];
};

export type MarketingCreativeAsset = {
  asset_version_id: string;
  media_kind: "image" | "video";
  artifact_ref: string;
  artifact_web_url: string | null;
  checksum_sha256: string;
  content_type: string;
  qa_summary: string;
  revision_count: number;
  provider_id: string;
  cost: string;
  fidelity_mode: "generative" | "exact_source_transform";
  product_source_checksum_sha256: string | null;
};

export type MarketingCreativeAutomationDetail = {
  request_id: string;
  package_id: string;
  package_ref: string;
  route: "manual" | "assisted" | "automated";
  status: string;
  issues: { code: string; detail: string; component: string | null }[];
  final_review: {
    review_id: string;
    direction_summary: string;
    review_checklist: string[];
    assets: MarketingCreativeAsset[];
    image_count: number;
    video_count: number;
    created_at: string;
  } | null;
  production_versions: {
    asset_version_id: string;
    parent_asset_version_id: string | null;
    generation_request_id: string | null;
    revision_feedback: string | null;
    media_kind: "image" | "video";
    variation_key: string;
    success: boolean;
    outcome: string;
    attempt_count: number;
    total_cost: string;
    artifact_ref: string | null;
    artifact_web_url: string | null;
    checksum_sha256: string | null;
    content_type: string | null;
    provider_id: string | null;
    actual_width: number | null;
    actual_height: number | null;
    actual_duration_seconds: number | null;
    has_audio_stream: boolean | null;
    fidelity_mode: "generative" | "exact_source_transform" | null;
    product_source_checksum_sha256: string | null;
    technical_check_summary: string | null;
    intermediate_artifacts: {
      artifact_ref: string;
      artifact_web_url: string | null;
      checksum_sha256: string;
      content_type: string;
      provider_id: string;
      duration_seconds: number | null;
      cost: string;
      fidelity_mode: "generative" | "exact_source_transform";
      product_source_checksum_sha256: string | null;
    }[];
  }[];
  review_decision: {
    decision_id: string;
    review_id: string;
    decision: "approve" | "manual_takeover";
    asset_version_ids: string[];
    asset_checksums: string[];
    reviewer_alias: string;
    reason: string;
    decided_at: string;
    key_visual_asset_version_id: string | null;
  } | null;
  manual_takeover: {
    takeover_id: string;
    requested_by: string;
    reason: string;
    requested_at: string;
  } | null;
  ads_draft: {
    draft_id: string;
    destination_ref: string;
    daily_budget: string;
    currency: string;
    draft_fingerprint: string;
    status: string;
    asset_version_ids: string[];
    asset_checksums: string[];
    created_at: string;
  } | null;
  ads_approved: boolean;
  ads_provider_status: string;
  ads_activation: {
    platform: string;
    account_id: string;
    campaign_id: string;
    ad_ids: string[];
    activated_at: string;
  } | null;
  production_attempt_count: number;
  generation_request_count: number;
  generation_requests: {
    generation_request_id: string;
    requested_by: string;
    reason: string;
    requested_at: string;
    target_asset_version_ids: string[];
    knowledge_refs: string[];
  }[];
  production_cost: string;
  production_error_code: string | null;
  production_error_detail: string | null;
  created_at: string;
  updated_at: string;
  trace: {
    request: Record<string, unknown>;
    source_refs: string[];
    memory_refs: string[];
    knowledge_refs_by_stage: Record<string, string[]>;
    selected_idea: Record<string, unknown> | null;
    prepared_brief: Record<string, unknown> | null;
    strategy: Record<string, unknown> | null;
    plan: {
      plan_id: string;
      readiness: string;
      strategy_summary: string;
      rationale: string;
      evidence_refs: string[];
      image_plans: Record<string, unknown>[];
      video_plan: Record<string, unknown> | null;
      video_plans: Record<string, unknown>[];
      missing_context: string[];
      uncertainties: string[];
      memory_refs: string[];
      model_profile: string;
      prompt_version: string;
    } | null;
    events: { event_id: string; event_type: string; payload: Record<string, unknown>; created_at: string }[];
    input_tokens: number | null;
    output_tokens: number | null;
    total_cost: string;
    technical_checks: string[];
    latency: {
      total_duration_ms: number | null;
      total_outcome: "succeeded" | "failed" | null;
      is_final: boolean;
      steps: {
        step: string;
        outcome: "succeeded" | "failed";
        started_at: string;
        completed_at: string;
        duration_ms: number;
      }[];
    };
  } | null;
};

export type MarketingCreativeAutomationBatch = {
  batch_id: string;
  items: MarketingCreativeAutomationItem[];
  total: number;
};

export type MarketingCreativeAutomationList = {
  items: MarketingCreativeAutomationItem[];
  total: number;
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
  analysis_model_id: string;
};

export type ResearchMediaMode = "images" | "videos" | "images_and_videos";

export type ResearchReviewDecision = "approve" | "reject" | "review_later";

export type ResearchKeywordSuggestion = {
  keyword: string;
};

export type ResearchKeywordSuggestionList = {
  brand_id: string;
  items: ResearchKeywordSuggestion[];
};

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
  prompt_version: string;
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
  version_count: number;
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

export type ShortlistedResearchReference = {
  reference_id: string;
  record_key: string;
  media_id: string;
  artifact_ref: string;
  platform: string;
  title: string;
  summary: string;
  score: number;
  reasons: string[];
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
  versions: {
    version_id: string;
    record_key: string;
    job_id: string;
    content_hash: string;
    record: ResearchCrawlRecord;
    observed_at: string;
  }[];
};

export type CreativeKnowledgeStatus =
  | "draft"
  | "proposed"
  | "approved"
  | "rejected"
  | "superseded"
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
  version: number;
  version_ref: string;
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
  supersedes: string | null;
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
