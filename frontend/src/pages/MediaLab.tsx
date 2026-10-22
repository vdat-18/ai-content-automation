import { useEffect, useState, type FormEvent } from "react";
import { AutoResizeTextarea } from "../components/AutoResizeTextarea";
import { MediaLabJobProgress } from "../components/MediaLabJobProgress";
import { useI18n } from "../hooks/useI18n";
import { pilotApi } from "../services/pilotApi";
import { marketingErrorMessage } from "../services/http";
import { MediaLabVideoPanel } from "./MediaLabVideoPanel";
import type {
  MediaAsset,
  MediaLabImageCapability,
  MediaLabImageCapabilities,
  MediaLabImageOrchestrationStatus,
  MediaLabImagePlan,
  MediaLabImageReferenceRequest,
  MediaLabImageRun,
  MediaLabImageSource,
} from "../types/pilotApi";

const imageAccept = "image/jpeg,image/png,image/webp,image/avif,image/tiff,.tif,.tiff";
const imagePlanningJobStorageKey = "media-lab-image-planning-job";
const imagePreparedJobStorageKey = "media-lab-image-prepared-job";
const maximumReferenceImages = 10;

type SourceAssetState = "pending" | "uploading" | "processing" | "ready" | "failed";

type SelectedImageSource = {
  localId: string;
  label: string;
  state: SourceAssetState;
  progress: number | null;
  asset: MediaAsset | null;
  error: string | null;
};

