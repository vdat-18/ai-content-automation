const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const src = (...parts) => fs.readFileSync(path.resolve(__dirname, "../src", ...parts), "utf8");

test("pilot API owns every backend HTTP request", () => {
  const api = src("services", "pilotApi.ts");
  const http = src("services", "http.ts");
  const sourceRoot = path.resolve(__dirname, "../src");
  const files = [];
  const visit = (directory) => {
    for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
      const target = path.join(directory, entry.name);
      if (entry.isDirectory()) visit(target);
      else if (/\.(ts|tsx)$/.test(entry.name)) files.push(target);
    }
  };
  visit(sourceRoot);

  assert.match(http, /response = await fetch\(path, init\)/);
  assert.match(api, /dashboard.*\/api\/v1\/dashboard\/snapshot/);
  assert.match(api, /aiUsage.*\/api\/v1\/ai-usage\/summary/);
  assert.match(api, /aiUsageEvents.*\/api\/v1\/ai-usage\/events/);
  assert.match(api, /aiUsageEvent.*\/api\/v1\/ai-usage\/events/);
  assert.match(api, /aiUsageRuns.*\/api\/v1\/ai-usage\/runs/);
  assert.match(api, /gmcRuns.*\/api\/v1\/performance\/gmc\/runs/);
  assert.match(api, /dataSources.*\/api\/v1\/data-sources/);
  assert.match(api, /sourcePerformanceCandidates[\s\S]*performance-candidates/);
  assert.match(api, /marketingCreativeAutomations[\s\S]*marketing\/creative-automations/);
  assert.match(api, /creativeKnowledge[\s\S]*marketing\/creative-knowledge/);
  for (const file of files.filter((item) => !item.endsWith(path.join("services", "http.ts")))) {
    assert.doesNotMatch(fs.readFileSync(file, "utf8"), /\bfetch\(/, file);
  }
});

