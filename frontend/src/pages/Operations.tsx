import { useEffect, useMemo, useRef, useState } from "react";
import { AlertCircle, ArrowLeft, ArrowRight, Check, Database, GitBranch, Image, RefreshCcw, ShieldCheck, Sparkles, TriangleAlert, Upload, Video } from "lucide-react";
import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { useDataSources, useDataSourceSync, useDataSourcesSyncAll } from "../hooks/useDataSources";
import { usePilotDashboard } from "../hooks/usePilotDashboard";
import { Badge, EmptyState, PageHeader, Panel, PanelHeader, SkeletonPage, StatusBadge } from "../components/ui";

import { pilotApi } from "../services/pilotApi";
import { LivePerformanceEvidence } from "../marketing/LivePerformanceEvidence";
import { GmcBackendPilot, PerformanceDecisions } from "../marketing/Shared";
import { businessStage, dashboardStreamLabels } from "../marketing/labels";
import { useI18n } from "../hooks/useI18n";
import { AutoResizeTextarea } from "../components/AutoResizeTextarea";
import { Modal } from "../components/Modal";
import { SplitHandle } from "../components/SplitHandle";
import { useSplitResize } from "../hooks/useSplitResize";
import type { MarketingCreativeAutomationBatch, MarketingCreativeAutomationCapabilities, MarketingCreativeAutomationDetail, MarketingCreativeProductSelection, ProductFamilyCandidate } from "../types/pilotApi";

export function PerformancePage() {
  const [params, setParams] = useSearchParams();
  const view = params.get("view") === "evidence" ? "evidence" : "decisions";
  return <>
    <PageHeader eyebrow="Learn and decide" title="Performance" description="Start with recommended actions, then inspect the source evidence when you need more detail." variant="analytics" />
    <div className="filterbar performance-view-switch"><div className="segmented">
      <button className={view === "decisions" ? "active" : ""} onClick={() => setParams({ view: "decisions" })}>Opportunities & decisions</button>
      <button className={view === "evidence" ? "active" : ""} onClick={() => setParams({ view: "evidence" })}>Source evidence</button>
    </div></div>
    {view === "decisions" ? <PerformanceDecisions /> : <><LivePerformanceEvidence /><GmcBackendPilot /></>}
  </>;
}

type CreativeLoopRun = {
  run_id: string;
  state: string;
  initial_evaluation_id: string;
  lesson_id: string | null;
  approved_creative_version_id: string | null;
  updated_at: string;
};
type CreativeLoopTimeline = {
  run: CreativeLoopRun;
  steps: { key: string; label: string; status: string; reference: string | null; detail: string }[];
};

const loopStageLabels = ["Opportunity", "Plan review", "Creative production", "Creative review", "Results", "Learning", "Next brief"];

const loopStatePresentation = (state: string | null | undefined) => {
  switch (state) {
    case "awaiting_demand_approval":
      return { title: "Experiment plan ready", detail: "Review the opportunity and decide whether the team should move into production." };
    case "awaiting_creative_approval":
      return { title: "Creative ready for review", detail: "Check the exact output before it can move to the results stage." };
    case "awaiting_ads_outcome":
      return { title: "Waiting for Ads results", detail: "The approved creative is live in the learning loop. No action is needed right now." };
    case "awaiting_lesson_approval":
      return { title: "Learning ready for review", detail: "Confirm the learning before AI applies it to the next creative brief." };
    case "next_brief_ready":
    case "completed":
      return { title: "Next brief is ready", detail: "This learning loop is complete and the next cycle can begin." };
    case "rejected":
    case "deferred":
      return { title: "Loop paused", detail: "This run is not progressing. Open the activity details if you need its audit history." };
    default:
      return { title: "AI is preparing the next step", detail: "This page will update automatically when the next decision or result is ready." };
  }
};
type ExecutionCommand = {
  command_id: string;
  name: string;
  workflow_run_id: string | null;
  status: string;
  attempts: number;
  max_attempts: number;
  updated_at: string;
  available_at: string;
  last_error_code: string | null;
  last_error_message: string | null;
};

const creativeRatios = ["9:16", "4:5", "1:1", "16:9", "4:3", "3:4", "3:2", "2:3"] as const;
const maximumOutputsPerMediaKind = 10;
type CreativeRatio = (typeof creativeRatios)[number];
type ImageFormat = "png" | "jpeg" | "webp";
type OutputQuantities = Record<CreativeRatio, number>;
type VariantReferenceTarget = {
  key: string;
  sourceId: string;
  productId: string;
  variantId: string;
  label: string;
  detail: string;
};
type CreativeReferenceOption = {
  referenceId: string;
  title: string;
  previewUrl: string;
};

const formatLatency = (durationMs: number | null) => {
  if (durationMs === null) return "In progress";
  if (durationMs < 1000) return `${Math.round(durationMs)} ms`;
  if (durationMs < 60_000) return `${(durationMs / 1000).toFixed(2)} s`;
  const minutes = Math.floor(durationMs / 60_000);
  return `${minutes}m ${((durationMs % 60_000) / 1000).toFixed(1)}s`;
};

const preferredAgentModelId = "grok-4-fast-reasoning";
const preferredImageModelId = "grok-imagine-image";
const preferredVideoModelId = "grok-imagine-video";
const launcherRequestedBy = "Marketing dashboard";
const matchesPreferredModel = (modelId: string, preferredModelId: string) => (
  modelId === preferredModelId || modelId.endsWith(`/${preferredModelId}`)
);

const outputProfiles = (
  mediaKind: "image" | "video",
  quantities: OutputQuantities,
  imageFormat: ImageFormat = "png",
  imageSizes: Partial<Record<CreativeRatio, string>> = {},
) =>
  creativeRatios.map((ratio) => ({
    profile_id: `${mediaKind}-${ratio.replace(":", "x")}-${mediaKind === "image" ? imageFormat : "mp4"}`,
    media_kind: mediaKind,
    aspect_ratio: ratio,
    file_format: mediaKind === "image" ? imageFormat : "mp4" as const,
    count: quantities[ratio],
    ...(mediaKind === "image" && imageSizes[ratio] ? { image_size: imageSizes[ratio] } : {}),
  })).filter((profile) => profile.count > 0);

const totalQuantity = (quantities: OutputQuantities) =>
  Object.values(quantities).reduce((total, count) => total + count, 0);

const updateQuantity = (
  quantities: OutputQuantities,
  ratio: CreativeRatio,
  value: string,
  maximumForRatio = maximumOutputsPerMediaKind,
): OutputQuantities => {
  const requested = Number(value);
  const nextValue = Number.isFinite(requested) ? Math.max(0, Math.trunc(requested)) : 0;
  const remaining = maximumOutputsPerMediaKind - (totalQuantity(quantities) - quantities[ratio]);
  return { ...quantities, [ratio]: Math.min(nextValue, maximumForRatio, Math.max(0, remaining)) };
};

const capQuantityPerRatio = (quantities: OutputQuantities, maximumForRatio: number): OutputQuantities => (
  Object.fromEntries(
    creativeRatios.map((ratio) => [ratio, Math.min(quantities[ratio], maximumForRatio)]),
  ) as OutputQuantities
);

const routeQuantities = (
  quantities: OutputQuantities,
  supportedRatios: readonly CreativeRatio[],
): OutputQuantities => {
  const next: OutputQuantities = { "9:16": 0, "4:5": 0, "1:1": 0, "16:9": 0, "4:3": 0, "3:4": 0, "3:2": 0, "2:3": 0 };
  for (const ratio of supportedRatios) next[ratio] = quantities[ratio];
  const dropped = totalQuantity(quantities) - totalQuantity(next);
  if (dropped > 0 && supportedRatios.length > 0) {
    const fallback = supportedRatios[0];
    next[fallback] = Math.min(maximumOutputsPerMediaKind, next[fallback] + dropped);
  }
  return next;
};

const quantitySummary = (quantities: OutputQuantities) => {
  const configured = creativeRatios
    .filter((ratio) => quantities[ratio] > 0)
    .map((ratio) => `${quantities[ratio]} × ${ratio}`);
  return configured.length > 0 ? configured.join(" · ") : "No outputs";
};

const ratioLabel = (ratio: CreativeRatio) => (
  ratio === "9:16" ? "Vertical" : ratio === "4:5" ? "Feed" : ratio === "1:1" ? "Square" : ["3:4", "2:3"].includes(ratio) ? "Portrait" : "Landscape"
);

const moveOutputProfile = (
  quantities: OutputQuantities,
  fromRatio: CreativeRatio,
  toRatio: CreativeRatio,
): OutputQuantities => {
  if (fromRatio === toRatio || quantities[toRatio] > 0) return quantities;
  return { ...quantities, [fromRatio]: 0, [toRatio]: quantities[fromRatio] };
};