export function MediaLabPage() {
  const { t } = useI18n();
  const [activeWorkspace, setActiveWorkspace] = useState<"image" | "video">("image");
  const [catalog, setCatalog] = useState<MediaLabImageCapabilities | null>(null);
  const [orchestration, setOrchestration] = useState<MediaLabImageOrchestrationStatus | null>(null);
  const [history, setHistory] = useState<MediaLabImageRun[]>([]);
  const [request, setRequest] = useState("");
  const [referenceAssets, setReferenceAssets] = useState<SelectedImageSource[]>([]);
  const [previousAssetId, setPreviousAssetId] = useState("");
  const [plan, setPlan] = useState<MediaLabImagePlan | null>(null);
  const [planSources, setPlanSources] = useState<MediaLabImageSource[]>([]);
  const [planningJobId, setPlanningJobId] = useState(() => (
    localStorage.getItem(imagePlanningJobStorageKey)
    ?? localStorage.getItem(imagePreparedJobStorageKey)
    ?? ""
  ));
  const [preparedJobId, setPreparedJobId] = useState(() => localStorage.getItem(imagePreparedJobStorageKey) ?? "");
  const [outputPresetId, setOutputPresetId] = useState("");
  const [outputFormat, setOutputFormat] = useState<"png" | "jpeg" | "webp">("png");
  const [run, setRun] = useState<MediaLabImageRun | null>(null);
  const [comparison, setComparison] = useState<MediaLabImageRun[]>([]);
  const [loading, setLoading] = useState(true);
  const [preparing, setPreparing] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [reviewing, setReviewing] = useState(false);
  const [error, setError] = useState("");

  const refreshHistory = () => {
    void pilotApi.mediaLabImageRuns().then((response) => setHistory(response.items));
  };

  useEffect(() => {
    const controller = new AbortController();
    Promise.all([
      pilotApi.mediaLabImageCapabilities(controller.signal),
      pilotApi.mediaLabImageOrchestration(controller.signal),
      pilotApi.mediaLabImageRuns(controller.signal),
    ])
      .then(([capabilities, planner, runs]) => {
        setCatalog(capabilities);
        setOrchestration(planner);
        setHistory(runs.items);
      })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) {
          setError(marketingErrorMessage(reason));
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (!planningJobId) return;
    setPreparing(true);
    const controller = new AbortController();
    const readJob = async () => {
      try {
        const job = await pilotApi.mediaLabImagePlanningJob(planningJobId, controller.signal);
        if (job.state === "planning") return;
        localStorage.removeItem(imagePlanningJobStorageKey);
        setPlanningJobId("");
        setPreparing(false);
        if (job.plan) {
          localStorage.setItem(imagePreparedJobStorageKey, job.job_id);
          setPreparedJobId(job.job_id);
          setRequest(job.user_request);
          setPlanSources(job.source_asset_ids.map((asset_id) => ({ kind: "media_asset", asset_id })));
          setPlan(job.plan);
          setRun(null);
        } else {
          setError(marketingErrorMessage(new Error(job.error_code ?? "planning_failed")));
        }
      } catch (reason) {
        if (!controller.signal.aborted) {
          localStorage.removeItem(imagePlanningJobStorageKey);
          setPlanningJobId("");
          setPreparing(false);
          setError(marketingErrorMessage(reason));
        }
      }
    };
    void readJob();
    const timer = window.setInterval(() => void readJob(), 2_000);
    return () => {
      controller.abort();
      window.clearInterval(timer);
    };
  }, [planningJobId]);

  useEffect(() => {
    if (!run || !isImageRunInFlight(run)) return;
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      void pilotApi
        .mediaLabImageRun(run.run_id, controller.signal)
        .then(async (next) => {
          if (next.regenerated_run_id) {
            const regenerated = await pilotApi.mediaLabImageRun(
              next.regenerated_run_id,
              controller.signal,
            );
            setRun(regenerated);
          } else {
            setRun(next);
          }
          if (!isImageRunInFlight(next)) refreshHistory();
        })
        .catch((reason: unknown) => {
          if (!controller.signal.aborted) {
            setError(marketingErrorMessage(reason));
          }
        });
    }, 2_000);
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [run]);

  const active = run ? isImageRunInFlight(run) : false;
  const hasUploadingSource = referenceAssets.some(
    (source) => source.state === "pending" || source.state === "uploading" || source.state === "processing",
  );
  const interactionLocked = Boolean(active || preparing || generating || hasUploadingSource);
  const maximumSourceCount = Math.min(orchestration?.max_image_sources ?? 0, maximumReferenceImages);
  const sourceCount = referenceAssets.length + (previousAssetId ? 1 : 0);
  const previousOptions = history.filter(
    (item) => item.generation_state === "succeeded" && item.output_asset_id,
  );
  const selectedCapability = catalog?.items.find(
    (item) => item.capability_id === plan?.capability_id,
  );
  useEffect(() => {
    if (!selectedCapability) return;
    setOutputPresetId((current) => (
      selectedCapability.output_presets.some((preset) => preset.preset_id === current)
        ? current
        : selectedCapability.output_presets[0]?.preset_id ?? ""
    ));
    setOutputFormat((current) => (
      selectedCapability.supported_output_formats.includes(current)
        ? current
        : selectedCapability.supported_output_formats[0] ?? "png"
    ));
  }, [selectedCapability]);

  useEffect(() => {
    if (!run) {
      setComparison([]);
      return;
    }
    const controller = new AbortController();
    void pilotApi
      .mediaLabImageComparison(run.run_id, controller.signal)
      .then((response) => setComparison(response.candidates))
      .catch(() => {
        if (!controller.signal.aborted) setComparison([]);
      });
    return () => controller.abort();
  }, [run]);

  const canGenerate = Boolean(
    plan?.state === "ready"
      && plan.intent
      && plan.production_prompt
      && selectedCapability
      && catalog?.enabled
      && !hasUploadingSource,
  );

  const invalidatePlan = () => {
    setPlan(null);
    setPlanSources([]);
    setPlanningJobId("");
    setPreparedJobId("");
    localStorage.removeItem(imagePlanningJobStorageKey);
    localStorage.removeItem(imagePreparedJobStorageKey);
    setError("");
  };

  const updateSource = (localId: string, update: Partial<SelectedImageSource>) => {
    setReferenceAssets((current) => current.map((source) => (
      source.localId === localId ? { ...source, ...update } : source
    )));
  };

  const addReferenceFiles = async (files: FileList | null) => {
    const additions = Array.from(files ?? []);
    if (additions.length === 0) return;
    const availableSlots = maximumSourceCount - sourceCount;
    if (additions.length > availableSlots) {
      setError(
        t("Media Lab currently accepts at most {count} image sources.").replace(
          "{count}",
          String(maximumSourceCount),
        ),
      );
      return;
    }
    const selected = additions.map((file) => ({
      localId: crypto.randomUUID(),
      label: file.name,
      state: "pending" as const,
      progress: null,
      asset: null,
      error: null,
      file,
    }));
    setReferenceAssets((current) => [
      ...current,
      ...selected.map((source) => ({
        localId: source.localId,
        label: source.label,
        state: source.state,
        progress: source.progress,
        asset: source.asset,
        error: source.error,
      })),
    ]);
    invalidatePlan();

    for (const source of selected) {
      updateSource(source.localId, { state: "uploading", progress: 0 });
      try {
        const asset = await pilotApi.uploadMediaAsset(source.file, "image", (progress) => {
          updateSource(source.localId, {
            state: progress === 100 ? "processing" : "uploading",
            progress,
          });
        });
        updateSource(source.localId, {
          state: "ready",
          progress: 100,
          asset,
          error: null,
        });
      } catch (reason) {
        updateSource(source.localId, {
          state: "failed",
          error: marketingErrorMessage(reason),
        });
      }
    }
  };

  const removeReferenceAsset = (localId: string) => {
    setReferenceAssets((current) => current.filter((source) => source.localId !== localId));
    invalidatePlan();
  };

  const updatePreviousAsset = (assetId: string) => {
    if (assetId && referenceAssets.length >= maximumSourceCount) {
      setError(
        t("Media Lab currently accepts at most {count} image sources. Remove one upload first.").replace(
          "{count}",
          String(maximumSourceCount),
        ),
      );
      return;
    }
    setPreviousAssetId(assetId);
    invalidatePlan();
  };

  const buildSources = (): MediaLabImageSource[] => {
    const uploads = referenceAssets.map((source) => {
      if (source.state !== "ready" || source.asset === null) {
        throw new Error("Wait for every selected image upload to finish before preparing.");
      }
      return { kind: "media_asset" as const, asset_id: source.asset.asset_id };
    });
    if (previousAssetId) uploads.push({ kind: "media_asset", asset_id: previousAssetId });
    return uploads;
  };

  const sourceLabel = (index: number) => {
    const source = referenceAssets[index];
    if (source) return source.label;
    const previous = previousOptions.find((item) => item.output_asset_id === previousAssetId);
    return previous ? `Media Lab image ${previous.run_id.slice(0, 8)}` : t("Previous Media Lab output");
  };

  const prepare = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!orchestration?.enabled || interactionLocked) return;
    if (!request.trim()) {
      setError(t("Describe what you want to create before preparing the plan."));
      return;
    }
    if (sourceCount > maximumSourceCount) {
      setError(
        t("Media Lab currently accepts at most {count} image sources.").replace(
          "{count}",
          String(maximumSourceCount),
        ),
      );
      return;
    }

    setPreparing(true);
    setError("");
    setPreparedJobId("");
    localStorage.removeItem(imagePreparedJobStorageKey);
    try {
      const sources = buildSources();
      const response = await pilotApi.prepareMediaLabImage({
        source_run_id: crypto.randomUUID(),
        user_request: request.trim(),
        sources,
      });
      setPlanSources(sources);
      setPlanningJobId(response.job_id);
      localStorage.setItem(imagePlanningJobStorageKey, response.job_id);
    } catch (reason) {
      setError(marketingErrorMessage(reason));
      setPreparing(false);
    }
  };

  const createImageRun = async (
    activePlan: MediaLabImagePlan,
    capability: MediaLabImageCapability,
    sources: MediaLabImageSource[],
    presetId: string,
    format: "png" | "jpeg" | "webp",
  ) => {
    if (!activePlan.intent || !activePlan.production_prompt) {
      throw new Error("The prepared image request is incomplete.");
    }
    const references: MediaLabImageReferenceRequest[] = activePlan.references.map((reference) => {
        const source = sources[reference.source_index];
        if (!source) throw new Error("Prepared image source is no longer available. Prepare again.");
        return {
          role: reference.role,
          priority: reference.priority,
          must_preserve: reference.must_preserve,
          allowed_changes: reference.allowed_changes,
          identity_group: reference.identity_group,
          source,
        };
      });
    const response = await pilotApi.createMediaLabImageRun({
      intent: activePlan.intent,
      prompt: activePlan.production_prompt,
      references,
      orchestration: activePlan.orchestration,
      ...(capability.supports_output_size && presetId
        ? { output_preset_id: presetId }
        : {}),
      output_format: format,
    });
    setRun(response);
    localStorage.removeItem(imagePreparedJobStorageKey);
    refreshHistory();
  };

  const generate = async () => {
    if (!canGenerate || !plan || !selectedCapability) return;
    setGenerating(true);
    setError("");
    try {
      await createImageRun(plan, selectedCapability, planSources, outputPresetId, outputFormat);
    } catch (reason) {
      setError(marketingErrorMessage(reason));
    } finally {
      setGenerating(false);
    }
  };

  const generateDraft = async () => {
    if (!preparedJobId || plan?.state !== "needs_input" || !catalog?.enabled) return;
    setGenerating(true);
    setError("");
    try {
      const job = await pilotApi.acceptMediaLabImageDraft(preparedJobId);
      if (!job.plan || job.plan.state !== "ready") {
        throw new Error("The draft request could not be prepared.");
      }
      const capability = catalog.items.find(
        (item) => item.capability_id === job.plan?.capability_id,
      );
      if (!capability) throw new Error("The draft image setup is unavailable.");
      const sources = job.source_asset_ids.map((asset_id) => ({
        kind: "media_asset" as const,
        asset_id,
      }));
      const presetId = capability.output_presets.some((preset) => preset.preset_id === outputPresetId)
        ? outputPresetId
        : capability.output_presets[0]?.preset_id ?? "";
      const format = capability.supported_output_formats.includes(outputFormat)
        ? outputFormat
        : capability.supported_output_formats[0] ?? "png";
      setPlan(job.plan);
      setPlanSources(sources);
      setOutputPresetId(presetId);
      setOutputFormat(format);
      await createImageRun(job.plan, capability, sources, presetId, format);
    } catch (reason) {
      setError(marketingErrorMessage(reason));
    } finally {
      setGenerating(false);
    }
  };

  const review = async (decision: "approved" | "rejected") => {
    if (!run || reviewing) return;
    setReviewing(true);
    setError("");
    try {
      const response = await pilotApi.reviewMediaLabImageRun(run.run_id, decision);
      setRun(response);
      refreshHistory();
    } catch (reason) {
      setError(marketingErrorMessage(reason));
    } finally {
      setReviewing(false);
    }
  };

  return (
    <>
      <header className="page-header">
        <div>
          <p className="eyebrow">CREATIVE WORKSPACE</p>
          <h1>{t("Media Lab")}</h1>
          <p>{t("Create and refine marketing images or short video shots from a simple request and your approved source assets.")}</p>
        </div>
      </header>
      <div className="media-lab-workspace-tabs" role="tablist" aria-label={t("Choose what to create")}>
        <button
          aria-controls="media-lab-image-workspace"
          aria-selected={activeWorkspace === "image"}
          className={activeWorkspace === "image" ? "is-active" : ""}
          onClick={() => setActiveWorkspace("image")}
          role="tab"
          type="button"
        >
          <span>{t("Create Image")}</span>
        </button>
        <button
          aria-controls="media-lab-video-workspace"
          aria-selected={activeWorkspace === "video"}
          className={activeWorkspace === "video" ? "is-active" : ""}
          onClick={() => setActiveWorkspace("video")}
          role="tab"
          type="button"
        >
          <span>{t("Create Video")}</span>
        </button>
      </div>
      <div hidden={activeWorkspace !== "image"} id="media-lab-image-workspace" role="tabpanel">
      <section className="panel media-lab-panel">
        <div className="media-lab-section-heading">
          <div>
            <p className="eyebrow">CREATE IMAGE</p>
            <h2>{t("Create or revise an image")}</h2>
          </div>
          <span className={`media-lab-availability ${loading ? "is-checking" : catalog?.enabled && orchestration?.enabled ? "is-ready" : "is-unavailable"}`}>
            {loading ? t("Checking availability") : catalog?.enabled && orchestration?.enabled ? t("Ready") : t("Unavailable")}
          </span>
        </div>
        <p className="media-lab-guidance">{t("Human approval is required before publishing. Check the product, visible text, logo, and material details in every result.")}</p>
        {error && (
          <div role="alert" className="model-lab-error media-lab-friendly-error">
            <strong>{t("Something needs attention")}</strong>
            <p>{t(error)}</p>
          </div>
        )}
        {!loading && orchestration && !orchestration.enabled && (
          <div className="empty-note">
            <p>{t("Image request review is temporarily unavailable.")}</p>
          </div>
        )}
        {!loading && catalog && !catalog.enabled && (
          <div className="empty-note">
            <p>{t("Image creation is temporarily unavailable.")}</p>
          </div>
        )}
        {!loading && orchestration?.enabled && (
          <form className="media-lab-form media-lab-create-form" onSubmit={prepare}>
            <label className="media-lab-prompt">
              <span>{t("Describe the image you want")}</span>
              <AutoResizeTextarea
                value={request}
                onChange={(event) => {
                  setRequest(event.target.value);
                  invalidatePlan();
                }}
                disabled={interactionLocked}
                placeholder={t(
                  "Describe the scene or requested change. Attach the approved product image whenever product fidelity matters.",
                )}
              />
            </label>
            <fieldset className="media-lab-file-picker">
              <legend>{t("Reference images")}</legend>
              <p className="media-lab-mode-description">
                {t(
                  "Add product photos, style references, backgrounds, or another approved visual. You can attach up to {count} images.",
                ).replace("{count}", String(maximumSourceCount))}
              </p>
              <label className="media-lab-upload-zone">
                <span>{t("Upload new images")}</span>
                <strong>{t("Choose files or drop them here")}</strong>
                <input
                  type="file"
                  multiple
                  accept={imageAccept}
                  disabled={interactionLocked || sourceCount >= maximumSourceCount}
                  onChange={(event) => {
                    void addReferenceFiles(event.target.files);
                    event.target.value = "";
                  }}
                />
              </label>
              {referenceAssets.length > 0 && (
                <ul className="media-lab-source-list">
                  {referenceAssets.map((source) => (
                    <li key={source.localId}>
                      {source.asset?.preview_url
                        ? <img src={source.asset.preview_url} alt="" />
                        : <span className="media-lab-source-placeholder" aria-hidden="true" />}
                      <span>
                        {source.label} · {t(source.state)}
                        {source.progress !== null && source.state !== "ready" ? ` ${source.progress}%` : ""}
                        {source.error ? ` · ${source.error}` : ""}
                      </span>
                      <button
                        className="secondary-button"
                        type="button"
                        disabled={interactionLocked}
                        onClick={() => removeReferenceAsset(source.localId)}
                      >
                        {t("Remove")}
                      </button>
                    </li>
                  ))}
                </ul>
              )}
              {previousOptions.length > 0 && (
                <div className="media-lab-library-picker">
                  <div className="media-lab-library-heading">
                    <div>
                      <strong>{t("Continue from a previous result")}</strong>
                    </div>
                    {previousAssetId && <button className="text-link" type="button" onClick={() => updatePreviousAsset("")}>{t("Clear selection")}</button>}
                  </div>
                  <div className="media-lab-asset-grid">
                    {previousOptions.slice(0, 8).map((item) => {
                      const assetId = item.output_asset_id ?? "";
                      const selected = assetId === previousAssetId;
                      return (
                        <button
                          aria-pressed={selected}
                          className={`media-lab-asset-card ${selected ? "is-selected" : ""}`}
                          disabled={interactionLocked || (!selected && referenceAssets.length >= maximumSourceCount)}
                          key={assetId}
                          onClick={() => updatePreviousAsset(selected ? "" : assetId)}
                          type="button"
                        >
                          {item.master_output_url || item.output_url
                            ? <img src={item.master_output_url ?? item.output_url ?? ""} alt={t("Previous generated result")} />
                            : <span className="media-lab-asset-placeholder">{t("Preview unavailable")}</span>}
                          <span>
                            <strong>{t("Image version")} C{item.regeneration_count}</strong>
                            <small>{new Date(item.created_at).toLocaleString()}</small>
                            <small>{t(item.review_state.replaceAll("_", " "))}</small>
                          </span>
                        </button>
                      );
                    })}
                  </div>
                </div>
              )}
            </fieldset>
            <button
              className="secondary-button"
              type="submit"
              disabled={preparing || interactionLocked}
            >
              {preparing ? t("Reviewing your request…") : t("Review request")}
            </button>
          </form>
        )}
        {plan && (
          <ImagePlanCard plan={plan} sourceLabel={sourceLabel} t={t} />
        )}
        {plan?.state === "needs_input" && preparedJobId && catalog?.enabled && (
          <section className="media-lab-draft-override" aria-label={t("Draft generation option")}>
            <div>
              <strong>{t("Generate a draft anyway?")}</strong>
              <p>{t("The image will use your request as written. Visible text and unresolved details may be inaccurate, so careful human review is required.")}</p>
            </div>
            <button
              className="primary-button"
              type="button"
              disabled={generating || interactionLocked}
              onClick={() => void generateDraft()}
            >
              {generating ? t("Starting draft…") : t("Generate draft anyway")}
            </button>
          </section>
        )}
        {canGenerate && selectedCapability && (
          <section className="media-lab-generation-controls" aria-label={t("Generation controls")}>
            <div className="media-lab-options">
              {selectedCapability.supports_output_size ? (
                <label>
                  <span>{t("Output quality and size")}</span>
                  <select
                    value={outputPresetId}
                    onChange={(event) => setOutputPresetId(event.target.value)}
                    disabled={interactionLocked}
                  >
                    {selectedCapability.output_presets.map((preset) => (
                      <option key={preset.preset_id} value={preset.preset_id}>
                        {preset.label} · {preset.width}×{preset.height}
                      </option>
                    ))}
                  </select>
                </label>
              ) : (
                <p className="media-lab-option-note">{t("This plan keeps the product source dimensions.")}</p>
              )}
              <label>
                <span>{t("Delivery format")}</span>
                <select
                  value={outputFormat}
                  onChange={(event) => setOutputFormat(event.target.value as "png" | "jpeg" | "webp")}
                  disabled={interactionLocked}
                >
                  {selectedCapability.supported_output_formats.map((format) => (
                    <option key={format} value={format}>{format.toUpperCase()}</option>
                  ))}
                </select>
              </label>
            </div>
            <button
              className="primary-button"
              type="button"
              disabled={generating || interactionLocked}
              onClick={() => void generate()}
            >
              {generating ? t("Starting…") : t("Create image")}
            </button>
          </section>
        )}
        {run && (
          <ImageRunResult
            run={run}
            comparison={comparison}
            maxRegenerations={orchestration?.max_regenerations ?? 0}
            qualityReviewEnabled={orchestration?.quality_review_enabled ?? false}
            onReview={review}
            reviewing={reviewing}
          />
        )}
      </section>
      </div>
      <div hidden={activeWorkspace !== "video"} id="media-lab-video-workspace" role="tabpanel">
        <MediaLabVideoPanel />
      </div>
    </>
  );
}