test("SecondBrain exposes a human-governed Creative knowledge lifecycle", () => {
  const page = src("pages", "CreativeKnowledge.tsx");
  const styles = src("styles.css");
  const app = src("App.tsx");
  const shell = src("components", "AppShell.tsx");
  const api = src("services", "pilotApi.ts");

  assert.match(app, /path="second-brain"/);
  assert.match(shell, /to: "\/second-brain"/);
  assert.match(api, /creative-knowledge\/bootstrap/);
  assert.match(api, /manifest_id: "creative_v2_2026_09_29"/);
  assert.match(api, /decideCreativeKnowledge/);
  assert.match(api, /markCreativeKnowledgeConflict/);
  assert.match(page, /Version history/);
  assert.match(page, /Propose updated version/);
  assert.match(page, /Propose reusable lesson/);
  assert.match(page, /knowledge_type === "feedback"/);
  assert.match(page, /Used by stages/);
  assert.match(page, /applies_to: proposal\.appliesTo/);
  assert.match(page, /useSplitResize\("aic-second-brain-split"/);
  assert.match(page, /<SplitHandle label="Resize knowledge panels"/);
  assert.match(styles, /\.second-brain-layout\.split-active/);
  assert.match(styles, /\.second-brain-detail \{[^}]*overflow-y: auto/);
  assert.doesNotMatch(page, /Load the latest reviewed source package/);
  assert.doesNotMatch(page, /Save as a proposal first/);
  assert.doesNotMatch(page, /autoApprove|auto_approve/);
});

test("Creative review exposes pinned SecondBrain criteria", () => {
  const operations = src("pages", "Operations.tsx");
  const contracts = src("types", "pilotApi.ts");

  assert.match(contracts, /review_checklist: string\[\]/);
  assert.match(contracts, /knowledge_refs: string\[\]/);
  assert.match(operations, /SecondBrain review checklist/);
  assert.match(operations, /review\.review_checklist\.map/);
});

test("Model Lab chat composer expands as the user types", () => {
  const page = src("pages", "ModelLab.tsx");
  assert.match(page, /scrollHeight/);
  assert.match(page, /Math\.min\(event\.currentTarget\.scrollHeight, 240\)/);
  assert.match(page, /rows=\{1\}/);
});

test("AI usage page reads the durable API without mock fallback", () => {
  const page = src("pages", "AIUsage.tsx");
  assert.match(page, /useAIUsage/);
  assert.match(page, /useAIUsageEvents/);
  assert.match(page, /useAIUsageRuns/);
  assert.match(page, /Unknown cost is never treated as zero/);
  assert.match(page, /Runs & jobs/);
  assert.match(page, /Provider calls/);
  assert.match(page, /Trace coverage/);
  assert.match(page, /Provider call detail/);
  assert.doesNotMatch(page, /mockApi|mockData/);
});

test("Media Lab Create Image uses typed API contracts and human review", () => {
  const page = src("pages", "MediaLab.tsx");
  const videoPage = src("pages", "MediaLabVideoPanel.tsx");
  const finalAdPage = src("pages", "MediaLabFinalVideoAdPanel.tsx");
  const autoResizeTextarea = src("components", "AutoResizeTextarea.tsx");
  const styles = src("styles.css");
  const api = src("services", "pilotApi.ts");
  const shell = src("components", "AppShell.tsx");

  assert.ok(api.includes("/api/v1/media-lab/image-orchestration"));
  assert.ok(api.includes("/api/v1/media-lab/image-plan-jobs"));
  assert.ok(api.includes("/draft"));
  assert.ok(page.includes("mediaLabImagePlanningJob"));
  assert.ok(page.includes("imagePlanningJobStorageKey"));
  assert.ok(api.includes("/api/v1/media-lab/image-runs"));
  assert.ok(api.includes("reviewMediaLabImageRun"));
  assert.ok(page.includes("pilotApi.mediaLabImageOrchestration"));
  assert.ok(page.includes("pilotApi.prepareMediaLabImage"));
  assert.ok(page.includes("pilotApi.createMediaLabImageRun"));
  assert.ok(page.includes("pilotApi.reviewMediaLabImageRun"));
  assert.ok(page.includes("Review request"));
  assert.ok(page.includes("Generate draft anyway"));
  assert.ok(page.includes("Visible text and unresolved details may be inaccurate"));
  assert.ok(page.includes("Output quality and size"));
  assert.ok(page.includes("View quality checks and version history"));
  assert.ok(page.indexOf("Generated master") < page.indexOf("View quality checks and version history"));
  assert.ok(page.includes("How your images will be used"));
  assert.ok(page.includes("Human review required"));
  assert.ok(page.includes("quality_review_state"));
  assert.ok(page.includes("regenerated_run_id"));
  assert.ok(page.includes("Quality summary"));
  assert.ok(page.includes("max_image_sources"));
  assert.ok(page.includes("addReferenceFiles"));
  assert.ok(page.includes("multiple"));
  assert.ok(page.includes("<AutoResizeTextarea"));
  assert.ok(videoPage.includes("<AutoResizeTextarea"));
  assert.ok(finalAdPage.includes("<AutoResizeTextarea"));
  assert.ok(autoResizeTextarea.includes("textarea.scrollHeight"));
  assert.match(styles, /\.media-lab-prompt textarea \{ max-height: min\(65vh, 720px\); overflow-y: auto; \}/);
  assert.doesNotMatch(page, /capabilityId|Product source image|Style reference image/);
  assert.doesNotMatch(page, /Run ID|Provider delay|Variation seed|Technical details/);
  assert.doesNotMatch(page, /fetch\(/);
  assert.match(shell, /to: "\/media-lab"/);
});

test("Media Lab Create Video uses the persistent typed flow and explicit human review", () => {
  const page = src("pages", "MediaLabVideoPanel.tsx");
  const mediaLab = src("pages", "MediaLab.tsx");
  const api = src("services", "pilotApi.ts");

  assert.ok(api.includes("/api/v1/media-lab/video-orchestration"));
  assert.ok(api.includes("/api/v1/media-lab/video-capabilities"));
  assert.ok(api.includes("/api/v1/media-lab/video-plan-jobs"));
  assert.ok(page.includes("mediaLabVideoPlanningJob"));
  assert.ok(page.includes("videoPlanningJobStorageKey"));
  assert.ok(api.includes("/api/v1/media-lab/video-runs"));
  assert.ok(api.includes("reviewMediaLabVideoRun"));
  assert.ok(mediaLab.includes("<MediaLabVideoPanel />"));
  assert.ok(page.includes("pilotApi.prepareMediaLabVideo"));
  assert.ok(page.includes("pilotApi.createMediaLabVideoRun"));
  assert.ok(page.includes("pilotApi.reviewMediaLabVideoRun"));
  assert.ok(page.includes('kind: "media_asset"'));
  assert.ok(page.includes("asset_id: source.asset.asset_id"));
  assert.ok(page.includes("How your images will be used"));
  assert.ok(page.includes("verification_plan"));
  assert.ok(page.includes("max_generation_image_sources"));
  assert.ok(page.includes("multiple"));
  assert.ok(page.includes("verification_state"));
  assert.ok(page.includes("verification_frames"));
  assert.ok(page.includes("verification_error_code"));
  assert.ok(page.includes("Automated quality check evidence"));
  assert.ok(page.includes("Persisted temporal evidence"));
  assert.ok(page.includes("approval is unavailable"));
  assert.ok(page.includes('quality_review_error_code !== "retry_budget_exhausted"'));
  assert.ok(page.includes("now requires human review"));
  assert.ok(page.includes("Check the product details, full motion"));
  assert.match(page, /<video controls src=\{run\.output_url\}/);
  assert.ok(page.includes("max_image_sources"));
  assert.doesNotMatch(page, /Run ID|Provider delay|Variation seed|Technical details/);
});

test("Creative detail reviews every exact final version with its source brief", () => {
  const page = src("pages", "CreativeJobs.tsx");
  const api = src("services", "pilotApi.ts");
  assert.match(page, /final_version_refs/);
  assert.match(page, /finalVersions\.map/);
  assert.match(page, /CreativeVersionReview/);
  assert.match(page, /reviewer\.trim\(\)/);
  assert.match(api, /creativeReviewContext/);
  assert.doesNotMatch(page, /reviewer: "marketing-reviewer"/);
  assert.doesNotMatch(page, /candidate_summary \?\? creativeTitle/);
  assert.match(page, /Search title, run, job or idea/);
  assert.doesNotMatch(page, /Search brand, SKU, run or idea/);
  assert.match(page, /job\.display_title/);
  assert.match(page, /t\("Ready for review"\)/);
  assert.match(page, /Synthetic output — no viewable image/);
  assert.match(page, /decision-callout--form/);
  assert.match(page, /decision-callout--sticky/);
  assert.match(page, /display_title/);
  assert.match(page, /thumbnail_web_url/);
  assert.doesNotMatch(page, /CreativeJobThumbnail/);
  assert.match(page, /audit-details/);
  assert.match(page, /Version technical details/);
  assert.match(page, /Total cost/);
  assert.match(page, /job\.card\?\.candidate_summary/);
  assert.match(page, /Team brief/);
  assert.match(page, /useHiddenCreatives/);
  assert.match(page, /creative-pipeline-row__actions/);
  assert.match(page, /Restore hidden/);
  assert.match(page, /toggleAllVisible/);
  assert.match(page, /Remove selected/);
  assert.match(page, /creative-pipeline-row__select/);
  assert.match(page, /hideCreatives\(selectedVisibleIds\)/);
  assert.match(page, /creativeWarning/);
  assert.match(page, /Product fidelity, visible text, claims and brand fit still need human review/);
});

test("operational pages use the backend dashboard projection without a mock fallback", () => {
  const shell = src("components", "AppShell.tsx");
  const overview = src("pages", "Overview.tsx");
  const approvals = src("pages", "Approvals.tsx");
  const operations = src("pages", "Operations.tsx");

  for (const source of [overview, approvals, operations]) {
    assert.match(source, /usePilotDashboard/);
  }
  assert.match(overview, /useDataSources/);
  assert.match(overview, /Needs your decision/);
  assert.match(overview, /Failed commands/);
  assert.match(overview, /flow\.business_stage/);
  assert.match(approvals, /Could not load approvals/);
  assert.match(approvals, /DecisionCard/);
  assert.match(approvals, /previewByEntity/);
  assert.doesNotMatch(approvals, /data\.marketing\.approvals/);
  assert.match(operations, /pilot\.data\?\.exceptions/);
  assert.match(operations, /pilot\.data\?\.workflows/);
  assert.doesNotMatch(operations, /pilotApi\.marketingCreativeAutomations/);
  assert.match(operations, /brand: selectedBrand/);
  assert.match(operations, /sku_tier: "overflow"/);
  assert.match(operations, /high_brand_risk: false/);
  assert.match(operations, /image_count: imageCount/);
  assert.match(operations, /video_count: videoCount/);
  assert.match(operations, /platform: "meta"/);
  assert.match(operations, /objective: "conversion"/);
  assert.match(operations, /Search SKU, product name, or Variant/);
  assert.doesNotMatch(operations, /includeBackgroundMusic|marketOptions|creativeDirections/);
  assert.doesNotMatch(operations, /Only overflow\/backlog SKU requests/);
  assert.doesNotMatch(operations, /Recent requests/);
  assert.match(operations, /Pipeline latency/);
  assert.match(operations, /trace\.latency\.total_duration_ms/);
  assert.match(operations, /trace\.latency\.steps/);
  assert.match(shell, /pilot\.data\?\.summary\.pending_approvals/);
  assert.match(shell, /Connected/);
  assert.match(shell, /role="dialog" aria-modal="true" aria-label=\{t\("Search workspace"\)\}/);
  assert.match(shell, /creatives\.data\?\.items\.map/);
  assert.match(shell, /pilot\.data\?\.exceptions\.map/);
  assert.match(shell, /Local pilot/);
  assert.match(shell, /No sign-in/);
  assert.match(shell, /AI usage brand/);
  assert.doesNotMatch(shell, /navigate\("\/"\).*Brand workspace/s);
  assert.doesNotMatch(shell, /Dat Nguyen|AI Engineer/);
  assert.doesNotMatch(shell, /mockApi|mockData|mock\.error/);
  assert.doesNotMatch(shell, /error \? <section className="error-panel"/);
});

test("GMC panel uses the backend read model", () => {
  const shared = src("marketing", "Shared.tsx");

  assert.match(shared, /useGmcRuns/);
  assert.match(shared, /H1 GMC ingestion/);
});

test("Creative production uses exact per-ratio quantities and provider capabilities", () => {
  const page = src("pages", "Operations.tsx");
  const api = src("services", "pilotApi.ts");
  const types = src("types", "pilotApi.ts");

  assert.match(page, /imageQuantities/);
  assert.match(page, /videoQuantities/);
  assert.match(page, /imageFormat/);
  assert.match(page, /supported_formats/);
  assert.match(page, /selectedImageModel/);
  assert.match(page, /image_provider_id/);
  assert.match(page, /Image model/);
  assert.match(page, /exact_source_transform" \? t\("Exact Shopify source"\) : model\.display_name/);
  assert.match(page, /image_model_id/);
  assert.match(page, /image_resolution/);
  assert.match(page, /image_quality/);
  assert.match(page, /automation-profile-editor/);
  assert.match(page, /moveOutputProfile/);
  assert.match(page, /Add image profile/);
  assert.match(types, /MarketingCreativeImageModelCapability/);
  assert.match(page, /output_profiles/);
  assert.match(page, /const \[executionMode\] = useState<"brief_only" \| "generate_once">\("generate_once"\)/);
  assert.doesNotMatch(page, /<option value="brief_only">/);
  assert.match(page, /marketingCreativeAutomationCapabilities/);
  assert.match(page, /Agent model/);
  assert.match(page, /agent_model_id: agentModelId/);
  assert.match(types, /agent_models: string\[\]/);
  assert.match(page, /routeQuantities/);
  assert.doesNotMatch(page, /recentBatches/);
  assert.match(page, /selectedAssetIds/);
  assert.match(page, /target_asset_version_ids: revisionAssetIds/);
  assert.match(page, /creative_set_strategy: "single"/);
  assert.match(page, /selected_reference_ids/);
  assert.match(page, /variant_reference_assignments: variantReferenceAssignments/);
  assert.match(page, /reference_selection_mode/);
  assert.doesNotMatch(page, /Let Agent choose after the brief/);
  assert.match(page, /3\. Upload visual references/);
  assert.match(page, /Apply these references to all Variants/);
  assert.doesNotMatch(page, /Do not use visual references/);
  assert.doesNotMatch(page, /pilotApi\.researchRecords/);
  assert.doesNotMatch(page, /researchReferenceOptions/);
  assert.match(page, /pilotApi\.uploadMediaAsset\(file, "image"/);
  assert.match(page, /`upload:\$\{asset\.asset_id\}`/);
  assert.match(page, /Upload your own reference/);
  assert.match(page, /selectedIds\.length >= maximumHumanReferences/);
  assert.match(page, /setVideoQuantities\] = useState<OutputQuantities>\(\{ "9:16": 1/);
  assert.match(page, /&& imageCount > 0\s*&& videoCount > 0/);
  assert.match(page, /Start creates both images and videos, plus the detailed brief/);
  assert.match(src("styles.css"), /\.automation-reference-upload/);
  assert.match(page, /automation-product-browser/);
  assert.match(page, /automation-product-card__summary/);
  assert.match(page, /automation-variant-browser/);
  assert.match(page, /productThumbnail/);
  assert.match(page, /variantMedia/);
  assert.match(page, /Browse matching Products/);
  assert.match(page, /role="combobox"/);
  assert.match(page, /onFocus=\{\(\) => setProductPickerOpen\(true\)\}/);
  assert.match(page, /open=\{productPickerOpen\}/);
  assert.match(page, /Loading Products and Variants/);
  assert.match(page, /productBrowseLimit/);
  assert.match(page, /Products shown/);
  assert.match(api, /limit: String\(limit\)/);
  assert.match(page, /View images/);
  assert.match(page, /automation-product-gallery-dialog/);
  assert.match(page, /openProductGallery/);
  assert.match(page, /openProductGallery\(item, variantImage\?\.media_id\)/);
  assert.match(page, /openProductGallery\(product, media\.media_id\)/);
  assert.match(src("styles.css"), /cursor: zoom-in/);
  assert.doesNotMatch(page, /filteredSuggestions\.flatMap/);
  assert.match(src("styles.css"), /\.automation-suggestions > \.automation-product-browser \{ grid-template-columns: repeat\(4/);
  assert.match(src("styles.css"), /\.automation-product-browser-item \{ align-self: start; display: grid/);
  assert.doesNotMatch(src("pages", "Operations.tsx"), /2\. Creative approach/);
  assert.doesNotMatch(src("pages", "Operations.tsx"), /Run owner/);
  assert.match(src("pages", "Operations.tsx"), /const preferredAgentModelId = "gemini-3\.8-flash"/);
  assert.match(src("pages", "Operations.tsx"), /const preferredImageModelId = "gpt-image-2\.5-flare"/);
  assert.match(src("pages", "Operations.tsx"), /const preferredVideoModelId = "grok-imagine-video-1\.5"/);
  assert.match(src("pages", "Operations.tsx"), /useState\(15\)/);
  assert.match(src("pages", "Operations.tsx"), /className="automation-output-settings"/);
  assert.match(src("pages", "Operations.tsx"), /2\. Additional requirements \(optional\)/);
  assert.match(src("pages", "Operations.tsx"), /3\. Upload visual references/);
  assert.match(src("pages", "Operations.tsx"), /4\. Output per Variant/);
  assert.doesNotMatch(src("pages", "Operations.tsx"), /5\. Output per Variant/);
  assert.match(src("pages", "Operations.tsx"), /creative_set_strategy: "single"/);
  assert.match(src("pages", "Operations.tsx"), /execution_mode: executionMode/);
  assert.match(src("pages", "Operations.tsx"), /to="\/creatives\?view=media"/);
  assert.match(src("pages", "Operations.tsx"), /automation-media-mode-help/);
  assert.match(page, /notes: otherContext/);
  assert.match(page, /imageTextMode/);
  assert.match(page, /supports_text_rendering/);
  assert.match(page, /Let Agent write/);
  assert.match(page, /Use exact text/);
  assert.match(page, /headline: imageHeadline/);
  assert.doesNotMatch(page, /include_text: false/);
  assert.doesNotMatch(page, /What do you want to receive/);
  assert.match(page, /Array\.from\(\{ length: Math\.min\(30, maximumFinalVideoDuration\) \}/);
  assert.doesNotMatch(page, /Campaign preset/);
  assert.match(page, /Use this output/);
  assert.match(page, /Key Visual/);
  assert.doesNotMatch(page, /outputs ready/);
  assert.match(api, /creative-automations\/capabilities/);
  assert.match(types, /target_asset_version_ids/);
  assert.doesNotMatch(page, /distributeOutputProfiles/);
});

test("Creative production limits reference uploads and output totals in the frontend", () => {
  const production = src("pages", "Operations.tsx");
  const imageLab = src("pages", "MediaLab.tsx");
  const videoLab = src("pages", "MediaLabVideoPanel.tsx");

  assert.match(production, /const maximumOutputsPerMediaKind = 10/);
  assert.match(production, /const maximumForRatio = exactSource \? 1 : maximumOutputsPerMediaKind/);
  assert.match(production, /totalQuantity\(quantities\) < maximumOutputsPerMediaKind/);
  assert.match(imageLab, /const maximumReferenceImages = 10/);
  assert.match(videoLab, /const maximumReferenceImages = 10/);
  assert.match(imageLab, /Math\.min\(orchestration\?\.max_image_sources \?\? 0, maximumReferenceImages\)/);
  assert.match(videoLab, /Math\.min\(orchestration\?\.max_image_sources \?\? 0, maximumReferenceImages\)/);
});

test("Marketing workspace uses responsive task groups and dense operator layouts", () => {
  const shell = src("components", "AppShell.tsx");
  const operations = src("pages", "Operations.tsx");
  const shared = src("marketing", "Shared.tsx");
  const styles = src("marketing", "workspace.css");

  assert.match(shell, /Creative workflow/);
  assert.match(shell, /Research & knowledge/);
  assert.match(shell, /Creative Library/);
  assert.match(operations, /useSplitResize\("aic-creative-output-split"/);
  assert.match(operations, /<SplitHandle label="Resize output settings"/);
  assert.match(operations, /workflow-list--activity/);
  assert.match(operations, /<footer><span>\{t\("Suggested action"\)\}/);
  assert.match(shared, /performance-decision-value/);
  assert.match(styles, /\.automation-output-card \{ grid-column: 2; grid-row: 1;/);
  assert.match(styles, /\.workflow-list--activity \{[^}]*repeat\(2/);
  assert.match(styles, /\.exception-list \{[^}]*repeat\(2/);
});

test("Data Sources uses the read-only backend connector status", () => {
  const operations = src("pages", "Operations.tsx");
  const livePerformance = src("marketing", "LivePerformanceEvidence.tsx");
  const hook = src("hooks", "useDataSources.ts");

  assert.match(operations, /useDataSources/);
  assert.match(operations, /Real read-only API checks/);
  assert.match(operations, /LivePerformanceEvidence/);
  assert.match(operations, /PerformanceDecisions/);
  assert.match(operations, /<LivePerformanceEvidence \/><GmcBackendPilot \/>/);
  assert.match(src("marketing", "Shared.tsx"), /Recommended actions/);
  assert.match(src("marketing", "Shared.tsx"), /Evidence and evaluation details/);
  assert.match(src("marketing", "Shared.tsx"), /performanceRecommendationLabel/);
  assert.match(livePerformance, /Live SKU performance evidence/);
  assert.match(livePerformance, /creative_lineage_status/);
  assert.match(livePerformance, /Evidence only\./);
  assert.match(hook, /pilotApi\.dataSources/);
  assert.match(hook, /pilotApi\.sourcePerformanceCandidates/);
  assert.match(hook, /pilotApi\.syncDataSource/);
  assert.match(hook, /pilotApi\.syncAllDataSources/);
  assert.doesNotMatch(hook, /mockApi|mockData/);
});

test("Media Lab final Video Ad runs autonomously without review controls", () => {
  const page = src("pages", "MediaLabFinalVideoAdPanel.tsx");
  const api = src("services", "pilotApi.ts");

  assert.ok(api.includes("/api/v1/media-lab/video-ads"));
  assert.ok(api.includes("createMediaLabVideoAd"));
  assert.ok(api.includes("cancelMediaLabVideoAd"));
  assert.ok(page.includes("pilotApi.createMediaLabVideoAd"));
  assert.match(page, /pilotApi\s*\.mediaLabVideoAd/);
  assert.ok(page.includes("Generate source shots"));
  assert.ok(page.includes("Select usable segments"));
  assert.ok(page.includes("Assemble final Ad"));
  assert.ok(page.includes("Download final MP4"));
  assert.doesNotMatch(page, /Approve exact video|reviewMediaLabVideoRun/);
});

test("Media Library exposes persisted image and video output history", () => {
  const page = src("pages", "MediaLibrary.tsx");
  const library = src("pages", "CreativeLibrary.tsx");
  const app = src("App.tsx");
  const shell = src("components", "AppShell.tsx");
  const styles = src("styles.css");

  assert.match(app, /path="media-library"/);
  assert.match(app, /Navigate replace to="\/creatives\?view=media"/);
  assert.doesNotMatch(shell, /to: "\/media-library"/);
  assert.match(library, /Creative jobs & briefs/);
  assert.match(library, /Generated media/);
  assert.match(library, /<MediaLibraryPage \/>/);
  assert.match(library, /<CreativesPage \/>/);
  assert.match(page, /pilotApi\.mediaLabImageRuns/);
  assert.match(page, /pilotApi\.mediaLabVideoRuns/);
  assert.match(page, /pilotApi\.mediaLabVideoAds/);
  assert.match(page, /VITE_ENABLE_LEGACY_LOCAL_MODELS/);
  assert.match(page, /legacyLocalModelsEnabled \? pilotApi\.mediaLabImageRuns/);
  assert.match(page, /legacyLocalModelsEnabled \? pilotApi\.mediaLabVideoRuns/);
  assert.match(page, /legacyLocalModelsEnabled \? pilotApi\.mediaLabVideoAds/);
  assert.match(page, /pilotApi\.marketingCreativeAutomations/);
  assert.match(page, /pilotApi\.marketingCreativeAutomation/);
  assert.match(page, /detail\.production_versions/);
  assert.match(page, /source: "creative-production"/);
  assert.match(page, /pilotApi\.deleteMediaLabImageRun/);
  assert.match(page, /pilotApi\.deleteMediaLabVideoRun/);
  assert.match(page, /pilotApi\.deleteMediaLabVideoAd/);
  assert.match(page, /media-library-card-delete/);
  assert.match(page, /media-library-card-hover/);
  assert.match(page, /HIDDEN_MEDIA_OUTPUTS_KEY/);
  assert.match(page, /Restore hidden/);
  assert.match(page, /Remove from Media Library/);
  assert.match(page, /window\.confirm/);
  assert.match(page, /planner_prompt_version/);
  assert.match(page, /production_prompt/);
  assert.match(page, /Download output/);
  assert.doesNotMatch(page, /\.model\b|provider_job_id|seed/);
  assert.match(styles, /\.media-library-layout \{[^}]*grid-template-columns: minmax\(380px, 720px\) minmax\(520px, 1\.25fr\)/);
  assert.match(styles, /\.media-library-grid \{[^}]*minmax\(220px, 1fr\)/);
  assert.match(styles, /\.media-library-grid \{[^}]*max-height: calc\(100dvh - var\(--topbar-h\) - 90px\)[^}]*overflow-y: auto[^}]*overscroll-behavior: contain[^}]*scrollbar-gutter: stable/);
});

test("Creative jobs use a paginated operational list instead of empty media cards", () => {
  const page = src("pages", "CreativeJobs.tsx");
  const workspace = src("marketing", "workspace.css");

  assert.match(page, /const PAGE_SIZE = 20/);
  assert.match(page, /Needs action/);
  assert.match(page, /In progress/);
  assert.match(page, /Exceptions/);
  assert.match(page, /Completed/);
  assert.match(page, /creative-pipeline-list/);
  assert.match(page, /CreativePipelineRow/);
  assert.match(page, /Creative production ·/);
  assert.doesNotMatch(page, /creative-grid--pipeline/);
  assert.doesNotMatch(page, /No generated version/);
  assert.match(workspace, /\.creative-pipeline-row \{/);
  assert.match(workspace, /grid-template-columns: 44px minmax\(320px, 1fr\) 110px 190px 100px/);
});