const addOutputProfile = (
  quantities: OutputQuantities,
  supportedRatios: readonly CreativeRatio[],
): OutputQuantities => {
  const ratio = supportedRatios.find((item) => quantities[item] === 0);
  return ratio ? { ...quantities, [ratio]: 1 } : quantities;
};
export function CreativeAutomationLauncher() {
  const { t } = useI18n();
  const [catalog, setCatalog] = useState<ProductFamilyCandidate[]>([]);
  const [catalogLoading, setCatalogLoading] = useState(true);
  const [selectedProducts, setSelectedProducts] = useState<MarketingCreativeProductSelection[]>([]);
  const [skuSearch, setSkuSearch] = useState("");
  const [productPickerOpen, setProductPickerOpen] = useState(false);
  const [productBrowseLimit, setProductBrowseLimit] = useState(24);
  const [expandedProductKey, setExpandedProductKey] = useState<string | null>(null);
  const [previewProduct, setPreviewProduct] = useState<ProductFamilyCandidate | null>(null);
  const [previewMediaId, setPreviewMediaId] = useState<string | null>(null);
  const [otherContext, setOtherContext] = useState("");
  const [agentModelId, setAgentModelId] = useState(preferredAgentModelId);
  const [agentReasoningEffort, setAgentReasoningEffort] = useState<"auto" | "minimal" | "low" | "medium" | "high">("auto");
  const [variantReferenceIds, setVariantReferenceIds] = useState<Record<string, string[]>>({});
  const [uploadedReferenceOptions, setUploadedReferenceOptions] = useState<Record<string, CreativeReferenceOption[]>>({});
  const [referenceUploadProgress, setReferenceUploadProgress] = useState<Record<string, number | null>>({});
  const [referenceUploadErrors, setReferenceUploadErrors] = useState<Record<string, string>>({});
  const [imageQuantities, setImageQuantities] = useState<OutputQuantities>({ "9:16": 1, "4:5": 0, "1:1": 0, "16:9": 0, "4:3": 0, "3:4": 0, "3:2": 0, "2:3": 0 });
  const [videoQuantities, setVideoQuantities] = useState<OutputQuantities>({ "9:16": 1, "4:5": 0, "1:1": 0, "16:9": 0, "4:3": 0, "3:4": 0, "3:2": 0, "2:3": 0 });
  const [imageFormat, setImageFormat] = useState<ImageFormat>("png");
  const [imageProviderId, setImageProviderId] = useState("");
  const [imageModelId, setImageModelId] = useState("");
  const [imageResolution, setImageResolution] = useState<"1k" | "1.5k" | "2k">("1k");
  const [imageQuality, setImageQuality] = useState<"auto" | "low" | "medium" | "high" | "xhigh" | "max">("low");
  const [imageSizes, setImageSizes] = useState<Partial<Record<CreativeRatio, string>>>({});
  const [imageBackground, setImageBackground] = useState<"auto" | "opaque" | "transparent">("auto");
  const [imageModeration, setImageModeration] = useState<"auto" | "low">("auto");
  const [imageInputFidelity, setImageInputFidelity] = useState<"low" | "high">("high");
  const [imageOutputCompression, setImageOutputCompression] = useState(90);
  const [imageTextMode, setImageTextMode] = useState<"none" | "agent" | "exact">("none");
  const [imageHeadline, setImageHeadline] = useState("");
  const [imageSubtext, setImageSubtext] = useState("");
  const [imageCta, setImageCta] = useState("");
  const [videoModelId, setVideoModelId] = useState("");
  const [videoResolution, setVideoResolution] = useState<"480p" | "720p" | "1080p">("720p");
  const [videoDurationSeconds, setVideoDurationSeconds] = useState(15);
  const [videoGenerateAudio, setVideoGenerateAudio] = useState(true);
  const [executionMode] = useState<"brief_only" | "generate_once">("generate_once");
  const [capabilities, setCapabilities] = useState<MarketingCreativeAutomationCapabilities | null>(null);
  const [result, setResult] = useState<MarketingCreativeAutomationBatch | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const outputPanelRef = useRef<HTMLElement>(null);
  const outputSplit = useSplitResize("aic-creative-output-split", 340, 520, outputPanelRef);

  useEffect(() => {
    const controller = new AbortController();
    pilotApi.marketingCreativeAutomationCapabilities(controller.signal)
      .then(setCapabilities)
      .catch((caught: unknown) => {
        if ((caught as { name?: string }).name !== "AbortError") {
          setError(caught instanceof Error ? caught.message : "Media capabilities are unavailable");
        }
      });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (!capabilities?.agent_models.length) return;
    if (!capabilities.agent_models.includes(agentModelId)) {
      setAgentModelId(
        capabilities.agent_models.find((modelId) => matchesPreferredModel(modelId, preferredAgentModelId))
          ?? capabilities.default_agent_model_id,
      );
    }
  }, [agentModelId, capabilities]);

  const agentReasoningLevels = useMemo(
    () => capabilities?.agent_reasoning_levels[agentModelId] ?? [],
    [agentModelId, capabilities],
  );

  useEffect(() => {
    if (!agentReasoningLevels.length) return;
    if (!agentReasoningLevels.includes(agentReasoningEffort)) {
      setAgentReasoningEffort(
        agentReasoningLevels.includes(capabilities?.default_agent_reasoning_level ?? "auto")
          ? capabilities!.default_agent_reasoning_level
          : agentReasoningLevels[0],
      );
    }
  }, [agentReasoningEffort, agentReasoningLevels, capabilities]);

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    setCatalogLoading(true);
    const timer = window.setTimeout(() => {
      pilotApi.productFamilies(skuSearch, productBrowseLimit, controller.signal)
        .then((payload) => {
          if (!active) return;
          setCatalog((current) => {
            const merged = new Map(
              current.map((item) => [`${item.source_id}:${item.product_id}`, item]),
            );
            for (const item of payload.items) {
              merged.set(`${item.source_id}:${item.product_id}`, item);
            }
            return [...merged.values()];
          });
        })
        .catch((caught: unknown) => {
          if (active && (caught as { name?: string }).name !== "AbortError") {
            setError(caught instanceof Error ? caught.message : "Product Family catalog is unavailable");
          }
        })
        .finally(() => {
          if (active) setCatalogLoading(false);
        });
    }, 300);
    return () => {
      active = false;
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [skuSearch, productBrowseLimit]);

  const selectedImageModel = capabilities?.image.image_models.find(
    (model) => model.provider_id === imageProviderId && model.model_id === imageModelId,
  ) ?? capabilities?.image.image_models.find(
    (model) => matchesPreferredModel(model.model_id, preferredImageModelId),
  ) ?? capabilities?.image.image_models[0];
  const exactSourceImageTransform = selectedImageModel?.fidelity_mode === "exact_source_transform";

  useEffect(() => {
    const model = capabilities?.image.image_models.find(
      (item) => item.provider_id === imageProviderId && item.model_id === imageModelId,
    )
      ?? capabilities?.image.image_models.find(
        (item) => matchesPreferredModel(item.model_id, preferredImageModelId),
      )
      ?? capabilities?.image.image_models[0];
    if (!model) return;
    if (imageProviderId !== model.provider_id) setImageProviderId(model.provider_id);
    if (imageModelId !== model.model_id) setImageModelId(model.model_id);
    if (!model.supported_resolutions.includes(imageResolution)) {
      setImageResolution(model.supported_resolutions[0]);
    }
    if (model.supported_qualities.length > 0 && !model.supported_qualities.includes(imageQuality)) {
      setImageQuality(model.supported_qualities[0]);
    }
    if (!model.supported_formats.includes(imageFormat)) setImageFormat(model.supported_formats[0]);
    if (model.supported_backgrounds.length && !model.supported_backgrounds.includes(imageBackground)) setImageBackground(model.supported_backgrounds[0]);
    if (model.supported_moderation.length && !model.supported_moderation.includes(imageModeration)) setImageModeration(model.supported_moderation[0]);
    if (model.supported_input_fidelities.length && !model.supported_input_fidelities.includes(imageInputFidelity)) setImageInputFidelity(model.supported_input_fidelities[0]);
  }, [capabilities, imageBackground, imageFormat, imageInputFidelity, imageModelId, imageModeration, imageProviderId, imageQuality, imageResolution]);

  useEffect(() => {
    if (!selectedImageModel) return;
    setImageSizes((current) => Object.fromEntries(
      Object.entries(current).filter(([, size]) => selectedImageModel.supported_image_sizes.includes(size)),
    ) as Partial<Record<CreativeRatio, string>>);
    if (imageFormat === "jpeg" && imageBackground === "transparent") setImageBackground("auto");
  }, [selectedImageModel, imageFormat, imageBackground]);

  useEffect(() => {
    if (
      executionMode === "generate_once"
      && selectedImageModel
      && !selectedImageModel.supports_text_rendering
    ) {
      setImageTextMode("none");
    }
  }, [executionMode, selectedImageModel]);

  const selectedVideoModel = capabilities?.video.models.find(
    (model) => model.model_id === videoModelId,
  ) ?? capabilities?.video.models.find(
    (model) => matchesPreferredModel(model.model_id, preferredVideoModelId),
  ) ?? capabilities?.video.models[0];
  const exactSourceVideoTransform = selectedVideoModel?.fidelity_mode === "exact_source_transform";

  useEffect(() => {
    const model = capabilities?.video.models.find((item) => item.model_id === videoModelId)
      ?? capabilities?.video.models.find(
        (item) => matchesPreferredModel(item.model_id, preferredVideoModelId),
      )
      ?? capabilities?.video.models[0];
    if (!model) return;
    if (videoModelId !== model.model_id) setVideoModelId(model.model_id);
    if (!model.supported_resolutions.includes(videoResolution)) {
      setVideoResolution(model.supported_resolutions[0]);
    }
  }, [capabilities, videoModelId, videoResolution]);

  useEffect(() => {
    if (exactSourceVideoTransform) setVideoGenerateAudio(false);
  }, [exactSourceVideoTransform]);

  useEffect(() => {
    if (!exactSourceImageTransform) return;
    setImageQuantities((current) => capQuantityPerRatio(current, 1));
  }, [exactSourceImageTransform]);

  useEffect(() => {
    if (!exactSourceVideoTransform) return;
    setVideoQuantities((current) => capQuantityPerRatio(current, 1));
  }, [exactSourceVideoTransform]);

  const maximumFinalVideoDuration = capabilities?.video.max_final_duration_seconds ?? 30;

  useEffect(() => {
    if (!capabilities || executionMode === "brief_only") return;
    if (capabilities.image.status === "ready" && selectedImageModel) {
      setImageQuantities((current) => routeQuantities(current, selectedImageModel.supported_aspect_ratios));
    }
    if (capabilities.video.status === "ready" && selectedVideoModel) {
      setVideoQuantities((current) => routeQuantities(current, selectedVideoModel.supported_aspect_ratios));
    }
  }, [capabilities, executionMode, selectedImageModel, selectedVideoModel]);

  const selectionKey = (item: MarketingCreativeProductSelection) =>
    `${item.source_id}:${item.product_id}:${item.selection_scope}:${item.variant_id ?? "family"}`;
  const productKey = (item: ProductFamilyCandidate) => `${item.source_id}:${item.product_id}`;
  const productThumbnail = (item: ProductFamilyCandidate) => item.image_url || item.media[0]?.url || null;
  const variantMedia = (item: ProductFamilyCandidate, variantId: string) => {
    const variant = item.variants.find((candidate) => candidate.variant_id === variantId);
    return item.media.find((candidate) => variant?.media_ids.includes(candidate.media_id))
      ?? item.media.find((candidate) => candidate.variant_ids.includes(variantId));
  };
  const openProductGallery = (item: ProductFamilyCandidate, mediaId?: string) => {
    setPreviewProduct(item);
    setPreviewMediaId(mediaId ?? item.media[0]?.media_id ?? null);
  };
  const selectedItems = selectedProducts
    .map((selection) => catalog.find((item) => item.source_id === selection.source_id && item.product_id === selection.product_id))
    .filter((item): item is ProductFamilyCandidate => item !== undefined);
  const selectedBrand = selectedItems[0]?.brand ?? "";
  useEffect(() => {
    if (!selectedBrand) setVariantReferenceIds({});
  }, [selectedBrand]);
  const variantReferenceTargets: VariantReferenceTarget[] = selectedProducts.flatMap((selection) => {
    const product = catalog.find((item) => item.source_id === selection.source_id && item.product_id === selection.product_id);
    if (!product) return [];
    return product.variants
      .filter((variant) => !selection.variant_id || variant.variant_id === selection.variant_id)
      .map((variant) => ({
        key: `${selection.source_id}:${selection.product_id}:${variant.variant_id}`,
        sourceId: selection.source_id,
        productId: selection.product_id,
        variantId: variant.variant_id,
        label: variant.sku || variant.title,
        detail: `${product.title} · ${Object.values(variant.selected_options).join(" / ") || variant.title}`,
      }));
  });
  const filteredSuggestions = catalog
    .filter((item) => item.brand && (!selectedBrand || item.brand === selectedBrand))
    .filter((item) => {
      const query = skuSearch.trim().toLocaleLowerCase();
      const variants = item.variants.map((variant) => `${variant.sku ?? ""} ${variant.title} ${Object.values(variant.selected_options).join(" ")}`).join(" ");
      return !query || `${item.family_key} ${item.title} ${item.handle} ${variants}`.toLocaleLowerCase().includes(query);
    });
  const imageCount = totalQuantity(imageQuantities);
  const videoCount = totalQuantity(videoQuantities);
  const totalOutputsPerVariant = imageCount + videoCount;
  const variantJobCount = selectedProducts.reduce((total, selection) => {
    if (selection.selection_scope === "variant") return total + 1;
    const family = catalog.find((item) => item.source_id === selection.source_id && item.product_id === selection.product_id);
    return total + (family?.variant_count ?? 0);
  }, 0);
  const totalOutputs = variantJobCount * totalOutputsPerVariant;
  const imageRatios = executionMode === "brief_only" || capabilities?.image.status !== "ready"
    ? creativeRatios
    : selectedImageModel?.supported_aspect_ratios ?? [];
  const videoRatios = executionMode === "brief_only" || capabilities?.video.status !== "ready"
    ? creativeRatios
    : selectedVideoModel?.supported_aspect_ratios ?? [];
  const imageFormats = executionMode === "brief_only" || capabilities?.image.status !== "ready"
    ? ["png", "jpeg", "webp"] as ImageFormat[]
    : selectedImageModel?.supported_formats ?? [];
  const selectedCapabilitiesReady = executionMode === "brief_only" || (
    (imageCount === 0 || capabilities?.image.status === "ready")
    && (videoCount === 0 || capabilities?.video.status === "ready")
  );
  const imageTextSupported = executionMode === "brief_only"
    || Boolean(selectedImageModel?.supports_text_rendering);
  const exactImageTextReady = imageCount === 0 || imageTextMode !== "exact"
    || Boolean(imageHeadline.trim() || imageSubtext.trim() || imageCta.trim());
  const selectedProductMediaReady = selectedProducts.every((selection) => {
    const groups = productMediaGroups(selection);
    return groups.length > 0 && groups.every((group) => group.media.length > 0
      && group.media.some((media) => selection.selected_media_ids.includes(media.media_id)));
  });
  const humanReferenceCapacities = executionMode === "brief_only"
    ? [8]
    : [
      ...(imageCount > 0 && selectedImageModel
        ? [Math.max(0, selectedImageModel.max_reference_images - 1)]
        : []),
      ...(videoCount > 0 && selectedVideoModel
        ? [
          selectedVideoModel.reference_to_video_resolutions.includes(videoResolution)
            ? Math.max(
              0,
              selectedVideoModel.max_reference_images
                - Math.min(2, selectedVideoModel.max_product_images),
            )
            : 0,
        ]
        : []),
    ];
  const maximumHumanReferences = humanReferenceCapacities.length
    ? Math.min(...humanReferenceCapacities)
    : 0;
  const referencesReady = variantReferenceTargets.length > 0
    && variantReferenceTargets.every((target) => {
      const selected = variantReferenceIds[target.key] ?? [];
      return selected.length > 0 && selected.length <= maximumHumanReferences;
    });
  const canSubmit = Boolean(
    selectedBrand
    && agentModelId
    && selectedProducts.length
    && imageCount > 0
    && videoCount > 0
    && variantJobCount > 0
    && selectedCapabilitiesReady
    && selectedProductMediaReady
    && exactImageTextReady
    && referencesReady
    && (imageCount === 0 || executionMode === "brief_only" || Boolean(selectedImageModel))
    && (videoCount === 0 || executionMode === "brief_only" || Boolean(selectedVideoModel))
  );

  const addProduct = (item: ProductFamilyCandidate, variantId?: string) => {
    if (!item.brand) return;
    if (selectedBrand && item.brand !== selectedBrand) {
      setError("Choose Product Families from one brand per run so the Creative context stays grounded.");
      return;
    }
    const selection: MarketingCreativeProductSelection = {
      source_id: item.source_id,
      product_id: item.product_id,
      family_key: item.family_key,
      selection_scope: variantId ? "variant" : "product_family",
      ...(variantId ? { variant_id: variantId } : {}),
      media_selection_mode: "manual",
      selected_media_ids: [],
    };
    if (selectedProducts.some((existing) => selectionKey(existing) === selectionKey(selection))) return;
    setSelectedProducts((items) => {
      const sameFamily = (existing: MarketingCreativeProductSelection) =>
        existing.source_id === selection.source_id && existing.product_id === selection.product_id;
      const retained = selection.selection_scope === "product_family"
        ? items.filter((existing) => !sameFamily(existing))
        : items.filter((existing) => !(sameFamily(existing) && existing.selection_scope === "product_family"));
      return [...retained, selection];
    });
    setSkuSearch("");
    setProductPickerOpen(false);
    setError("");
  };

  const eligibleProductMedia = (selection: MarketingCreativeProductSelection) => {
    const item = catalog.find((candidate) => candidate.source_id === selection.source_id && candidate.product_id === selection.product_id);
    return item?.media.filter((media) => !selection.variant_id || media.variant_ids.length === 0 || media.variant_ids.includes(selection.variant_id)) ?? [];
  };

  function productMediaGroups(selection: MarketingCreativeProductSelection) {
    const item = catalog.find((candidate) => candidate.source_id === selection.source_id && candidate.product_id === selection.product_id);
    if (!item) return [];
    const variants = selection.variant_id
      ? item.variants.filter((variant) => variant.variant_id === selection.variant_id)
      : item.variants;
    if (selection.variant_id && !variants.length) return [];
    if (!variants.length) {
      return [{ key: "family", label: t("Product Family"), detail: item.family_key, media: item.media }];
    }
    return variants.map((variant) => ({
      key: variant.variant_id,
      label: variant.sku || variant.title,
      detail: Object.values(variant.selected_options).join(" / ") || variant.title,
      media: item.media.filter((media) => media.variant_ids.length === 0 || media.variant_ids.includes(variant.variant_id)),
    }));
  }

  const toggleProductMedia = (selection: MarketingCreativeProductSelection, mediaId: string) => {
    setSelectedProducts((items) => items.map((item) => {
      if (selectionKey(item) !== selectionKey(selection)) return item;
      const selectedMediaIds = item.selected_media_ids.includes(mediaId)
        ? item.selected_media_ids.filter((id) => id !== mediaId)
        : [...item.selected_media_ids, mediaId];
      return { ...item, selected_media_ids: selectedMediaIds };
    }));
  };

  const toggleVariantReference = (targetKey: string, referenceId: string) => {
    setVariantReferenceIds((current) => {
      const selected = current[targetKey] ?? [];
      return {
        ...current,
        [targetKey]: selected.includes(referenceId)
          ? selected.filter((item) => item !== referenceId)
          : [...selected, referenceId],
      };
    });
  };

  const uploadVariantReference = async (targetKey: string, file: File) => {
    if (!{"image/png": true, "image/jpeg": true, "image/webp": true}[file.type]) {
      setReferenceUploadErrors((current) => ({
        ...current,
        [targetKey]: t("Upload a PNG, JPEG or WebP image."),
      }));
      return;
    }
    const selected = variantReferenceIds[targetKey] ?? [];
    if (selected.length >= maximumHumanReferences) {
      setReferenceUploadErrors((current) => ({
        ...current,
        [targetKey]: t("The selected model has no remaining reference image slot."),
      }));
      return;
    }
    setReferenceUploadErrors((current) => ({ ...current, [targetKey]: "" }));
    setReferenceUploadProgress((current) => ({ ...current, [targetKey]: 0 }));
    try {
      const asset = await pilotApi.uploadMediaAsset(file, "image", (progress) => {
        setReferenceUploadProgress((current) => ({ ...current, [targetKey]: progress }));
      });
      const referenceId = `upload:${asset.asset_id}`;
      const option: CreativeReferenceOption = {
        referenceId,
        title: file.name,
        previewUrl: asset.preview_url,
      };
      setUploadedReferenceOptions((current) => ({
        ...current,
        [targetKey]: [
          ...(current[targetKey] ?? []).filter((item) => item.referenceId !== referenceId),
          option,
        ],
      }));
      setVariantReferenceIds((current) => ({
        ...current,
        [targetKey]: [...new Set([...(current[targetKey] ?? []), referenceId])],
      }));
    } catch (caught) {
      setReferenceUploadErrors((current) => ({
        ...current,
        [targetKey]: caught instanceof Error ? caught.message : t("Reference image upload failed."),
      }));
    } finally {
      setReferenceUploadProgress((current) => ({ ...current, [targetKey]: null }));
    }
  };

  const applyVariantReferencesToAll = (sourceKey: string) => {
    const selected = variantReferenceIds[sourceKey] ?? [];
    if (!selected.length) return;
    const uploaded = (uploadedReferenceOptions[sourceKey] ?? []).filter((item) => (
      selected.includes(item.referenceId)
    ));
    setVariantReferenceIds(Object.fromEntries(
      variantReferenceTargets.map((target) => [target.key, selected]),
    ));
    if (uploaded.length > 0) {
      setUploadedReferenceOptions((current) => Object.fromEntries(
        variantReferenceTargets.map((target) => [
          target.key,
          [
            ...(current[target.key] ?? []).filter((item) => (
              !uploaded.some((source) => source.referenceId === item.referenceId)
            )),
            ...uploaded,
          ],
        ]),
      ));
    }
  };


  const submit = async () => {
    if (!canSubmit) return;
    setLoading(true); setError(""); setResult(null);
    try {
      const variantReferenceAssignments = variantReferenceTargets.map((target) => ({
        source_id: target.sourceId,
        product_id: target.productId,
        variant_id: target.variantId,
        reference_ids: variantReferenceIds[target.key] ?? [],
      }));
      const selectedReferenceIds = [...new Set(
        variantReferenceAssignments.flatMap((assignment) => assignment.reference_ids),
      )];
      const payload = await pilotApi.createMarketingCreativeAutomation({
        product_selections: selectedProducts,
        brand: selectedBrand,
        platform: "meta",
        objective: "conversion",
        agent_model_id: agentModelId,
        agent_reasoning_effort: agentReasoningEffort,
        image_count: imageCount,
        video_count: videoCount,
        ...(imageCount > 0 && selectedImageModel ? {
          image_provider_id: selectedImageModel.provider_id,
          image_model_id: selectedImageModel.model_id,
          image_resolution: imageResolution,
          image_quality: selectedImageModel.supported_qualities.length ? imageQuality : undefined,
          image_background: selectedImageModel.supported_backgrounds.length ? imageBackground : undefined,
          image_moderation: selectedImageModel.supported_moderation.length ? imageModeration : undefined,
          image_input_fidelity: selectedImageModel.supported_input_fidelities.length ? imageInputFidelity : undefined,
          image_output_compression: selectedImageModel.supports_output_compression && imageFormat !== "png" ? imageOutputCompression : undefined,
        } : {}),
        ...(videoCount > 0 && selectedVideoModel ? {
          video_model_id: selectedVideoModel.model_id,
          video_resolution: videoResolution,
          video_duration_seconds: videoDurationSeconds,
          video_generate_audio: exactSourceVideoTransform ? false : videoGenerateAudio,
        } : {}),
        execution_mode: executionMode,
        aspect_ratio: outputProfiles("video", videoQuantities)[0]?.aspect_ratio ?? outputProfiles("image", imageQuantities, imageFormat)[0]?.aspect_ratio ?? "9:16",
        output_profiles: [
          ...outputProfiles("image", imageQuantities, imageFormat, imageSizes),
          ...outputProfiles("video", videoQuantities),
        ],
        sku_tier: "overflow",
        requested_by: launcherRequestedBy,
        include_text: imageCount > 0 && imageTextMode !== "none",
        ...(imageCount > 0 && imageTextMode === "exact" ? {
          headline: imageHeadline.trim() || undefined,
          subtext: imageSubtext.trim() || undefined,
          cta_text: imageCta.trim() || undefined,
        } : {}),
        notes: otherContext.trim() || undefined,
        brand_instructions: otherContext.trim() || undefined,
        human_hooks: [],
        human_claims: [],
        include_logo: false,
        use_research_references: true,
        reference_selection_mode: "human",
        selected_reference_ids: selectedReferenceIds,
        output_reference_assignments: [],
        variant_reference_assignments: variantReferenceAssignments,
        creative_set_strategy: "single",
        high_brand_risk: false,
        automation_override: false,
        idempotency_key: globalThis.crypto?.randomUUID?.() ?? `marketing-${Date.now()}`,
      });
      setResult(payload);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Creative automation could not start");
    } finally {
      setLoading(false);
    }
  };

  const renderProfiles = (
    mediaKind: "image" | "video",
    quantities: OutputQuantities,
    setQuantities: (value: OutputQuantities | ((current: OutputQuantities) => OutputQuantities)) => void,
    supportedRatios: readonly CreativeRatio[],
    exactSource: boolean,
  ) => {
    const configuredRatios = creativeRatios.filter((ratio) => quantities[ratio] > 0);
    const maximumForRatio = exactSource ? 1 : maximumOutputsPerMediaKind;
    return <fieldset className="automation-profile-editor">
      <legend>{t(mediaKind === "image" ? "Image output profiles" : "Video output profiles")}</legend>
      {configuredRatios.length === 0 && <p className="muted-copy">{t("No output profile selected.")}</p>}
      {configuredRatios.map((ratio) => {
        const availableRatios = supportedRatios.filter((candidate) => candidate === ratio || quantities[candidate] === 0);
        const remaining = maximumOutputsPerMediaKind - (totalQuantity(quantities) - quantities[ratio]);
        return <div className="automation-profile-row" key={`${mediaKind}-${ratio}`}>
          <label><span>{t("Placement / ratio")}</span><select aria-label={t(`${mediaKind === "image" ? "Image" : "Video"} placement and ratio`)} value={ratio} onChange={(event) => setQuantities((current) => moveOutputProfile(current, ratio, event.target.value as CreativeRatio))}>{availableRatios.map((candidate) => <option key={candidate} value={candidate}>{t(ratioLabel(candidate))} · {candidate}</option>)}</select></label>
          <label><span>{t("Quantity")}</span><select aria-label={t(`${mediaKind === "image" ? "Image" : "Video"} quantity`)} value={quantities[ratio]} onChange={(event) => setQuantities((current) => updateQuantity(current, ratio, event.target.value, maximumForRatio))}>{Array.from({ length: Math.min(maximumForRatio, remaining) }, (_, index) => index + 1).map((count) => <option key={count} value={count}>{count}</option>)}</select></label>
          {mediaKind === "image" && selectedImageModel && selectedImageModel.supported_image_sizes.length > 0 && <label><span>{t("Size")}</span><select value={imageSizes[ratio] && selectedImageModel.supported_image_sizes.includes(imageSizes[ratio]) ? imageSizes[ratio] : ""} onChange={(event) => setImageSizes((current) => ({ ...current, [ratio]: event.target.value }))}><option value="">{t("Auto")}</option>{selectedImageModel.supported_image_sizes.filter((size) => { const [width, height] = size.split("x").map(Number); const [rw, rh] = ratio.split(":").map(Number); return width * rh === height * rw; }).map((size) => <option key={size} value={size}>{size}</option>)}</select></label>}
          <button type="button" className="secondary-button" onClick={() => setQuantities((current) => ({ ...current, [ratio]: 0 }))}>{t("Remove")}</button>
        </div>;
      })}
      {configuredRatios.length < supportedRatios.length && totalQuantity(quantities) < maximumOutputsPerMediaKind && <button type="button" className="secondary-button" onClick={() => setQuantities((current) => addOutputProfile(current, supportedRatios))}>{t(mediaKind === "image" ? "Add image profile" : "Add video profile")}</button>}
    </fieldset>;
  };

  return <Panel className="automation-launcher">
    <PanelHeader title={t("Create Creative for a Product or Variant")} action={<Badge tone="info"><Sparkles size={13} /> {t("Marketing automation")}</Badge>} />
    <div className={`automation-launcher__layout ${outputSplit.active ? "split-active" : ""}`} style={outputSplit.style}>
      <section className="automation-launcher__main">
        <div className="automation-sku-picker">
          <label><span>{t("1. Choose a Product or Variant")}</span><div className="automation-sku-input"><input role="combobox" aria-expanded={productPickerOpen && filteredSuggestions.length > 0} aria-controls="creative-product-options" value={skuSearch} onFocus={() => setProductPickerOpen(true)} onClick={() => setProductPickerOpen(true)} onChange={(event) => { setSkuSearch(event.target.value); setProductPickerOpen(true); }} placeholder={t("Search SKU, product name, or Variant")} /></div></label>
          {selectedProducts.length > 0 && <div className="automation-selected-skus">{selectedProducts.map((selection) => <button type="button" key={selectionKey(selection)} onClick={() => setSelectedProducts((items) => items.filter((item) => selectionKey(item) !== selectionKey(selection)))}>{selection.family_key}{selection.variant_id ? ` / ${selection.variant_id}` : ` / ${t("Entire family")}`}<span aria-hidden="true">x</span></button>)}</div>}
          {selectedBrand && <p className="muted-copy">{t("Brand from Shopify")}: <strong>{selectedBrand}</strong></p>}
          {productPickerOpen && catalogLoading && <p className="muted-copy" role="status">{t("Loading Products and Variants…")}</p>}
          {filteredSuggestions.length > 0 && <details id="creative-product-options" className="automation-product-options" open={productPickerOpen} onToggle={(event) => setProductPickerOpen(event.currentTarget.open)}><summary>{t("Browse matching Products")} ({filteredSuggestions.length})</summary><div className="automation-suggestions"><div className="automation-product-browser-toolbar"><span>{t("Available from synchronized Shopify Product data")}</span><label><span>{t("Show")}</span><select aria-label={t("Products shown")} value={productBrowseLimit} onChange={(event) => setProductBrowseLimit(Number(event.target.value))}>{[12, 24, 48, 100, 500].map((limit) => <option key={limit} value={limit}>{limit}</option>)}</select></label></div><div className="automation-product-browser">{filteredSuggestions.map((item) => {
            const key = productKey(item);
            const expanded = expandedProductKey === key;
            const familySelected = selectedProducts.some((selection) => selection.source_id === item.source_id && selection.product_id === item.product_id && selection.selection_scope === "product_family");
            const selectedVariantIds = new Set(selectedProducts.filter((selection) => selection.source_id === item.source_id && selection.product_id === item.product_id && selection.variant_id).map((selection) => selection.variant_id));
            const thumbnail = productThumbnail(item);
            return <div className="automation-product-browser-item" key={key}>
              <article className={`automation-product-card${expanded ? " is-expanded" : ""}${familySelected || selectedVariantIds.size ? " is-selected" : ""}`}>
                <button type="button" className="automation-product-card__summary" aria-expanded={expanded} aria-controls={`variants-${item.product_id}`} onClick={() => setExpandedProductKey(expanded ? null : key)}>
                  {thumbnail ? <img src={thumbnail} alt="" loading="lazy" referrerPolicy="no-referrer" /> : <span className="automation-product-thumbnail-placeholder"><Image size={20} aria-hidden="true" /></span>}
                  <span><strong>{item.title}</strong><small>{t("Product code")}: {item.family_key}</small><small>{item.variant_count} {t("variants")} · {item.brand}</small></span>
                  <span className="automation-product-card__toggle" aria-hidden="true">⌄</span>
                </button>
                <footer>
                  <button type="button" className={familySelected ? "is-selected" : ""} disabled={familySelected} onClick={() => addProduct(item)}>{familySelected ? t("Entire product selected") : t("Select entire product")}</button>
                  <button type="button" disabled={item.media.length === 0} onClick={() => openProductGallery(item)}>{t(item.media.length ? "View images" : "No images")}</button>
                  <button type="button" onClick={() => setExpandedProductKey(expanded ? null : key)}>{expanded ? t("Hide variants") : t("View variants")}</button>
                </footer>
              </article>
              {expanded && <section className="automation-variant-browser" id={`variants-${item.product_id}`}>
                <header><div><strong>{item.title}</strong><small>{t("Choose the exact Variant or select the entire Product above.")}</small></div><span>{item.variant_count} {t("variants")}</span></header>
                <div>{item.variants.map((variant) => {
                  const variantSelected = selectedVariantIds.has(variant.variant_id);
                  const variantImage = variantMedia(item, variant.variant_id);
                  const variantImageUrl = variantImage?.url || productThumbnail(item);
                  const options = Object.values(variant.selected_options).join(" / ") || variant.title;
                  const selectionDisabled = variantSelected || familySelected;
                  return <button type="button" className={variantSelected ? "is-selected" : ""} aria-disabled={selectionDisabled} key={variant.variant_id} onClick={() => {
                    if (!selectionDisabled) addProduct(item, variant.variant_id);
                  }}>
                    {variantImageUrl ? <img
                      src={variantImageUrl}
                      alt={variantImage?.alt || `${options} ${t("Product image")}`}
                      loading="lazy"
                      referrerPolicy="no-referrer"
                      role={item.media.length ? "button" : undefined}
                      tabIndex={item.media.length ? 0 : undefined}
                      aria-label={item.media.length ? t("View image") : undefined}
                      onClick={(event) => {
                        if (!item.media.length) return;
                        event.preventDefault();
                        event.stopPropagation();
                        openProductGallery(item, variantImage?.media_id);
                      }}
                      onKeyDown={(event) => {
                        if (!item.media.length || (event.key !== "Enter" && event.key !== " ")) return;
                        event.preventDefault();
                        event.stopPropagation();
                        openProductGallery(item, variantImage?.media_id);
                      }}
                    /> : <span className="automation-product-thumbnail-placeholder"><Image size={18} aria-hidden="true" /></span>}
                    <span><strong>{options}</strong><small>{variant.sku ? `${t("Variant SKU")}: ${variant.sku}` : `${t("Variant ID")}: ${variant.variant_id}`}</small>{variant.price && <small>{variant.price} {variant.currency}</small>}</span>
                    <span>{familySelected ? t("Included in Product") : variantSelected ? t("Selected") : t("Select Variant")}</span>
                  </button>;
                })}</div>
              </section>}
            </div>;
          })}</div></div></details>}
          {productPickerOpen && !catalogLoading && filteredSuggestions.length === 0 && <p className="muted-copy" role="status">{t("No matching Products or Variants.")}</p>}
          {selectedProducts.map((selection) => {
            const product = catalog.find((item) => item.source_id === selection.source_id && item.product_id === selection.product_id);
            const productMedia = eligibleProductMedia(selection);
            const mediaGroups = productMediaGroups(selection);
            return <section className="automation-source-picker" key={`media:${selectionKey(selection)}`}>
              <header><div><strong>{t("Shopify product images")}</strong><small>{selection.family_key}{selection.variant_id ? ` / ${selection.variant_id}` : ` / ${t("Entire family")}`}</small></div><span>{productMedia.length} {t("images available")}</span></header>
              <p className="automation-media-mode-help">{t("The images you check define the allowed set. Each Variant must retain at least one eligible image.")}</p>
              <div className="automation-variant-media-groups">{mediaGroups.map((group) => {
                const featuredMediaId = [...group.media].sort((left, right) => {
                  const leftPriority = left.variant_ids.includes(group.key) ? 0 : 1;
                  const rightPriority = right.variant_ids.includes(group.key) ? 0 : 1;
                  return leftPriority - rightPriority || left.position - right.position || left.media_id.localeCompare(right.media_id);
                })[0]?.media_id;
                const hasManualSelection = group.media.some((media) => selection.selected_media_ids.includes(media.media_id));
                return <section className="automation-variant-media-group" key={group.key}>
                  <header><div><strong>{group.label}</strong><small>{group.detail}</small></div><span>{group.media.length} {t("eligible images")}</span></header>
                  <div className="automation-source-grid">{group.media.map((media) => {
                    const selected = selection.selected_media_ids.includes(media.media_id);
                    const content = <><img
                      src={media.url}
                      alt={media.alt || selection.family_key}
                      loading="lazy"
                      referrerPolicy="no-referrer"
                      role="button"
                      tabIndex={0}
                      aria-label={t("View image")}
                      onClick={(event) => {
                        event.preventDefault();
                        event.stopPropagation();
                        if (product) openProductGallery(product, media.media_id);
                      }}
                      onKeyDown={(event) => {
                        if (event.key !== "Enter" && event.key !== " ") return;
                        event.preventDefault();
                        event.stopPropagation();
                        if (product) openProductGallery(product, media.media_id);
                      }}
                    /><span>{media.alt || `${t("Product view")} ${media.position}`}<small>{media.media_id === featuredMediaId ? `${t("Featured")} · ` : ""}Shopify media {media.position}</small></span></>;
                    return <label className={selected ? "selected" : ""} key={media.media_id}><input type="checkbox" checked={selected} onChange={() => toggleProductMedia(selection, media.media_id)} />{content}</label>;
                  })}</div>
                  {!hasManualSelection && <small className="form-error">{t("Select at least one image for this Variant.")}</small>}
                </section>;
              })}</div>
              {productMedia.length === 0 && <small className="form-error">{t("No Shopify product image is mapped to this selection.")}</small>}
            </section>;
          })}
        </div>
        <label className="automation-notes"><span>{t("2. Additional requirements (optional)")}</span><AutoResizeTextarea rows={3} value={otherContext} onChange={(event) => setOtherContext(event.target.value)} placeholder={t("Add any special brand direction, audience, angle, hooks, offer, claims, or constraints here.")} /></label>
        <section className="automation-reference-picker">
          <p className="eyebrow">{t("3. Upload visual references")}</p>
          <p className="muted-copy">{t("Upload at least one reference for each Variant. The Agent uses it as visual direction and completes the creative approach automatically.")}</p>
          <div className="automation-variant-media-groups">{variantReferenceTargets.map((target, index) => {
                  const selectedIds = variantReferenceIds[target.key] ?? [];
                  const referenceOptions = uploadedReferenceOptions[target.key] ?? [];
                  const uploadProgress = referenceUploadProgress[target.key];
                  const uploadError = referenceUploadErrors[target.key];
                  const targetReady = selectedIds.length > 0 && selectedIds.length <= maximumHumanReferences;
                  return <details className="automation-variant-media-group automation-reference-variant" key={target.key} open={variantReferenceTargets.length === 1 || index === 0}>
                    <summary><strong>{target.label}</strong><small>{target.detail} · {selectedIds.length} {t("selected")}</small></summary>
                      <div className="automation-reference-upload">
                        <div><strong>{t("Upload your own reference")}</strong><small>{t("PNG, JPEG or WebP. The image is attached only to this Variant unless you apply the decision to all.")}</small></div>
                        <label className={`secondary-button${uploadProgress !== null && uploadProgress !== undefined ? " disabled" : ""}`}>
                          <Upload size={15} />
                          <span>{uploadProgress !== null && uploadProgress !== undefined ? t("Uploading {count}%").replace("{count}", String(uploadProgress)) : t("Choose image")}</span>
                          <input
                            type="file"
                            accept="image/png,image/jpeg,image/webp"
                            disabled={(uploadProgress !== null && uploadProgress !== undefined) || selectedIds.length >= maximumHumanReferences}
                            onChange={(event) => {
                              const file = event.target.files?.[0];
                              event.target.value = "";
                              if (file) void uploadVariantReference(target.key, file);
                            }}
                          />
                        </label>
                      </div>
                      {uploadError && <small className="form-error">{uploadError}</small>}
                      <div className="automation-reference-grid">{referenceOptions.map((reference) => {
                        const selected = selectedIds.includes(reference.referenceId);
                        return <label className={`automation-reference-card${selected ? " is-selected" : ""}`} key={`${target.key}:${reference.referenceId}`}>
                          <input type="checkbox" checked={selected} disabled={!selected && selectedIds.length >= maximumHumanReferences} onChange={() => toggleVariantReference(target.key, reference.referenceId)} />
                          <img src={reference.previewUrl} alt={reference.title} loading="lazy" />
                          <span><strong>{t("Uploaded reference")}</strong><small>{reference.title}</small></span>
                        </label>;
                      })}</div>
                    {selectedIds.length > 0 && variantReferenceTargets.length > 1 && <button type="button" className="secondary-button" onClick={() => applyVariantReferencesToAll(target.key)}>{t("Apply these references to all Variants")}</button>}
                    {!targetReady && <small className="form-error">{maximumHumanReferences === 0 ? t("The selected models have no input slot for a direct visual reference.") : t("Upload and select between 1 and {count} references.").replace("{count}", String(maximumHumanReferences))}</small>}
                  </details>;
                })}</div>
          {!referencesReady && variantReferenceTargets.length === 0 && <small className="form-error">{t("Choose a Product or Variant before uploading references.")}</small>}
        </section>
      </section>
      <aside ref={outputPanelRef} className="automation-output-card">
        <SplitHandle label="Resize output settings" {...outputSplit.handleProps} />
        <details className="automation-output-settings">
          <summary><span>{t("4. Output per Variant")}</span><small>{imageCount} {t("image outputs")} · {videoCount} {t("video outputs")} · {videoDurationSeconds}s</small></summary>
          <div className="automation-output-settings__body">
        {capabilities?.agent_models.length ? <div className="automation-brand-copy-fields automation-agent-fields">
          <label className="automation-select-field"><span>{t("Agent model")}</span><select value={agentModelId} onChange={(event) => setAgentModelId(event.target.value)}>{capabilities.agent_models.map((model) => <option key={model} value={model}>{model.replace("gemini/", "")}</option>)}</select></label>
          {agentReasoningLevels.length > 0 && <label><span>{t("Reasoning effort")}</span><select value={agentReasoningEffort} onChange={(event) => setAgentReasoningEffort(event.target.value as typeof agentReasoningEffort)}>{agentReasoningLevels.map((level) => <option key={level} value={level}>{t(level)}</option>)}</select></label>}
        </div> : null}
        <p className="automation-profile-summary">{t("Start creates both images and videos, plus the detailed brief.")}</p>
        <details className="automation-output-section" open><summary><span><Image size={16} /> {t("Images")}</span><small>{imageCount}/{maximumOutputsPerMediaKind} · {t(quantitySummary(imageQuantities))} · {imageFormat.toUpperCase()}</small></summary>
          {executionMode === "generate_once" && capabilities?.image.image_models.length ? <div className="automation-brand-copy-fields">
            <label><span>{t("Image model")}</span><select value={selectedImageModel ? `${selectedImageModel.provider_id}|${selectedImageModel.model_id}` : ""} onChange={(event) => { const [providerId, ...modelParts] = event.target.value.split("|"); setImageProviderId(providerId); setImageModelId(modelParts.join("|")); }}>{capabilities.image.image_models.map((model) => <option key={`${model.provider_id}:${model.model_id}`} value={`${model.provider_id}|${model.model_id}`}>{model.fidelity_mode === "exact_source_transform" ? t("Exact Shopify source") : model.display_name}</option>)}</select></label>
            {selectedImageModel && <>
              <label><span>{t("Resolution")}</span><select value={imageResolution} onChange={(event) => setImageResolution(event.target.value as "1k" | "1.5k" | "2k")}>{selectedImageModel.supported_resolutions.map((resolution) => <option key={resolution} value={resolution}>{resolution.toUpperCase()}</option>)}</select></label>
              {selectedImageModel.supported_qualities.length > 0 && <label><span>{t("Quality")}</span><select value={imageQuality} onChange={(event) => setImageQuality(event.target.value as typeof imageQuality)}>{selectedImageModel.supported_qualities.map((quality) => <option key={quality} value={quality}>{t(quality)}</option>)}</select></label>}
              <label><span>{t("File format")}</span><select value={imageFormat} onChange={(event) => setImageFormat(event.target.value as ImageFormat)}>{imageFormats.map((format) => <option key={format} value={format}>{format.toUpperCase()}</option>)}</select></label>
              {selectedImageModel.supported_backgrounds.length > 0 && <label><span>{t("Background")}</span><select value={imageBackground} onChange={(event) => setImageBackground(event.target.value as typeof imageBackground)}>{selectedImageModel.supported_backgrounds.filter((value) => value !== "transparent" || imageFormat !== "jpeg").map((value) => <option key={value} value={value}>{t(value)}</option>)}</select></label>}
              {selectedImageModel.supported_moderation.length > 0 && <label><span>{t("Moderation")}</span><select value={imageModeration} onChange={(event) => setImageModeration(event.target.value as typeof imageModeration)}>{selectedImageModel.supported_moderation.map((value) => <option key={value} value={value}>{t(value)}</option>)}</select></label>}
              {selectedImageModel.supported_input_fidelities.length > 0 && <label><span>{t("Input fidelity")}</span><select value={imageInputFidelity} onChange={(event) => setImageInputFidelity(event.target.value as typeof imageInputFidelity)}>{selectedImageModel.supported_input_fidelities.map((value) => <option key={value} value={value}>{t(value)}</option>)}</select></label>}
              {selectedImageModel.supports_output_compression && imageFormat !== "png" && <label><span>{t("Output compression")}</span><input type="number" min={0} max={100} value={imageOutputCompression} onChange={(event) => setImageOutputCompression(Number(event.target.value))} /></label>}
            </>}
          </div> : null}
          <div className="automation-brand-copy-fields">
            <label><span>{t("Text in image")}</span><select value={imageTextMode} onChange={(event) => setImageTextMode(event.target.value as "none" | "agent" | "exact")}><option value="none">{t("No text")}</option>{imageTextSupported && <option value="agent">{t("Let Agent write")}</option>}{imageTextSupported && <option value="exact">{t("Use exact text")}</option>}</select></label>
            {imageTextMode === "exact" && imageTextSupported && <>
              <label><span>{t("Headline")}</span><input value={imageHeadline} onChange={(event) => setImageHeadline(event.target.value)} placeholder={t("Exact headline (optional)")} /></label>
              <label><span>{t("Supporting text")}</span><input value={imageSubtext} onChange={(event) => setImageSubtext(event.target.value)} placeholder={t("Exact supporting text (optional)")} /></label>
              <label><span>{t("Call to action")}</span><input value={imageCta} onChange={(event) => setImageCta(event.target.value)} placeholder={t("Exact CTA (optional)")} /></label>
              {!exactImageTextReady && <small className="form-error">{t("Enter at least one exact text field.")}</small>}
            </>}
          </div>
          {renderProfiles("image", imageQuantities, setImageQuantities, imageRatios, Boolean(exactSourceImageTransform))}
        </details>
        <details className="automation-output-section"><summary><span><Video size={16} /> {t("Videos")}</span><small>{videoCount}/{maximumOutputsPerMediaKind} · {t(quantitySummary(videoQuantities))}</small></summary>
          {executionMode === "generate_once" && capabilities?.video.models.length ? <div className="automation-brand-copy-fields">
            <label><span>{t("Video model")}</span><select value={selectedVideoModel?.model_id ?? ""} onChange={(event) => setVideoModelId(event.target.value)}>{capabilities.video.models.map((model) => <option key={model.model_id} value={model.model_id}>{model.display_name}</option>)}</select></label>
            {selectedVideoModel && <>
              <label><span>{t("Resolution")}</span><select value={videoResolution} onChange={(event) => setVideoResolution(event.target.value as "480p" | "720p" | "1080p")}>{selectedVideoModel.supported_resolutions.map((resolution) => <option key={resolution} value={resolution}>{resolution}</option>)}</select></label>
              <label><span>{t("Final video duration")}</span><select value={videoDurationSeconds} onChange={(event) => setVideoDurationSeconds(Number(event.target.value))}>{Array.from({ length: Math.min(30, maximumFinalVideoDuration) }, (_, index) => index + 1).map((seconds) => <option key={seconds} value={seconds}>{seconds} {t("seconds")}</option>)}</select></label>
              {(selectedVideoModel.supports_native_voice || selectedVideoModel.supports_native_music) && <div className="automation-ingredient-toggles"><label><input type="checkbox" checked={videoGenerateAudio} onChange={(event) => setVideoGenerateAudio(event.target.checked)} /><span><strong>{t("Generate audio")}</strong></span></label></div>}
            </>}
          </div> : null}
          {renderProfiles("video", videoQuantities, setVideoQuantities, videoRatios, Boolean(exactSourceVideoTransform))}
        </details>
        <p className="automation-profile-summary">{imageCount} {t("image outputs")} / {videoCount} {t("video outputs")} {t("per Variant")} / {variantJobCount} {t("Variant jobs")} / {totalOutputs} {t("total outputs")}</p>
        {(imageCount === 0 || videoCount === 0) && <small className="form-error">{t("Configure at least one image and one video per Variant.")}</small>}
          </div>
        </details>
        <p className="automation-profile-summary">{t("Start runs production without another approval step. Finished outputs appear automatically in Creative Library.")}</p>
        <button className="approve-button automation-start" disabled={loading || !canSubmit} onClick={() => void submit()}>{loading ? t("Preparing…") : `${t("Start")} ${variantJobCount || ""} ${t("Variant jobs")}`}</button>
      </aside>
    </div>
    {previewProduct && (() => {
      const activeMedia = previewProduct.media.find((media) => media.media_id === previewMediaId) ?? previewProduct.media[0];
      return <Modal title="Product image gallery" onClose={() => setPreviewProduct(null)} className="automation-product-gallery-dialog">
        <div className="automation-product-gallery-main">
          {activeMedia && <img src={activeMedia.url} alt={activeMedia.alt || previewProduct.title} referrerPolicy="no-referrer" />}
          <div><strong>{previewProduct.title}</strong><small>{t("Product code")}: {previewProduct.family_key}</small>{activeMedia && <small>{activeMedia.alt || `${t("Product view")} ${activeMedia.position}`} · Shopify media {activeMedia.position}</small>}</div>
        </div>
        <div className="automation-product-gallery-thumbnails" aria-label={t("Product images")}>{previewProduct.media.map((media, index) => <button type="button" className={media.media_id === activeMedia?.media_id ? "is-selected" : ""} aria-label={`${t("View image")} ${index + 1}`} key={media.media_id} onClick={() => setPreviewMediaId(media.media_id)}><img src={media.url} alt={media.alt || `${previewProduct.title} ${index + 1}`} loading="lazy" referrerPolicy="no-referrer" /><span>{index + 1}</span></button>)}</div>
      </Modal>;
    })()}
    {error && <p className="form-error" role="alert">{error}</p>}
    {result && <p className="automation-created" role="status"><Check size={15} /> {result.total} {t("independent jobs created")}. <Link to="/creatives?view=media">{t("Open Creative Library")}</Link></p>}
  </Panel>;
}
function CreativeClosedLoopPilot() {
  const { t, formatDate } = useI18n();
  const [params] = useSearchParams();
  const requestedRunId = params.get("loop");
  const [runs, setRuns] = useState<CreativeLoopRun[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [timeline, setTimeline] = useState<CreativeLoopTimeline | null>(null);
  const [reason, setReason] = useState("");
  const [reviewer, setReviewer] = useState("");
  const [loopWarning, setLoopWarning] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [commands, setCommands] = useState<ExecutionCommand[]>([]);
  const activeCommandRef = useRef<ExecutionCommand | null>(null);
  useEffect(() => {
    activeCommandRef.current = commands.find((command) => ["pending", "running", "retry_wait", "cancel_requested"].includes(command.status)) ?? null;
  }, [commands]);

  const loadTimeline = async (runId: string) => {
    const payload = await pilotApi.creativeLoopTimeline<CreativeLoopTimeline>(runId);
    setTimeline(payload);
    setRuns((items) => items.map((item) => item.run_id === payload.run.run_id ? payload.run : item));
  };

  const loadCommands = async (runId: string) => {
    const payload = await pilotApi.creativeLoopCommands<ExecutionCommand>(runId);
    setCommands(payload.items);
  };

  useEffect(() => {
    const controller = new AbortController();
    pilotApi.creativeLoops<CreativeLoopRun>(controller.signal)
      .then((payload) => {
        setRuns(payload.items);
        const requested = payload.items.find((item) => item.run_id === requestedRunId);
        setSelectedId(requested?.run_id ?? payload.items[0]?.run_id ?? null);
        setLoopWarning(
          requested || !requestedRunId || payload.items.length === 0
            ? ""
            : "Requested workflow is not available. Showing the latest persisted run instead."
        );
        setError("");
      })
      .catch((caught: unknown) => {
        if ((caught as { name?: string }).name !== "AbortError") setError(caught instanceof Error ? caught.message : "Creative loop API unavailable");
      });
    return () => controller.abort();
  }, [requestedRunId]);

  const terminalStates = new Set(["next_brief_ready", "completed", "rejected", "deferred"]);
  const isTerminal = terminalStates.has(timeline?.run.state ?? "");
  useEffect(() => {
    if (!selectedId) { setTimeline(null); setCommands([]); return; }
    const refresh = () => Promise.all([loadTimeline(selectedId), loadCommands(selectedId)]).catch((caught: unknown) => setError(caught instanceof Error ? caught.message : "Creative loop execution unavailable"));
    void refresh();
    if (isTerminal) return;
    const timer = window.setInterval(() => {
      if (document.visibilityState === "hidden" || activeCommandRef.current) return;
      void refresh();
    }, 2000);
    return () => window.clearInterval(timer);
  }, [selectedId, isTerminal]);

  const post = async (path: string, body?: object) => {
    if (!timeline) return;
    setSaving(true); setError("");
    try {
      const payload = await pilotApi.postCreativeLoop<{ command: ExecutionCommand }>(timeline.run.run_id, path, body);
      setCommands((items) => [payload.command, ...items.filter((item) => item.command_id !== payload.command.command_id)]);
      setReason("");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Creative loop action failed");
    } finally {
      setSaving(false);
    }
  };

  const retryCommand = async (commandId: string) => {
    setSaving(true); setError("");
    try {
      await pilotApi.retryExecutionCommand<ExecutionCommand>(commandId);
      if (selectedId) await loadCommands(selectedId);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Execution command retry failed");
    } finally {
      setSaving(false);
    }
  };

  const cancelCommand = async (commandId: string) => {
    setSaving(true); setError("");
    try {
      await pilotApi.cancelExecutionCommand<ExecutionCommand>(commandId);
      if (selectedId) await loadCommands(selectedId);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Execution command cancellation failed");
    } finally {
      setSaving(false);
    }
  };

  if (error && !runs.length) return <Panel className="mkt-issue-panel"><PanelHeader title="Creative Closed Loop API not connected" meta="Check the API and worker services." /><p>{error}</p></Panel>;
  if (!runs.length) return <Panel><PanelHeader title="Marketing Creative Closed Loop" meta="No persisted workflow is available." /><p>A workflow will appear after a real Performance or Creative source event starts the loop.</p></Panel>;
  const state = timeline?.run.state;
  const decisionBody = { reviewer_alias: reviewer.trim(), reason: reason.trim() };
  const activeCommand = commands.find((command) => ["pending", "running", "retry_wait", "cancel_requested"].includes(command.status));
  const currentStep = loopStatePresentation(state);
  const needsDecision = ["awaiting_demand_approval", "awaiting_creative_approval", "awaiting_lesson_approval"].includes(state ?? "");
  return <Panel className="cross-panel creative-loop-card"><PanelHeader title="Creative learning loop" meta="One view from opportunity to the next stronger brief." action={state ? <Badge tone={needsDecision ? "warning" : "info"}>{needsDecision ? "Needs your decision" : "In progress"}</Badge> : undefined} />
    {loopWarning && <p className="form-error" role="alert">{t(loopWarning)}</p>}
    <div className="creative-loop-toolbar"><label><span>{t("Workflow")}</span><select value={selectedId ?? ""} onChange={(event) => { setSelectedId(event.target.value); setReason(""); }}>{runs.map((run) => <option key={run.run_id} value={run.run_id}>{formatDate(run.updated_at, { dateStyle: "medium" })} · {t(loopStatePresentation(run.state).title)}</option>)}</select></label><span className="creative-loop-updated">{t("Updated automatically")}</span></div>
    {timeline && <><section className="workflow-current" aria-labelledby="workflow-current-title"><div className="workflow-current__icon"><GitBranch size={22} /></div><div><p className="eyebrow">{t("Current step")}</p><h3 id="workflow-current-title">{t(currentStep.title)}</h3><p>{t(currentStep.detail)}</p></div></section>
      {activeCommand && <p className="mkt-filter-note" role="status"><strong>AI is processing the next step.</strong> This view will update automatically. <button className="secondary-button" disabled={saving || activeCommand.status === "cancel_requested"} onClick={() => void cancelCommand(activeCommand.command_id)}>Cancel</button></p>}
      {state === "awaiting_ads_outcome"
        ? <div className="workflow-gate workflow-gate--waiting"><div className="workflow-gate-copy"><strong>{t("Nothing to do right now")}</strong><p>The approved version is waiting for a persisted Ads outcome from the Performance data pipeline.</p></div></div>
        : ["awaiting_demand_approval", "awaiting_creative_approval", "awaiting_lesson_approval"].includes(state ?? "")
          ? <div className="workflow-gate"><div className="workflow-gate-copy"><strong>{t("Your decision")}</strong><p>{t("Add a short reason so the team can understand this decision later.")}</p></div><div className="workflow-gate-fields"><label>{t("Reviewer name")}<input value={reviewer} onChange={(event) => setReviewer(event.target.value)} placeholder={t("Enter your name")} /></label><label>{t("Decision reason")}<textarea rows={2} value={reason} onChange={(event) => setReason(event.target.value)} placeholder={t("What led to this decision?")} /></label></div><div className="workflow-gate-actions">{state === "awaiting_demand_approval" && <><button className="approve-button" disabled={saving || Boolean(activeCommand) || !reason.trim() || !reviewer.trim()} onClick={() => void post("demand-decision", { ...decisionBody, evaluation_id: timeline.run.initial_evaluation_id, decision: "approve" })}>Approve plan</button><button className="secondary-button" disabled={saving || Boolean(activeCommand) || !reason.trim() || !reviewer.trim()} onClick={() => void post("demand-decision", { ...decisionBody, evaluation_id: timeline.run.initial_evaluation_id, decision: "defer" })}>Decide later</button><button className="reject-button" disabled={saving || Boolean(activeCommand) || !reason.trim() || !reviewer.trim()} onClick={() => void post("demand-decision", { ...decisionBody, evaluation_id: timeline.run.initial_evaluation_id, decision: "reject" })}>Decline</button></>}{state === "awaiting_creative_approval" && <><button className="approve-button" disabled={saving || Boolean(activeCommand) || !reason.trim() || !reviewer.trim()} onClick={() => void post("creative-decision", { ...decisionBody, decision: "approve" })}>Approve creative</button><button className="reject-button" disabled={saving || Boolean(activeCommand) || !reason.trim() || !reviewer.trim()} onClick={() => void post("creative-decision", { ...decisionBody, decision: "reject" })}>Request changes</button></>}{state === "awaiting_lesson_approval" && timeline.run.lesson_id && <><button className="approve-button" disabled={saving || Boolean(activeCommand) || !reason.trim() || !reviewer.trim()} onClick={() => void post("lesson-decision", { ...decisionBody, lesson_id: timeline.run.lesson_id, decision: "approve" })}>Use this learning</button><button className="secondary-button" disabled={saving || Boolean(activeCommand) || !reason.trim() || !reviewer.trim()} onClick={() => void post("lesson-decision", { ...decisionBody, lesson_id: timeline.run.lesson_id, decision: "defer" })}>Decide later</button><button className="reject-button" disabled={saving || Boolean(activeCommand) || !reason.trim() || !reviewer.trim()} onClick={() => void post("lesson-decision", { ...decisionBody, lesson_id: timeline.run.lesson_id, decision: "reject" })}>Discard</button></>}</div></div>
          : null}
      <div className="workflow-progress-map" aria-label={t("Workflow progress")}>{timeline.steps.map((step, index) => <div className={`workflow-progress-step workflow-progress-step--${step.status}`} key={step.key}><span>{step.status === "completed" ? <Check size={13} /> : index + 1}</span><strong>{t(loopStageLabels[index] ?? step.label)}</strong></div>)}</div>
      <details className="workflow-technical" open={commands.some((command) => command.status === "failed")}>
        <summary>Workflow details</summary>
        <div className="workflow-stage-details">{timeline.steps.map((step) => <div key={step.key}><div><strong>{step.label}</strong><p>{step.detail}</p></div><StatusBadge status={step.status} /></div>)}</div>
        <dl className="compact-dl"><div><dt>Workflow ID</dt><dd><code>{timeline.run.run_id}</code></dd></div>{timeline.steps.filter((step) => step.reference).map((step) => <div key={step.key}><dt>{step.label}</dt><dd><code>{step.reference}</code></dd></div>)}</dl>
        <p className="muted-copy workflow-safety-note">All displayed workflow state is persisted by the backend. Publishing and campaign mutation remain disabled.</p>
      </details>
      {commands.length > 0 && <details className="workflow-technical" open={commands.some((command) => command.status === "failed")}><summary>Execution history ({commands.length})</summary><div className="workflow-list">{commands.map((command) => <div className="readiness-row" key={command.command_id}><div><strong>{command.name}</strong><p className="muted-copy">Attempt {command.attempts}/{command.max_attempts}{command.last_error_code ? ` · ${command.last_error_code}: ${command.last_error_message}` : ""}</p></div><div><StatusBadge status={command.status} />{command.status === "failed" && <button className="secondary-button" disabled={saving} onClick={() => void retryCommand(command.command_id)}><RefreshCcw size={15} />Retry</button>}</div></div>)}</div></details>}
      {error && <p className="form-error" role="alert">{error}</p>}</>}
  </Panel>;
}


export function CreativeAutomationDetailPage() {
  const { requestId = "" } = useParams();
  const [detail, setDetail] = useState<MarketingCreativeAutomationDetail | null>(null);
  const [reviewer, setReviewer] = useState("");
  const [reason, setReason] = useState("");
  const [destination, setDestination] = useState("");
  const [dailyBudget, setDailyBudget] = useState("30");
  const [currency, setCurrency] = useState("USD");
  const [adsReviewer, setAdsReviewer] = useState("");
  const [adsReason, setAdsReason] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [selectedAssetIds, setSelectedAssetIds] = useState<string[]>([]);
  const [revisionAssetIds, setRevisionAssetIds] = useState<string[]>([]);
  const [keyVisualAssetId, setKeyVisualAssetId] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    let active = true;
    const refreshableStatuses = new Set([
      "queued",
      "pending",
      "running",
      "retry_wait",
      "preparing",
      "awaiting_generation_provider",
      "producing",
      "revision_requested",
    ]);
    const load = async () => {
      try {
        const next = await pilotApi.marketingCreativeAutomation(requestId, controller.signal);
        if (!active) return;
        setDetail(next);
        setError("");
        if (refreshableStatuses.has(next.status)) timer = setTimeout(load, 10_000);
      } catch (caught: unknown) {
        if (active && (caught as { name?: string }).name !== "AbortError") {
          setError(caught instanceof Error ? caught.message : "Creative automation is unavailable");
        }
      } finally {
        if (active) setLoading(false);
      }
    };
    void load();
    return () => {
      active = false;
      controller.abort();
      if (timer) clearTimeout(timer);
    };
  }, [requestId]);

  const selectableAssetIds = JSON.stringify(
    detail?.final_review?.assets.map((asset) => asset.asset_version_id)
      ?? detail?.production_versions.filter((asset) => !asset.success).map((asset) => asset.asset_version_id)
      ?? [],
  );
  const hasFinalReview = Boolean(detail?.final_review);
  const defaultKeyVisualAssetId = detail?.final_review?.assets.find(
    (asset) => asset.media_kind === "image",
  )?.asset_version_id ?? null;

  useEffect(() => {
    const assetIds = JSON.parse(selectableAssetIds) as string[];
    if (hasFinalReview) {
      setSelectedAssetIds(assetIds);
      setRevisionAssetIds([]);
      setKeyVisualAssetId(defaultKeyVisualAssetId);
    } else {
      setSelectedAssetIds([]);
      setRevisionAssetIds(assetIds);
      setKeyVisualAssetId(null);
    }
  }, [defaultKeyVisualAssetId, hasFinalReview, selectableAssetIds]);

  const toggleAsset = (assetVersionId: string) => {
    setSelectedAssetIds((current) => {
      const next = current.includes(assetVersionId)
        ? current.filter((item) => item !== assetVersionId)
        : [...current, assetVersionId];
      if (!next.includes(keyVisualAssetId ?? "")) {
        const replacement = detail?.final_review?.assets.find((asset) => asset.media_kind === "image" && next.includes(asset.asset_version_id));
        setKeyVisualAssetId(replacement?.asset_version_id ?? null);
      }
      return next;
    });
  };

  const toggleRevisionAsset = (assetVersionId: string) => {
    setRevisionAssetIds((current) => current.includes(assetVersionId)
      ? current.filter((item) => item !== assetVersionId)
      : [...current, assetVersionId]);
  };

  const run = async (operation: () => Promise<MarketingCreativeAutomationDetail>) => {
    setSaving(true); setError("");
    try {
      await operation();
      setDetail(await pilotApi.marketingCreativeAutomation(requestId));
    }
    catch (caught) { setError(caught instanceof Error ? caught.message : "The request could not be completed"); }
    finally { setSaving(false); }
  };

  const decide = (decision: "approve" | "manual_takeover") => {
    const review = detail?.final_review;
    if (!detail || !review || !reviewer.trim() || (decision === "manual_takeover" && !reason.trim())) return;
    const reviewReason = reason.trim() || "Human approved without revision notes.";
    void run(() => pilotApi.decideMarketingCreativeAutomation(detail.request_id, {
      review_id: review.review_id,
      asset_version_ids: decision === "approve" ? selectedAssetIds : review.assets.map((asset) => asset.asset_version_id),
      asset_checksums: (decision === "approve" ? selectedAssetIds : review.assets.map((asset) => asset.asset_version_id)).map((assetId) => review.assets.find((asset) => asset.asset_version_id === assetId)!.checksum_sha256),
      key_visual_asset_version_id: decision === "approve" ? keyVisualAssetId : null,
      decision,
      reviewer_alias: reviewer.trim(),
      reason: reviewReason,
      idempotency_key: globalThis.crypto?.randomUUID?.() ?? `creative-review-${Date.now()}`,
    }));
  };

  const generateAgain = () => {
    if (!detail || !reviewer.trim() || !reason.trim()) return;
    void run(() => pilotApi.generateMarketingCreativeAgain(detail.request_id, {
      requested_by: reviewer.trim(),
      reason: reason.trim(),
      target_asset_version_ids: revisionAssetIds,
      idempotency_key: globalThis.crypto?.randomUUID?.() ?? `generate-again-${Date.now()}`,
    }));
  };

  const takeOverManually = () => {
    if (!detail || !reviewer.trim() || !reason.trim()) return;
    void run(() => pilotApi.takeOverMarketingCreativeManually(detail.request_id, {
      requested_by: reviewer.trim(),
      reason: reason.trim(),
      idempotency_key: globalThis.crypto?.randomUUID?.() ?? `manual-takeover-${Date.now()}`,
    }));
  };

  const createDraft = () => {
    if (!detail || !destination.trim() || !dailyBudget.trim()) return;
    void run(() => pilotApi.createMarketingCreativeAdsDraft(detail.request_id, {
      destination_ref: destination.trim(),
      daily_budget: dailyBudget,
      currency: currency.trim().toUpperCase(),
      idempotency_key: globalThis.crypto?.randomUUID?.() ?? `ads-draft-${Date.now()}`,
    }));
  };

  const approveDraft = () => {
    const draft = detail?.ads_draft;
    if (!detail || !draft || !adsReviewer.trim() || !adsReason.trim()) return;
    void run(() => pilotApi.approveMarketingCreativeAdsDraft(detail.request_id, {
      draft_id: draft.draft_id,
      draft_fingerprint: draft.draft_fingerprint,
      asset_version_ids: draft.asset_version_ids,
      asset_checksums: draft.asset_checksums,
      reviewer_alias: adsReviewer.trim(),
      reason: adsReason.trim(),
      idempotency_key: globalThis.crypto?.randomUUID?.() ?? `ads-approval-${Date.now()}`,
    }));
  };

  const launchAds = () => {
    const draft = detail?.ads_draft;
    if (!detail || !draft || detail.ads_provider_status !== "ready") return;
    void run(() => pilotApi.activateMarketingCreativeAdsDraft(detail.request_id, {
      draft_id: draft.draft_id,
      draft_fingerprint: draft.draft_fingerprint,
      asset_version_ids: draft.asset_version_ids,
      asset_checksums: draft.asset_checksums,
    }));
  };

  if (loading) return <SkeletonPage />;
  if (!detail) return <><Link className="back-link" to="/creative-production"><ArrowLeft size={16} />Back to Creative Production</Link><Panel><h1>Creative automation unavailable</h1>{error && <p className="form-error">{error}</p>}</Panel></>;
  const review = detail.final_review;
  const canReview = detail.status === "ready_for_review" && review && !detail.review_decision;
  const canCreateDraft = detail.status === "creative_approved" && !detail.ads_draft;
  const canApproveDraft = detail.status === "ads_draft_ready" && detail.ads_draft && !detail.ads_approved;
  const canRecover = ["needs_input", "awaiting_generation_provider", "production_needs_attention"].includes(detail.status) && !detail.manual_takeover;
  const hasExactSourceOutput = Boolean(
    review?.assets.some((asset) => asset.fidelity_mode === "exact_source_transform")
    || detail.production_versions.some((asset) => asset.fidelity_mode === "exact_source_transform"),
  );
  const canGenerateAgain = detail.status === "production_needs_attention" && !hasExactSourceOutput;
  const currentVersionIds = new Set(review?.assets.map((asset) => asset.asset_version_id) ?? []);
  const historicalVersions = detail.production_versions.filter((asset) => !currentVersionIds.has(asset.asset_version_id));
  const selectedIdea = detail.trace?.selected_idea;
  const preparedBrief = detail.trace?.prepared_brief;
  const strategy = detail.trace?.strategy;
  const strategyCritique = strategy?.critique as Record<string, unknown> | undefined;
  const plannedImages = detail.trace?.plan?.image_plans ?? [];
  const plannedVideos = detail.trace?.plan?.video_plans ?? [];
  const plannedReferenceSelections = [
    ...plannedImages.map((plan, index) => ({ outputKey: `image:${index + 1}`, plan })),
    ...plannedVideos.map((plan, index) => ({ outputKey: `video:${index + 1}`, plan })),
  ].map(({ outputKey, plan }) => ({
    outputKey,
    referenceIds: Array.isArray(plan.reference_ids)
      ? plan.reference_ids.filter((item): item is string => typeof item === "string")
      : [],
    rationale: typeof plan.reference_rationale === "string" ? plan.reference_rationale : "",
  })).filter((item) => item.referenceIds.length > 0);
  const plannedProductSelections = [
    ...plannedImages.map((plan, index) => ({
      variationKey: String(plan.variation_key ?? `image:${index + 1}`),
      mediaIds: Array.isArray(plan.selected_media_ids)
        ? plan.selected_media_ids.filter((item): item is string => typeof item === "string")
        : [],
    })),
    ...plannedVideos.map((plan, index) => ({
      variationKey: String(plan.variation_key ?? `video:${index + 1}`),
      mediaIds: Array.isArray(plan.scenes)
        ? [...new Set(plan.scenes.flatMap((scene) => Array.isArray((scene as Record<string, unknown>).selected_media_ids)
          ? ((scene as Record<string, unknown>).selected_media_ids as unknown[]).filter((item): item is string => typeof item === "string")
          : []))]
        : [],
    })),
  ];
  const assembledVideos = detail.production_versions.filter(
    (version) => version.media_kind === "video" && version.intermediate_artifacts.length > 0,
  );
  const requestTrace = detail.trace?.request;
  const requestedOutput = requestTrace?.output as Record<string, unknown> | undefined;
  const imageCount = Number(requestedOutput?.image_count ?? 0);
  const videoCount = Number(requestedOutput?.video_count ?? 0);
  const videoMin = Number(requestedOutput?.video_duration_min_seconds ?? requestedOutput?.video_duration_seconds ?? 0);
  const videoMax = Number(requestedOutput?.video_duration_max_seconds ?? requestedOutput?.video_duration_seconds ?? 0);
  const duration = videoMin === videoMax ? `${videoMin}s` : `${videoMin}–${videoMax}s`;
  const requestScope = [
    requestTrace?.include_text ? "text" : "no text",
    requestTrace?.include_logo ? "logo" : "no logo",
    imageCount > 0 ? `${imageCount} image${imageCount === 1 ? "" : "s"}` : null,
    videoCount > 0 ? `${videoCount} video${videoCount === 1 ? "" : "s"} at ${duration}` : null,
    videoCount > 0 ? (requestTrace?.video_generate_audio ? "audio" : "silent") : null,
  ].filter(Boolean).join(" · ");
  return <>
    <Link className="back-link" to="/creative-production"><ArrowLeft size={16} />Back to Creative Production</Link>
    <PageHeader eyebrow="Creative production" title={review ? "Review generated outputs" : "Creative request status"} description="Review exact asset versions, explicitly generate another version, or hand the SKU back to the team." actions={<StatusBadge status={detail.status} />} />
    <div className="automation-detail-grid">
      <main>
        {!review && <Panel className="automation-waiting"><Sparkles size={22} /><div><h2>No generated output yet</h2><p>{detail.production_error_detail ?? (detail.status === "awaiting_generation_provider" ? "The brief is ready. Production will start only after an approved managed image/video provider is connected." : "This request is waiting for the next production step.")}</p>{detail.production_error_code && <small>Error reference: {detail.production_error_code}</small>}{detail.issues.length > 0 && <ul>{detail.issues.map((issue) => <li key={`${issue.component ?? "workflow"}-${issue.code}`}><strong>{issue.component ?? "workflow"}:</strong> {issue.detail}</li>)}</ul>}</div></Panel>}
        {review && review.review_checklist.length > 0 && <Panel className="automation-review-checklist"><PanelHeader title="SecondBrain review checklist" meta={`${review.review_checklist.length} approved criteria`} /><ul>{review.review_checklist.map((criterion) => <li key={criterion}>{criterion}</li>)}</ul></Panel>}
        {review && <Panel><PanelHeader title="Choose outputs to use" meta={`${review.image_count} image${review.image_count === 1 ? "" : "s"} · ${review.video_count} assembled video`} /><p className="automation-direction">{review.direction_summary}</p><div className="automation-asset-grid">{review.assets.map((asset) => { const version = detail.production_versions.find((item) => item.asset_version_id === asset.asset_version_id); const variationKey = version?.variation_key ?? asset.asset_version_id; const productMediaIds = plannedProductSelections.find((item) => item.variationKey === variationKey)?.mediaIds ?? []; const actualMedia = version?.actual_width && version.actual_height ? `${version.actual_width}×${version.actual_height}${version.actual_duration_seconds ? ` · ${version.actual_duration_seconds}s` : ""}${version.has_audio_stream === null || version.has_audio_stream === undefined ? "" : version.has_audio_stream ? " · audio" : " · silent"}` : null; return <article key={asset.asset_version_id} className={`automation-asset-card ${selectedAssetIds.includes(asset.asset_version_id) ? "automation-asset-card--selected" : ""}`}><label className="automation-asset-selection"><input type="checkbox" checked={selectedAssetIds.includes(asset.asset_version_id)} onChange={() => toggleAsset(asset.asset_version_id)} /><span>Use this output</span></label><div className="automation-asset-preview">{asset.artifact_web_url ? asset.media_kind === "video" ? <video controls preload="metadata" src={asset.artifact_web_url} /> : <img src={asset.artifact_web_url} alt={`Creative ${asset.asset_version_id}`} /> : <span>{asset.media_kind === "video" ? <Video /> : <Image />}<small>Preview unavailable</small></span>}</div><div><div className="card-topline"><Badge>{asset.media_kind}</Badge><Badge tone="success">Technical checks passed</Badge>{asset.fidelity_mode === "exact_source_transform" && <Badge tone="info">Exact Shopify source</Badge>}</div><strong>{variationKey}</strong><p>{asset.qa_summary}</p>{actualMedia && <p className="muted-copy">Actual output: {actualMedia}</p>}{productMediaIds.length > 0 && <p className="muted-copy">Shopify source used: <code>{productMediaIds.join(" · ")}</code></p>}{asset.product_source_checksum_sha256 && <p className="muted-copy">Frozen product source: <code>{asset.product_source_checksum_sha256.slice(0, 12)}</code></p>}{asset.media_kind === "image" && selectedAssetIds.includes(asset.asset_version_id) && <label className="automation-key-visual"><input type="radio" name="key-visual" checked={keyVisualAssetId === asset.asset_version_id} onChange={() => setKeyVisualAssetId(asset.asset_version_id)} /><span>Key Visual</span></label>}{asset.fidelity_mode !== "exact_source_transform" && <label className="automation-revision-selection"><input type="checkbox" checked={revisionAssetIds.includes(asset.asset_version_id)} onChange={() => toggleRevisionAsset(asset.asset_version_id)} /><span>Generate another version</span></label>}<small>{asset.provider_id} · {asset.revision_count} revision{asset.revision_count === 1 ? "" : "s"} · ${asset.cost}</small></div></article>; })}</div></Panel>}
        {canReview && <Panel className="automation-decision-panel"><PanelHeader title="Human review" meta={`${selectedAssetIds.length} output${selectedAssetIds.length === 1 ? "" : "s"} selected for use.`} /><div className="automation-review-fields"><label><span>Reviewer</span><input value={reviewer} onChange={(event) => setReviewer(event.target.value)} placeholder="Your name" /></label><label><span>Review feedback</span><textarea rows={3} value={reason} onChange={(event) => setReason(event.target.value)} placeholder="Optional when passing. Required when generating again or taking over manually." /></label></div><div className="automation-review-actions"><button className="approve-button" disabled={saving || !reviewer.trim() || selectedAssetIds.length === 0} onClick={() => decide("approve")}>Pass selected ({selectedAssetIds.length})</button>{!hasExactSourceOutput && <button className="secondary-button" disabled={saving || !reviewer.trim() || !reason.trim() || revisionAssetIds.length === 0} onClick={generateAgain}>Generate again ({revisionAssetIds.length})</button>}<button className="reject-button" disabled={saving || !reviewer.trim() || !reason.trim()} onClick={() => decide("manual_takeover")}>Take over manually</button></div></Panel>}
        {canRecover && <Panel className="automation-decision-panel"><PanelHeader title="Choose the next action" meta={canGenerateAgain ? "No automatic retry will run. Explicitly request another version or return this SKU to the team." : "Automation is paused. Return this SKU to the team if you do not want to wait for the missing dependency."} /><div className="automation-review-fields"><label><span>Requested by</span><input value={reviewer} onChange={(event) => setReviewer(event.target.value)} placeholder="Your name" /></label><label><span>Reason</span><textarea rows={3} value={reason} onChange={(event) => setReason(event.target.value)} placeholder="Why should the workflow retry or move to manual production?" /></label></div><div className="automation-review-actions">{canGenerateAgain && <button className="secondary-button" disabled={saving || !reviewer.trim() || !reason.trim() || revisionAssetIds.length === 0} onClick={generateAgain}>Retry selected outputs ({revisionAssetIds.length})</button>}<button className="reject-button" disabled={saving || !reviewer.trim() || !reason.trim()} onClick={takeOverManually}>Take over manually</button></div></Panel>}
        {detail.review_decision && <Panel className="automation-recorded-decision"><Check size={19} /><div><strong>Creative decision recorded: {detail.review_decision.decision.replaceAll("_", " ")}</strong><p>{detail.review_decision.reason}</p><small>{detail.review_decision.reviewer_alias} · {detail.review_decision.asset_version_ids.length} approved{detail.review_decision.key_visual_asset_version_id ? ` · Key Visual ${detail.review_decision.key_visual_asset_version_id}` : ""}</small></div></Panel>}
        {detail.manual_takeover && <Panel className="automation-recorded-decision"><Check size={19} /><div><strong>Manual takeover recorded</strong><p>{detail.manual_takeover.reason}</p><small>{detail.manual_takeover.requested_by} · {new Date(detail.manual_takeover.requested_at).toLocaleString()}</small></div></Panel>}
        {historicalVersions.length > 0 && <Panel className="automation-version-history"><details open={!review}><summary>Previous and failed output versions ({historicalVersions.length})</summary><div className="automation-asset-grid">{historicalVersions.map((asset) => <article key={asset.asset_version_id} className={`automation-asset-card ${revisionAssetIds.includes(asset.asset_version_id) ? "automation-asset-card--selected" : ""}`}>{canRecover && !asset.success && <label className="automation-asset-selection"><input type="checkbox" checked={revisionAssetIds.includes(asset.asset_version_id)} onChange={() => toggleRevisionAsset(asset.asset_version_id)} /><span>Retry this failed output</span></label>}<div className="automation-asset-preview">{asset.artifact_web_url ? asset.media_kind === "video" ? <video controls preload="metadata" src={asset.artifact_web_url} /> : <img src={asset.artifact_web_url} alt={`Creative ${asset.asset_version_id}`} /> : <span>{asset.media_kind === "video" ? <Video /> : <Image />}<small>Preview unavailable</small></span>}</div><div><div className="card-topline"><Badge>{asset.media_kind}</Badge><Badge tone={asset.success ? "success" : "warning"}>{asset.outcome.replaceAll("_", " ")}</Badge></div><strong>{asset.variation_key}</strong><p>{asset.technical_check_summary ?? "No technical check summary was recorded."}</p>{asset.revision_feedback && <p><strong>Revision feedback:</strong> {asset.revision_feedback}</p>}{asset.parent_asset_version_id && <small>Revised from {asset.parent_asset_version_id}</small>}<small>{asset.provider_id ?? "Provider unavailable"} · {asset.attempt_count} attempt{asset.attempt_count === 1 ? "" : "s"} · ${asset.total_cost}</small></div></article>)}</div></details></Panel>}
        {detail.trace && <Panel className="automation-trace"><details><summary>How this output was created</summary><div className="automation-trace__body"><p className="muted-copy">Structured inputs and decision summaries are shown for auditability. Private model reasoning is never stored or displayed.</p><section><h3>Pipeline latency</h3><p><strong>Total: {formatLatency(detail.trace.latency.total_duration_ms)}</strong>{!detail.trace.latency.is_final && " · still running"}</p>{detail.trace.latency.steps.length > 0 ? <div className="workflow-list">{detail.trace.latency.steps.map((step, index) => <div className="readiness-row" key={`${step.step}-${step.started_at}-${index}`}><div><strong>{step.step.replaceAll("_", " ")}</strong><p className="muted-copy">{step.outcome}</p></div><span>{formatLatency(step.duration_ms)}</span></div>)}</div> : <p className="muted-copy">Step timing will appear on the next pipeline run.</p>}</section><section><h3>Input</h3><dl className="compact-dl">{Object.entries(detail.trace.request).filter(([, value]) => value !== null).map(([key, value]) => <div key={key}><dt>{key.replaceAll("_", " ")}</dt><dd>{typeof value === "object" ? <code>{JSON.stringify(value)}</code> : String(value)}</dd></div>)}</dl></section>{(selectedIdea || preparedBrief) && <section><h3>Agent-prepared brief</h3><dl className="compact-dl">{selectedIdea && <><div><dt>Persona</dt><dd>{String(selectedIdea.persona ?? "Not recorded")}</dd></div><div><dt>Angle</dt><dd>{String(selectedIdea.angle ?? "Not recorded")}</dd></div><div><dt>Hook</dt><dd>{String(selectedIdea.hook ?? "Not recorded")}</dd></div><div><dt>Concept</dt><dd>{String(selectedIdea.concept ?? "Not recorded")}</dd></div></>}{preparedBrief && <div><dt>Visual direction</dt><dd>{String(preparedBrief.visual_direction ?? "Not recorded")}</dd></div>}</dl></section>}{strategy && <section><h3>Prepared strategy</h3><dl className="compact-dl"><div><dt>Strategy ID</dt><dd><code>{String(strategy.strategy_id ?? "Not recorded")}</code></dd></div><div><dt>Selection rationale</dt><dd>{String(strategyCritique?.rationale ?? "Not recorded")}</dd></div><div><dt>Evidence</dt><dd>{Array.isArray(strategy.evidence_refs) && strategy.evidence_refs.length ? strategy.evidence_refs.join(" · ") : "No strategy evidence recorded."}</dd></div><div><dt>Prompt versions</dt><dd>{Array.isArray(strategy.prompt_versions) && strategy.prompt_versions.length ? strategy.prompt_versions.join(" · ") : "Not recorded"}</dd></div></dl></section>}{detail.trace.plan && <section><h3>Orchestration plan</h3><p><strong>{detail.trace.plan.strategy_summary}</strong></p><p>{detail.trace.plan.rationale}</p><dl className="compact-dl"><div><dt>Model profile</dt><dd><code>{detail.trace.plan.model_profile}</code></dd></div><div><dt>Prompt version</dt><dd><code>{detail.trace.plan.prompt_version}</code></dd></div><div><dt>Readiness</dt><dd>{detail.trace.plan.readiness}</dd></div><div><dt>Image concepts</dt><dd>{detail.trace.plan.image_plans.length}</dd></div><div><dt>Video concepts</dt><dd>{plannedVideos.length || "Not requested"}</dd></div></dl>{plannedReferenceSelections.length > 0 && <div className="workflow-list">{plannedReferenceSelections.map((selection) => <div className="readiness-row" key={selection.outputKey}><div><strong>{selection.outputKey} Research references</strong><p className="muted-copy">{selection.rationale}</p></div><span className="muted-copy">{selection.referenceIds.join(" · ")}</span></div>)}</div>}{plannedVideos.length > 0 && <div className="workflow-list">{plannedVideos.map((video, index) => { const audio = video.audio_plan as Record<string, unknown> | undefined; const scenes = Array.isArray(video.scenes) ? video.scenes : []; return <div className="readiness-row" key={String(video.variation_key ?? index)}><div><strong>{String(video.scenario ?? video.variation_key ?? `Video ${index + 1}`)}</strong><p className="muted-copy">{String(video.creative_hypothesis ?? "No hypothesis recorded.")}</p></div><span className="muted-copy">{String(video.final_duration_seconds ?? "-")}s · {String(video.generation_strategy ?? "-").replaceAll("_", " ")} · {scenes.length} source{scenes.length === 1 ? "" : "s"} · voice {String(audio?.voice_mode ?? "none").replaceAll("_", " ")} · music {String(audio?.music_mode ?? "none").replaceAll("_", " ")}</span></div>; })}</div>}</section>}{assembledVideos.length > 0 && <section><h3>Video assembly</h3><div className="workflow-list">{assembledVideos.map((version) => <div className="readiness-row" key={version.asset_version_id}><div><strong>{version.asset_version_id}</strong><p className="muted-copy">{version.intermediate_artifacts.length} short scenes were produced before final assembly.</p></div><div>{version.intermediate_artifacts.map((scene, index) => <span key={scene.artifact_ref} className="muted-copy">Scene {index + 1}: {scene.duration_seconds ?? "-"}s - {scene.provider_id}</span>)}</div></div>)}</div></section>}<section><h3>Evidence and memory</h3><p>{detail.trace.source_refs.length ? detail.trace.source_refs.join(" · ") : "No source references recorded."}</p><p>{detail.trace.memory_refs.length ? `Approved memory: ${detail.trace.memory_refs.join(", ")}` : "No approved memory was applied."}</p></section><section><h3>Execution history</h3><div className="automation-trace__events">{detail.trace.events.map((event) => <div key={event.event_id}><span>{new Date(event.created_at).toLocaleString()}</span><strong>{event.event_type.replaceAll("_", " ")}</strong></div>)}</div><p className="muted-copy">Tokens: {detail.trace.input_tokens ?? "—"} in / {detail.trace.output_tokens ?? "—"} out · Recorded cost ${detail.trace.total_cost}</p></section>{detail.trace.technical_checks.length > 0 && <section><h3>Technical checks</h3><ul>{detail.trace.technical_checks.map((check, index) => <li key={`${check}-${index}`}>{check}</li>)}</ul></section>}</div></details></Panel>}
      </main>
      <aside className="automation-activation-column">
        <Panel><p className="eyebrow">Request</p><dl className="compact-dl"><div><dt>Route</dt><dd>{detail.route}</dd></div><div><dt>Package</dt><dd><code>{detail.package_id}</code></dd></div><div><dt>Scope</dt><dd>{requestScope || "Not recorded"}</dd></div><div><dt>Production</dt><dd>{detail.production_attempt_count} final-production attempts · ${detail.production_cost}</dd></div><div><dt>Generate again</dt><dd>{detail.generation_request_count} explicit requests</dd></div></dl></Panel>
        {canCreateDraft && <Panel><PanelHeader title="Create Ads Draft" meta="No Ads write occurs at this step." /><div className="automation-review-fields"><label><span>Destination</span><input value={destination} onChange={(event) => setDestination(event.target.value)} placeholder="Product page or destination ID" /></label><div className="automation-budget-fields"><label><span>Daily budget</span><input type="number" min="0.01" step="0.01" value={dailyBudget} onChange={(event) => setDailyBudget(event.target.value)} /></label><label><span>Currency</span><input maxLength={3} value={currency} onChange={(event) => setCurrency(event.target.value)} /></label></div></div><button className="approve-button" disabled={saving || !destination.trim() || Number(dailyBudget) <= 0 || currency.trim().length !== 3} onClick={createDraft}>Create draft</button></Panel>}
        {detail.ads_draft && <Panel><PanelHeader title="Ads Draft" meta="Exact Creative versions are locked." /><dl className="compact-dl"><div><dt>Destination</dt><dd>{detail.ads_draft.destination_ref}</dd></div><div><dt>Daily budget</dt><dd>{detail.ads_draft.daily_budget} {detail.ads_draft.currency}</dd></div><div><dt>Status</dt><dd>{detail.ads_draft.status.replaceAll("_", " ")}</dd></div></dl>{canApproveDraft && <><div className="automation-review-fields"><label><span>Approver</span><input value={adsReviewer} onChange={(event) => setAdsReviewer(event.target.value)} placeholder="Your name" /></label><label><span>Approval reason</span><textarea rows={2} value={adsReason} onChange={(event) => setAdsReason(event.target.value)} placeholder="Confirm budget and destination." /></label></div><button className="approve-button" disabled={saving || !adsReviewer.trim() || !adsReason.trim()} onClick={approveDraft}>Approve Ads Draft</button></>}</Panel>}
        {detail.ads_approved && !detail.ads_activation && detail.ads_provider_status === "ready" && <Panel className="automation-launch-lock"><ShieldCheck size={22} /><div><strong>Ready to launch</strong><p>The approved adapter will publish only the exact draft and Creative versions shown above.</p><button className="approve-button" disabled={saving} onClick={launchAds}>{saving ? "Launching…" : "Launch Ads"}</button></div></Panel>}
        {detail.ads_approved && !detail.ads_activation && detail.ads_provider_status !== "ready" && <Panel className="automation-launch-lock"><ShieldCheck size={22} /><div><strong>Approved, not published</strong><p>The exact Ads Draft is approved. Real launch remains locked until an approved least-privilege Ads adapter is configured.</p><small>Adapter status: {detail.ads_provider_status.replaceAll("_", " ")}</small></div></Panel>}
        {detail.ads_activation && <Panel className="automation-recorded-decision"><Check size={19} /><div><strong>Ads launched</strong><p>Campaign {detail.ads_activation.campaign_id} · {detail.ads_activation.ad_ids.length} ad{detail.ads_activation.ad_ids.length === 1 ? "" : "s"}</p><small>{detail.ads_activation.platform} account {detail.ads_activation.account_id}</small></div></Panel>}
      </aside>
    </div>
    {error && <p className="form-error" role="alert">{error}</p>}
  </>;
}