function ImagePlanCard({
  plan,
  sourceLabel,
  t,
}: {
  plan: MediaLabImagePlan;
  sourceLabel: (index: number) => string;
  t: (source: string) => string;
}) {
  const ready = plan.state === "ready";
  return (
    <section className="media-lab-plan" aria-live="polite">
      <div className="media-lab-plan-header">
        <div>
          <p className="eyebrow">{ready ? t("READY TO CREATE") : t("MORE INFORMATION NEEDED")}</p>
          <h2>{ready ? t("Request summary") : t("A few details are missing")}</h2>
        </div>
        {ready && <span className="status-chip">{t("Ready")}</span>}
      </div>
      <p>{plan.summary}</p>
      {plan.questions.length > 0 && (
        <div className="media-lab-plan-section">
          <strong>{t("Questions to resolve")}</strong>
          <ul>{plan.questions.map((question) => <li key={question}>{question}</li>)}</ul>
        </div>
      )}
      {plan.uncertainties.length > 0 && (
        <div className="media-lab-plan-section">
          <strong>{t("Uncertainties")}</strong>
          <ul>{plan.uncertainties.map((uncertainty) => <li key={uncertainty}>{uncertainty}</li>)}</ul>
        </div>
      )}
      {ready && (
        <>
          <div className="media-lab-plan-section">
            <strong>{t("How your images will be used")}</strong>
            <div className="media-lab-reference-plan">
              {plan.references.map((reference) => (
                <article key={`${reference.source_index}-${reference.role}`}>
                  <header>
                    <strong>{sourceLabel(reference.source_index)}</strong>
                    <span>{t(reference.role.replaceAll("_", " "))}</span>
                  </header>
                  {reference.must_preserve.length > 0 && (
                    <p><b>{t("Must preserve")}:</b> {reference.must_preserve.join(", ")}</p>
                  )}
                  {reference.allowed_changes.length > 0 && (
                    <p><b>{t("Allowed changes")}:</b> {reference.allowed_changes.join(", ")}</p>
                  )}
                </article>
              ))}
            </div>
          </div>
        </>
      )}
    </section>
  );
}