export function CreativeProductionPage() {
  const { t } = useI18n();
  return <section className="creative-production-page">
    <PageHeader eyebrow={t("Marketing production")} title={t("Creative Production")} description={t("Choose a Product or Variant, upload references, then start final image and video production.")} variant="campaign" actions={<Link className="secondary-button" to="/creatives?view=media">{t("View Creative Library")}</Link>} />
    <ol className="production-steps" aria-label={t("Creative production workflow")}>
      <li><span>01</span><strong>{t("Product")}</strong><small>{t("Choose Product or Variant")}</small></li>
      <li><span>02</span><strong>{t("Direction")}</strong><small>{t("Choose approach and add optional requirements")}</small></li>
      <li><span>03</span><strong>{t("Output")}</strong><small>{t("Choose profiles and model settings")}</small></li>
      <li><span>04</span><strong>{t("Review")}</strong><small>{t("Approve exact versions")}</small></li>
    </ol>
    <CreativeAutomationLauncher />
  </section>;
}

export function WorkflowsPage() {
  const { t, formatDate } = useI18n();
  const pilot = usePilotDashboard();
  const [params] = useSearchParams();
  const [stream, setStream] = useState("all");
  const requestedLoopId = params.get("loop");
  if (pilot.isLoading) return <SkeletonPage />;
  const workflows = (pilot.data?.workflows ?? []).filter((item) => stream === "all" || item.workstream === stream);
  const activityWorkflows = workflows.filter((item) => !item.action_path.includes("?loop="));
  const counts = { "AI working": workflows.filter((x) => x.status === "running").length, "Waiting for input": workflows.filter((x) => x.status === "waiting").length, "Needs attention": workflows.filter((x) => x.status === "failed").length };
  return (
    <>
      <PageHeader eyebrow="What AI is doing" title="AI activity" description="Follow business progress, see what is waiting and step in only when a decision or exception needs you." actions={<Badge tone="success"><span className="live-dot" />{t("Live")}</Badge>} />
      <div className="filterbar workflow-toolbar"><label>{t("Workstream")} <select aria-label={t("Workflow workstream")} value={stream} onChange={(event) => setStream(event.target.value)}><option value="all">{t("All Marketing")}</option>{Object.entries(dashboardStreamLabels).map(([key, label]) => <option key={key} value={key}>{t(label)}</option>)}</select></label><div className="workflow-counts">{Object.entries(counts).map(([label, value]) => <span key={label}><strong>{value}</strong> {t(label)}</span>)}</div></div>
      {(stream === "all" || stream === "creative") && requestedLoopId && <CreativeClosedLoopPilot />}
      {pilot.error && <Panel className="mkt-issue-panel"><strong>Dashboard workflow projection unavailable</strong><p>{pilot.error.message}</p></Panel>}
      <h2>{t("All activity")}</h2>
      <div className="workflow-list workflow-list--activity">
        {activityWorkflows.map((flow) => <Panel className="workflow-card" key={flow.workflow_id}><Link className="workflow-summary" to={flow.action_path}><span className="workflow-symbol"><GitBranch size={19} /></span><div><strong>{t(flow.title === "Static Creative production" ? "Creative output" : flow.title)}</strong><p>{flow.brand_id ?? t("Shared")} · {formatDate(flow.updated_at)}</p></div><div className="workflow-progress"><span>{t(businessStage(flow.business_stage))}</span><small>{t(dashboardStreamLabels[flow.workstream])}</small></div><StatusBadge status={flow.status} /><ArrowRight size={18} /></Link></Panel>)}
      </div>
      {!activityWorkflows.length && <EmptyState icon={<GitBranch />} title="No other activity" text="New automated work will appear here when it starts." />}
    </>
  );
}