function ImageRunResult({
  run,
  comparison,
  maxRegenerations,
  qualityReviewEnabled,
  onReview,
  reviewing,
}: {
  run: MediaLabImageRun;
  comparison: MediaLabImageRun[];
  maxRegenerations: number;
  qualityReviewEnabled: boolean;
  onReview: (decision: "approved" | "rejected") => void;
  reviewing: boolean;
}) {
  const { t } = useI18n();
  const checkingQuality = run.generation_state === "succeeded" && (
    run.quality_review_state === "reviewing" || run.quality_review_state === "regenerating"
  );
  const progressStep = run.generation_state === "queued" || run.generation_state === "running"
    ? 1
    : checkingQuality
      ? 2
      : qualityReviewEnabled
        ? 3
        : 2;
  const progressStatus = run.generation_state === "failed" || run.generation_state === "interrupted"
    ? t("Image creation stopped")
    : run.generation_state === "queued"
      ? t("Waiting to create your image")
      : run.generation_state === "running"
        ? t("Creating your image")
        : checkingQuality
          ? t("Checking image quality")
          : t("Image ready for review");
  return (
    <section className="media-lab-result" aria-live="polite">
      <MediaLabJobProgress
        completedAt={checkingQuality ? null : run.completed_at}
        currentStep={progressStep}
        revision={maxRegenerations > 0 ? `${t("Revision")} ${run.regeneration_count + 1} ${t("of")} ${maxRegenerations + 1}` : undefined}
        startedAt={run.started_at ?? run.created_at}
        status={progressStatus}
        steps={qualityReviewEnabled
          ? [t("Request ready"), t("Creating image"), t("Checking quality"), t("Ready for review")]
          : [t("Request ready"), t("Creating image"), t("Ready for review")]}
      />
      {run.retry_of_run_id && (
        <p className="media-lab-review-state">
          {t("This is an improved revision of the previous result.")}
        </p>
      )}
      {run.generation_state === "queued" && (
        <p>
          {run.queue_position
            ? t("Queue position: {position}").replace("{position}", String(run.queue_position))
            : t("Your image is waiting in the generation queue.")}
        </p>
      )}
      {run.generation_state === "running" && <p>{t("Your image is being created. This page updates automatically.")}</p>}
      {run.generation_state === "interrupted" && <p role="alert" className="model-lab-error">{t("Image creation was interrupted. Your request and source images are still saved.")}</p>}
      {run.generation_state === "failed" && <p role="alert" className="model-lab-error">{t("Image creation could not be completed. Your request and source images are still saved.")}</p>}
      {run.generation_state === "succeeded" && run.quality_review_state === "reviewing" && (
        <p>{t("The result is being checked against your original sources. This page updates automatically.")}</p>
      )}
      {run.generation_state === "succeeded" && run.quality_review_state === "regenerating" && (
        <p>{t("The first result needs improvement. A revised version is being created automatically.")}</p>
      )}
      {run.generation_state === "succeeded" && run.quality_review_error_code && (
        <p className="media-lab-quality-fallback">
          {t("Automated quality checking could not finish. Please review this result carefully.")}
        </p>
      )}
      {run.generation_state === "succeeded" && run.output_url && (
        <div className="media-lab-output">
          <img src={run.master_output_url ?? run.output_url} alt={t("Media Lab master output")} />
          <p className="media-lab-option-note">
            {t("Generated master")}: PNG · {run.width ?? "source"}×{run.height ?? "source"} · {run.output_format.toUpperCase()} {t("delivery")}
          </p>
          <a className="secondary-button" href={run.output_url} download>{t("Download output")}</a>
        </div>
      )}
      {run.generation_state === "succeeded" && run.references.length > 0 && (
        <section className="media-lab-verification-sources">
          <strong>{t("Images used for this result")}</strong>
          <p>{t("Compare these sources with the result before approving it.")}</p>
          <div className="media-lab-review-frame-grid">
            {run.references.map((reference) => (
              <a key={reference.reference_id} href={reference.url} target="_blank" rel="noreferrer">
                <img src={reference.url} alt={t("Resolved image source")} />
                <span>{t(reference.role.replaceAll("_", " "))}</span>
              </a>
            ))}
          </div>
        </section>
      )}
      {(run.quality_review || comparison.length > 1) && (
        <details className="media-lab-technical-details">
          <summary>{t("View quality checks and version history")}</summary>
          {run.quality_review && <ImageQualityReviewCard review={run.quality_review} />}
          {comparison.length > 1 && <ImageVersionComparison candidates={comparison} />}
        </details>
      )}
      {run.generation_state === "succeeded" && run.review_state === "awaiting_human_review" && (
        <div className="media-lab-review-actions">
          <strong>{t("Human review required")}</strong>
          <span>{t("Check the exact product, variant, material, logo, labels, and any visible text before approval.")}</span>
          <button className="primary-button" type="button" disabled={reviewing} onClick={() => onReview("approved")}>{t("Approve exact image")}</button>
          <button className="secondary-button" type="button" disabled={reviewing} onClick={() => onReview("rejected")}>{t("Reject")}</button>
        </div>
      )}
    </section>
  );
}


function ImageVersionComparison({
  candidates,
}: {
  candidates: MediaLabImageRun[];
}) {
  const { t } = useI18n();
  return (
    <section className="media-lab-quality-review" aria-label={t("Image version comparison")}>
      <div className="media-lab-quality-review-header">
        <strong>{t("Version comparison")}</strong>
        <span>{candidates.length} {t("versions")}</span>
      </div>
      <p>{t("Compare every generated version against the exact resolved sources before approving the latest version.")}</p>
      <div className="media-lab-review-frame-grid">
        {candidates.map((candidate) => (
          <article key={candidate.run_id}>
            {candidate.output_url ? (
              <img src={candidate.master_output_url ?? candidate.output_url} alt={t("Image version")} />
            ) : (
              <p>{t("Output not available")}</p>
            )}
            <strong>C{candidate.regeneration_count}</strong>
            <small>{new Date(candidate.created_at).toLocaleString()}</small>
            <small>{candidate.quality_review?.summary ?? t("Quality review pending")}</small>
          </article>
        ))}
      </div>
    </section>
  );
}

function ImageQualityReviewCard({
  review,
}: {
  review: NonNullable<MediaLabImageRun["quality_review"]>;
}) {
  const { t } = useI18n();
  return (
    <section className="media-lab-quality-review">
      <div className="media-lab-quality-review-header">
        <strong>{t("Quality summary")}</strong>
        <span className="status-chip">{t(review.decision)}</span>
      </div>
      <p>{review.summary}</p>
      {review.issues.length > 0 && (
        <div>
          <strong>{t("Observed issues")}</strong>
          <ul>
            {review.issues.map((issue) => (
              <li key={`${issue.category}-${issue.description}`}>
                <b>{issue.severity}</b>: {issue.category} — {issue.description}
              </li>
            ))}
          </ul>
        </div>
      )}
      {review.repair_instructions.length > 0 && (
        <div>
          <strong>{t("Automatic repair instructions")}</strong>
          <ul>{review.repair_instructions.map((item) => <li key={item}>{item}</li>)}</ul>
        </div>
      )}
      {review.uncertainties.length > 0 && (
        <div>
          <strong>{t("Items to check manually")}</strong>
          <ul>{review.uncertainties.map((item) => <li key={item}>{item}</li>)}</ul>
        </div>
      )}
      {review.repair_prompt && (
        <div>
          <strong>{t("Updated instructions")}</strong>
          <pre>{review.repair_prompt}</pre>
        </div>
      )}
    </section>
  );
}

function isImageRunInFlight(run: MediaLabImageRun): boolean {
  return (
    ["queued", "running"].includes(run.generation_state)
    || ["reviewing", "regenerating"].includes(run.quality_review_state)
  );
}