export function ExceptionsPage() {
  const { t, formatDate } = useI18n();
  const pilot = usePilotDashboard();
  const [tab, setTab] = useState("open");
  const [queue, setQueue] = useState("all");
  if (pilot.isLoading) return <SkeletonPage />;
  const items = (pilot.data?.exceptions ?? []).filter((item) => (tab === "all" || item.status === tab) && (queue === "all" || item.queue === queue));
  return (
    <>
      <PageHeader eyebrow="Human exception queue" title="Exceptions" description="Persisted business and operations exceptions from backend evidence and execution state." variant="operator" actions={<Badge tone="danger">{pilot.data?.summary.open_exceptions ?? 0} open</Badge>} />
      <div className="filterbar"><div className="segmented">{["open", "all"].map((item) => <button className={tab === item ? "active" : ""} onClick={() => setTab(item)} key={item}>{t(item)}</button>)}</div></div>
      <label className="filterbar">{t("Queue")} <select aria-label={t("Exception queue")} value={queue} onChange={(event) => setQueue(event.target.value)}><option value="all">{t("All queues")}</option><option value="operations">{t("Operations")}</option><option value="policy">{t("Policy")}</option></select></label>
      {pilot.error && <p className="form-error" role="alert">{pilot.error.message}</p>}
      <div className="exception-list">{items.map((item) => <Panel className="exception-card" key={item.exception_id}><span className={`severity-icon severity-icon--${item.severity === "blocking" ? "critical" : "warning"}`}>{item.severity === "blocking" ? <AlertCircle /> : <TriangleAlert />}</span><div><div className="card-topline"><Badge tone={item.severity === "blocking" ? "danger" : "warning"}>{item.severity}</Badge><Badge>{item.queue}</Badge><StatusBadge status={item.status} /></div><h2>{item.title}</h2><p>{item.detail}</p><span className="exception-source">{dashboardStreamLabels[item.workstream]} · {formatDate(item.created_at)}</span><footer><span>{t("Suggested action")}</span><Link className="text-link" to={item.action_path}>Inspect exact evidence →</Link></footer></div></Panel>)}</div>
      {!items.length && <EmptyState icon={<ShieldCheck />} title="No exceptions" text="No backend exceptions in the selected queue." />}
    </>
  );
}

export function DataSourcesPage() {
  const { t, formatDate } = useI18n();
  const sources = useDataSources();
  const sync = useDataSourceSync();
  const syncAll = useDataSourcesSyncAll();
  if (sources.isLoading) return <SkeletonPage />;
  const data = sources.data?.items ?? [];
  const hasActiveSync = data.some((source) => source.sync_status != null);
  const tokenUrgency = (source: (typeof data)[number]) => {
    if (!source.credential_expires_at) return null;
    const remaining = new Date(source.credential_expires_at).getTime() - Date.now();
    if (remaining <= 0) return <Badge tone="danger">{t("Token expired")}</Badge>;
    const hours = Math.round(remaining / 3_600_000);
    if (hours <= 24) return <Badge tone="warning">{t("Token expires in {hours}h", { hours: Math.max(1, hours) })}</Badge>;
    return null;
  };
  const statusData = [
    { name: t("Healthy"), value: data.filter((x) => x.status === "healthy").length, color: "var(--green)" },
    { name: t("Not synced"), value: data.filter((x) => x.status === "not_synced").length, color: "var(--amber)" },
    { name: t("Error"), value: data.filter((x) => x.status === "error").length, color: "var(--red)" },
  ];
  return (
    <>
      <PageHeader eyebrow="Read-only input health" title="Data sources" description="Real read-only API checks against configured source resources. Review the current Ads and SKU evidence in Performance." variant="operator" />
      {sources.error && <p className="form-error" role="alert">{sources.error.message}</p>}
      {!data.length ? <EmptyState icon={<Database />} title={t("No data sources configured")} text={t("Ask an administrator to provide the local data-source configuration. Read-only sync starts after configuration.")} /> : <>
      <div className="source-overview"><Panel><div role="img" aria-label={`${t("Data source status")}: ${data.filter((x) => x.status === "healthy").length}/${data.length} ${t("healthy")}`} style={{ display: "contents" }}><ResponsiveContainer width="100%" height={190}><PieChart><Pie data={statusData} dataKey="value" innerRadius={55} outerRadius={76} paddingAngle={4}>{statusData.map((item) => <Cell key={item.name} fill={item.color} />)}</Pie><Tooltip contentStyle={{ background: "var(--paper)", border: "1px solid var(--line)", borderRadius: 8, boxShadow: "var(--shadow-md)", fontSize: "var(--text-xs)" }} labelStyle={{ color: "var(--muted)" }} itemStyle={{ color: "var(--ink)" }} /></PieChart></ResponsiveContainer></div><div><strong>{data.filter((x) => x.status === "healthy").length}/{data.length}</strong><span>{t("healthy")}</span></div></Panel><Panel><h2>{t("Data readiness")}</h2><p>{data.every((item) => item.status === "healthy") ? t("All configured sources have a successful snapshot.") : t("Sync each source and inspect any authentication or resource errors.")}</p><div className="readiness-row"><span>{t("Mode")}</span><Badge tone="success">{t("Read only")}</Badge></div><div className="readiness-row"><span>{t("Resources")}</span><Badge>{t("Allowlisted")}</Badge></div><button className="secondary-button" onClick={() => syncAll.mutate()} disabled={syncAll.isPending || sync.isPending || hasActiveSync}><RefreshCcw size={15} className={hasActiveSync ? "spin" : undefined} />{hasActiveSync ? t("Syncing…") : t("Sync all")}</button></Panel></div>
      <div className="source-grid">{data.map((source) => { const isSyncing = source.sync_status != null; return <Panel className="source-card" key={source.source_id}><div><span className="source-icon"><Database size={19} /></span>{isSyncing ? <Badge tone="warning">{t("Syncing…")}</Badge> : source.status === "not_synced" ? <Badge tone="warning">{t("Not synced")}</Badge> : <StatusBadge status={source.status === "error" ? "failed" : "completed"} />}{tokenUrgency(source)}</div><h2>{source.name}</h2><span className="source-category">{t(source.category)} · {source.provider}</span><p>{source.purpose}</p><dl><div><dt>{t("Last sync")}</dt><dd>{source.last_sync_at ? formatDate(source.last_sync_at) : t("Never")}</dd></div><div><dt>{t("Records")}</dt><dd>{source.record_count}</dd></div><div><dt>{t("Change")}</dt><dd>{source.changed == null ? "—" : source.changed ? t("New snapshot") : t("Unchanged")}</dd></div>{source.credential_expires_at && <div><dt>{t("Token expires")}</dt><dd>{formatDate(source.credential_expires_at)}</dd></div>}</dl>{source.error_message && !isSyncing && <p className="form-error">{source.error_code}: {source.error_message}</p>}<button className="secondary-button" onClick={() => sync.mutate(source.source_id)} disabled={sync.isPending || syncAll.isPending || hasActiveSync}><RefreshCcw size={15} className={isSyncing ? "spin" : undefined} />{isSyncing ? t("Syncing…") : t("Sync now")}</button></Panel>; })}</div>
      <Panel className="source-candidates"><PanelHeader title="Performance evidence" meta="Google Ads and Meta Ads snapshots are reviewed on the Performance page." action={<Link className="text-link" to="/performance">Open Performance →</Link>} /></Panel>
      </>}
    </>
  );
}
