import { useEffect, useState, type FormEvent } from "react";
import { AutoResizeTextarea } from "../components/AutoResizeTextarea";
import { MediaLabJobProgress } from "../components/MediaLabJobProgress";
import { MediaLabFinalVideoAdPanel } from "./MediaLabFinalVideoAdPanel";
import { useI18n } from "../hooks/useI18n";
import { pilotApi } from "../services/pilotApi";
import { marketingErrorMessage } from "../services/http";
import type {
  MediaAsset,
  MediaLabImageRun,
  MediaLabVideoCapabilities,
  MediaLabVideoOrchestrationStatus,
  MediaLabVideoPlan,
  MediaLabVideoSourceRequest,
  MediaLabVideoRun,
  MediaLabVideoSource,
} from "../types/pilotApi";

const imageAccept = "image/jpeg,image/png,image/webp,image/avif,image/tiff,.tif,.tiff";
const videoPlanningJobStorageKey = "media-lab-video-planning-job";
const defaultDurations = [5, 6, 7, 8, 9, 10];
const maximumReferenceImages = 10;

type SourceAssetState = "pending" | "uploading" | "processing" | "ready" | "failed";

type SelectedVideoSource = {
  localId: string;
  label: string;
  state: SourceAssetState;
  progress: number | null;
  asset: MediaAsset | null;
  error: string | null;
};

export function MediaLabVideoPanel() {
  const { t } = useI18n();
  const [mode, setMode] = useState<"final-ad" | "short-shot">("final-ad");

  return (
    <>
      <div className="media-lab-view-switcher" role="tablist" aria-label={t("Video workflow")}>
        <button
          aria-selected={mode === "final-ad"}
          className={mode === "final-ad" ? "primary-button" : "secondary-button"}
          onClick={() => setMode("final-ad")}
          role="tab"
          type="button"
        >
          {t("Final Ad 20–25s")}
        </button>
        <button
          aria-selected={mode === "short-shot"}
          className={mode === "short-shot" ? "primary-button" : "secondary-button"}
          onClick={() => setMode("short-shot")}
          role="tab"
          type="button"
        >
          {t("Short source clip")}
        </button>
      </div>
      {mode === "final-ad" ? <MediaLabFinalVideoAdPanel /> : <MediaLabShortVideoPanel />}
    </>
  );
}

function MediaLabShortVideoPanel() {
  const { t } = useI18n();
  const [catalog, setCatalog] = useState<MediaLabVideoCapabilities | null>(null);
  const [orchestration, setOrchestration] = useState<MediaLabVideoOrchestrationStatus | null>(null);
  const [imageHistory, setImageHistory] = useState<MediaLabImageRun[]>([]);
  const [request, setRequest] = useState("");
  const [sourceAssets, setSourceAssets] = useState<SelectedVideoSource[]>([]);
  const [previousImageAssetIds, setPreviousImageAssetIds] = useState<string[]>([]);
  const [durationSeconds, setDurationSeconds] = useState(5);
  const [outputPresetId, setOutputPresetId] = useState("");
  const [outputFormat, setOutputFormat] = useState<"mp4">("mp4");
  const [plan, setPlan] = useState<MediaLabVideoPlan | null>(null);
  const [planSources, setPlanSources] = useState<MediaLabVideoSource[]>([]);
  const [planningJobId, setPlanningJobId] = useState(() => localStorage.getItem(videoPlanningJobStorageKey) ?? "");
  const [run, setRun] = useState<MediaLabVideoRun | null>(null);
  const [comparison, setComparison] = useState<MediaLabVideoRun[]>([]);
  const [loading, setLoading] = useState(true);
  const [preparing, setPreparing] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [reviewing, setReviewing] = useState(false);
  const [error, setError] = useState("");

  const refreshImageHistory = () => {
    void pilotApi.mediaLabImageRuns().then((response) => setImageHistory(response.items));
  };

  useEffect(() => {
    const controller = new AbortController();
    Promise.all([
      pilotApi.mediaLabVideoCapabilities(controller.signal),
      pilotApi.mediaLabVideoOrchestration(controller.signal),
      pilotApi.mediaLabImageRuns(controller.signal),
    ])
      .then(([capabilities, planner, images]) => {
        setCatalog(capabilities);
        setOrchestration(planner);
        setImageHistory(images.items);
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
        const job = await pilotApi.mediaLabVideoPlanningJob(planningJobId, controller.signal);
        if (job.state === "planning") return;
        localStorage.removeItem(videoPlanningJobStorageKey);
        setPlanningJobId("");
        setPreparing(false);
        if (job.plan) {
          setRequest(job.user_request);
          setPlanSources(job.source_asset_ids.map((asset_id) => ({ kind: "media_asset", asset_id })));
          setPlan(job.plan);
          setRun(null);
        } else {
          setError(marketingErrorMessage(new Error(job.error_code ?? "planning_failed")));
        }
      } catch (reason) {
        if (!controller.signal.aborted) {
          localStorage.removeItem(videoPlanningJobStorageKey);
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
    if (!run || !isVideoRunInFlight(run)) return;
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      void pilotApi
        .mediaLabVideoRun(run.run_id, controller.signal)
        .then(async (current) => {
          const next = current.regenerated_run_id
            ? await pilotApi.mediaLabVideoRun(current.regenerated_run_id, controller.signal)
            : current;
          setRun(next);
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

  const active = run ? isVideoRunInFlight(run) : false;
  const hasUploadingSource = sourceAssets.some(
    (source) => source.state === "pending" || source.state === "uploading" || source.state === "processing",
  );
  const interactionLocked = Boolean(active || preparing || generating || hasUploadingSource);
  const maximumSourceCount = Math.min(orchestration?.max_image_sources ?? 0, maximumReferenceImages);
  const maximumGenerationSourceCount = Math.min(
    orchestration?.max_generation_image_sources ?? 0,
    maximumReferenceImages,
  );
  const sourceCount = sourceAssets.length + previousImageAssetIds.length;
  const previousImageOptions = imageHistory.filter(
    (item) => item.generation_state === "succeeded" && item.output_asset_id,
  );
  const selectedCapability = catalog?.items.find(
    (item) => item.capability_id === plan?.capability_id,
  );
  const durationOptions = selectedCapability?.supported_duration_seconds ?? defaultDurations;

  useEffect(() => {
    if (!selectedCapability) return;
    setOutputPresetId((current) => (
      selectedCapability.output_presets.some((preset) => preset.preset_id === current)
        ? current
        : selectedCapability.default_output_preset_id ?? selectedCapability.output_presets[0]?.preset_id ?? ""
    ));
    setOutputFormat((current) => (
      selectedCapability.supported_output_formats.includes(current)
        ? current
        : selectedCapability.supported_output_formats[0] ?? "mp4"
    ));
  }, [selectedCapability]);

  useEffect(() => {
    if (!run) {
      setComparison([]);
      return;
    }
    const controller = new AbortController();
    void pilotApi
      .mediaLabVideoComparison(run.run_id, controller.signal)
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
    localStorage.removeItem(videoPlanningJobStorageKey);
    setError("");
  };

  const updateSource = (localId: string, update: Partial<SelectedVideoSource>) => {
    setSourceAssets((current) => current.map((source) => (
      source.localId === localId ? { ...source, ...update } : source
    )));
  };

  const selectSourceFiles = async (files: FileList | null) => {
    const additions = Array.from(files ?? []);
    if (additions.length === 0) return;
    if (sourceCount + additions.length > maximumSourceCount) {
      setError(
        t("Attach at most {count} image sources.").replace(
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
    setSourceAssets((current) => [
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

  const removeSourceAsset = (localId: string) => {
    setSourceAssets((current) => current.filter((source) => source.localId !== localId));
    invalidatePlan();
  };

  const togglePreviousImage = (assetId: string) => {
    setPreviousImageAssetIds((current) => {
      if (current.includes(assetId)) return current.filter((item) => item !== assetId);
      if (sourceAssets.length + current.length >= maximumSourceCount) {
        setError(
          t("Attach at most {count} image sources.").replace(
            "{count}",
            String(maximumSourceCount),
          ),
        );
        return current;
      }
      return [...current, assetId];
    });
    invalidatePlan();
  };

  const buildSources = (): MediaLabVideoSource[] => {
    const uploads = sourceAssets.map((source) => {
      if (source.state !== "ready" || source.asset === null) {
        throw new Error("Wait for every selected image upload to finish before preparing.");
      }
      return { kind: "media_asset" as const, asset_id: source.asset.asset_id };
    });
    return [
      ...uploads,
      ...previousImageAssetIds.map((assetId) => ({ kind: "media_asset" as const, asset_id: assetId })),
    ];
  };

  const sourceLabel = (index: number) => {
    const source = sourceAssets[index];
    if (source) return source.label;
    const assetId = previousImageAssetIds[index - sourceAssets.length];
    const previous = previousImageOptions.find((item) => item.output_asset_id === assetId);
    return previous ? `Media Lab image ${previous.run_id.slice(0, 8)}` : t("Video image source");
  };

  const prepare = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!orchestration?.enabled || interactionLocked) return;
    if (!request.trim()) {
      setError(t("Describe the video shot before preparing the plan."));
      return;
    }
    if (sourceCount > maximumSourceCount) {
      setError(
        t("Media Lab currently accepts at most {count} image source for this video flow.").replace(
          "{count}",
          String(maximumSourceCount),
        ),
      );
      return;
    }

    setPreparing(true);
    setError("");
    try {
      const sources = buildSources();
      const response = await pilotApi.prepareMediaLabVideo({
        source_run_id: crypto.randomUUID(),
        user_request: request.trim(),
        sources,
      });
      setPlanSources(sources);
      setPlanningJobId(response.job_id);
      localStorage.setItem(videoPlanningJobStorageKey, response.job_id);
    } catch (reason) {
      setError(marketingErrorMessage(reason));
      setPreparing(false);
    }
  };

  const generate = async () => {
    if (!canGenerate || !plan?.intent || !plan.production_prompt || !selectedCapability) return;
    setGenerating(true);
    setError("");
    try {
      const sources = planSources;
      const resolvedSources: MediaLabVideoSourceRequest[] = plan.sources.map((item) => {
        const source = sources[item.source_index];
        if (!source) throw new Error("Prepared video source is no longer available. Prepare again.");
        return {
          source_index: item.source_index,
          role: item.role,
          usage: item.usage,
          priority: item.priority,
          must_preserve: item.must_preserve,
          allowed_changes: item.allowed_changes,
          identity_group: item.identity_group,
          is_primary_identity: item.is_primary_identity,
          source,
        };
      });
      const response = await pilotApi.createMediaLabVideoRun({
        intent: plan.intent,
        prompt: plan.production_prompt,
        sources: resolvedSources,
        verification_plan: plan.verification_plan,
        duration_seconds: durationSeconds,
        orchestration: plan.orchestration,
        ...(outputPresetId ? { output_preset_id: outputPresetId } : {}),
        output_format: outputFormat,
      });
      setRun(response);
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
      setRun(await pilotApi.reviewMediaLabVideoRun(run.run_id, decision));
    } catch (reason) {
      setError(marketingErrorMessage(reason));
    } finally {
      setReviewing(false);
    }
  };

  return (
    <section className="panel media-lab-panel media-lab-video-panel">
      <div className="media-lab-section-heading">
        <div>
          <p className="eyebrow">CREATE VIDEO</p>
          <h2>{t("Create a short video")}</h2>
        </div>
        <span className={`media-lab-availability ${loading ? "is-checking" : catalog?.enabled && orchestration?.enabled ? "is-ready" : "is-unavailable"}`}>
          {loading ? t("Checking availability") : catalog?.enabled && orchestration?.enabled ? t("Ready") : t("Unavailable")}
        </span>
      </div>
      <p className="media-lab-guidance">{t("Human approval is required before publishing. Review the full motion, product details, and audio in every result.")}</p>
      {error && (
        <div role="alert" className="model-lab-error media-lab-friendly-error">
          <strong>{t("Something needs attention")}</strong>
          <p>{t(error)}</p>
        </div>
      )}
      {!loading && orchestration && !orchestration.enabled && (
        <div className="empty-note">
          <p>{t("Video request review is temporarily unavailable.")}</p>
        </div>
      )}
      {!loading && catalog && !catalog.enabled && (
        <div className="empty-note">
          <p>{t("Video creation is temporarily unavailable.")}</p>
        </div>
      )}
      {!loading && orchestration?.enabled && (
        <form className="media-lab-form media-lab-create-form" onSubmit={prepare}>
          <label className="media-lab-prompt">
            <span>{t("Describe the video you want")}</span>
            <AutoResizeTextarea
              value={request}
              onChange={(event) => {
                setRequest(event.target.value);
                invalidatePlan();
              }}
              disabled={interactionLocked}
              placeholder={t(
                "Describe the subject, action, setting, camera, lighting, and how any attached images should be used.",
              )}
            />
          </label>
          <fieldset className="media-lab-file-picker">
            <legend>{t("Reference images (optional)")}</legend>
            <p className="media-lab-mode-description">
              {t("Add product photos, people, backgrounds, style references, keyframes, or storyboard images.")}
            </p>
            <p className="media-lab-mode-description">
              {t("This video setup can currently use {count} selected image directly while creating the shot.").replace("{count}", String(maximumGenerationSourceCount))}
            </p>
            <label className="media-lab-upload-zone">
              <span>{t("Upload new images")}</span>
              <strong>{t("Choose files or drop them here")}</strong>
              <input
                type="file"
                accept={imageAccept}
                multiple
                disabled={interactionLocked || sourceCount >= maximumSourceCount}
                onChange={(event) => {
                  void selectSourceFiles(event.target.files);
                  event.target.value = "";
                }}
              />
            </label>
            {sourceAssets.length > 0 && (
              <ul className="media-lab-source-list">
                {sourceAssets.map((source) => (
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
                      onClick={() => removeSourceAsset(source.localId)}
                    >
                      {t("Remove")}
                    </button>
                  </li>
                ))}
              </ul>
            )}
            {previousImageOptions.length > 0 && (
              <div className="media-lab-library-picker">
                <div className="media-lab-library-heading">
                  <div>
                    <strong>{t("Choose from your recent images")}</strong>
                  </div>
                  <button className="text-link" type="button" onClick={refreshImageHistory}>{t("Refresh")}</button>
                </div>
                <div className="media-lab-asset-grid">
                  {previousImageOptions.slice(0, 8).map((item) => {
                    const assetId = item.output_asset_id;
                    if (assetId === null) return null;
                    const selected = previousImageAssetIds.includes(assetId);
                    return (
                      <button
                        aria-pressed={selected}
                        className={`media-lab-asset-card ${selected ? "is-selected" : ""}`}
                        disabled={interactionLocked}
                        key={assetId}
                        onClick={() => togglePreviousImage(assetId)}
                        type="button"
                      >
                        {item.master_output_url || item.output_url
                          ? <img src={item.master_output_url ?? item.output_url ?? ""} alt={t("Recent generated image")} />
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
          <button className="secondary-button" type="submit" disabled={preparing || interactionLocked}>
            {preparing ? t("Reviewing your request…") : t("Review request")}
          </button>
        </form>
      )}
      {plan && (
        <VideoPlanCard
          plan={plan}
          qualityReviewEnabled={orchestration?.quality_review_enabled ?? false}
          sourceLabel={sourceLabel}
        />
      )}
      {canGenerate && selectedCapability && (
        <section className="media-lab-generation-controls" aria-label={t("Video generation controls")}>
          <div className="media-lab-options">
            <label>
              <span>{t("Duration")}</span>
              <select
                value={durationSeconds}
                disabled={interactionLocked}
                onChange={(event) => setDurationSeconds(Number(event.target.value))}
              >
                {durationOptions.map((duration) => <option key={duration} value={duration}>{duration}s</option>)}
              </select>
            </label>
            <label>
              <span>{t("Output size")}</span>
              <select
                value={outputPresetId}
                disabled={interactionLocked}
                onChange={(event) => setOutputPresetId(event.target.value)}
              >
                {selectedCapability.output_presets.map((preset) => (
                  <option key={preset.preset_id} value={preset.preset_id}>
                    {preset.label}
                  </option>
                ))}
              </select>
            </label>
            <label>
              <span>{t("Delivery format")}</span>
              <select
                value={outputFormat}
                disabled={interactionLocked}
                onChange={(event) => setOutputFormat(event.target.value as "mp4")}
              >
                {selectedCapability.supported_output_formats.map((format) => (
                  <option key={format} value={format}>{format.toUpperCase()}</option>
                ))}
              </select>
            </label>
          </div>
          <button className="primary-button" type="button" disabled={generating || interactionLocked} onClick={() => void generate()}>
            {generating ? t("Starting…") : t("Create video")}
          </button>
        </section>
      )}
      {run && (
        <VideoRunResult
          run={run}
          comparison={comparison}
          maxRegenerations={orchestration?.max_regenerations ?? 0}
          qualityReviewEnabled={orchestration?.quality_review_enabled ?? false}
          onReview={review}
          reviewing={reviewing}
        />
      )}
    </section>
  );
}

function VideoPlanCard({
  plan,
  qualityReviewEnabled,
  sourceLabel,
}: {
  plan: MediaLabVideoPlan;
  qualityReviewEnabled: boolean;
  sourceLabel: (index: number) => string;
}) {
  const { t } = useI18n();
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
            {plan.sources.length === 0 ? (
              <p>{t("This video will be created from your written request only.")}</p>
            ) : (
              <div className="media-lab-reference-plan">
                {plan.sources.map((reference) => (
                  <article key={`${reference.source_index}-${reference.role}`}>
                    <header>
                      <strong>{sourceLabel(reference.source_index)}</strong>
                      <span>{t(reference.role.replaceAll("_", " "))} · {videoUsageLabel(reference.usage, t)}</span>
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
            )}
          </div>
          {qualityReviewEnabled && (
            <div className="media-lab-plan-section">
              <strong>{t("Quality checks")}</strong>
              <p>{t("The video will be checked for visual stability and consistency before it is ready for human review.")}</p>
            </div>
          )}
        </>
      )}
    </section>
  );
}

function VideoRunResult({
  run,
  comparison,
  maxRegenerations,
  qualityReviewEnabled,
  onReview,
  reviewing,
}: {
  run: MediaLabVideoRun;
  comparison: MediaLabVideoRun[];
  maxRegenerations: number;
  qualityReviewEnabled: boolean;
  onReview: (decision: "approved" | "rejected") => void;
  reviewing: boolean;
}) {
  const { t } = useI18n();
  const verificationBlocked = run.verification_state === "failed" || run.verification_error_code !== null;
  const terraBlocked = (
    run.quality_review_state === "unavailable"
    || (
      run.quality_review_error_code !== null
      && run.quality_review_error_code !== "retry_budget_exhausted"
    )
  );
  const canHumanReview = (
    run.review_state === "awaiting_human_review"
    && (
      !qualityReviewEnabled
      || (
        run.verification_state === "verified"
        && run.verification !== null
        && !verificationBlocked
        && run.quality_review !== null
        && !terraBlocked
      )
    )
  );

  const checkingQuality = qualityReviewEnabled && run.generation_state === "succeeded" && (
    run.verification_state === "verifying"
    || run.quality_review_state === "reviewing"
    || run.quality_review_state === "regenerating"
  );
  const progressStep = run.generation_state === "queued" || run.generation_state === "running"
    ? 1
    : checkingQuality
      ? 3
      : 4;
  const progressStatus = run.generation_state === "failed" || run.generation_state === "interrupted"
    ? t("Video creation stopped")
    : run.generation_state === "queued"
      ? t("Waiting to create your video")
      : run.generation_state === "running"
        ? t("Creating your video")
        : checkingQuality
          ? t("Checking video quality")
          : qualityReviewEnabled && (verificationBlocked || terraBlocked)
            ? t("Video ready — quality check needs attention")
            : t("Video ready for review");

  return (
    <section className="media-lab-result" aria-live="polite">
      <MediaLabJobProgress
        completedAt={checkingQuality ? null : run.completed_at}
        currentStep={progressStep}
        revision={maxRegenerations > 0 ? `${t("Revision")} ${run.regeneration_count + 1} ${t("of")} ${maxRegenerations + 1}` : undefined}
        startedAt={run.started_at ?? run.created_at}
        status={progressStatus}
        steps={qualityReviewEnabled
          ? [t("Request ready"), t("Creating video"), t("Processing output"), t("Checking quality"), t("Ready for review")]
          : [t("Request ready"), t("Creating video"), t("Processing output"), t("Ready for review")]}
      />
      {run.retry_of_run_id && (
        <p className="media-lab-review-state">
          {t("This is an improved revision of the previous result.")}
        </p>
      )}
      {run.regenerated_run_id && (
        <p className="media-lab-review-state">
          {t("A revised version is being created automatically.")}
        </p>
      )}
      {run.generation_state === "queued" && (
        <p>
          {run.queue_position
            ? t("Queue position: {position}").replace("{position}", String(run.queue_position))
            : t("Your video is waiting in the generation queue.")}
        </p>
      )}
      {run.generation_state === "running" && <p>{t("Your video is being created. This page updates automatically.")}</p>}
      {run.generation_state === "interrupted" && <p role="alert" className="model-lab-error">{t("Video creation was interrupted. Your request and source images are still saved.")}</p>}
      {run.generation_state === "failed" && <p role="alert" className="model-lab-error">{t("Video creation could not be completed. Your request and source images are still saved.")}</p>}
      {run.generation_state === "succeeded" && run.verification_state === "verifying" && (
        <p>{t("The full video is being checked for visual stability and consistency.")}</p>
      )}
      {run.generation_state === "succeeded" && run.quality_review_state === "reviewing" && (
        <p>{t("The quality results are being prepared for review.")}</p>
      )}
      {run.generation_state === "succeeded" && run.quality_review_state === "regenerating" && (
        <p>{t("The first result needs improvement. A revised version is being created automatically.")}</p>
      )}
      {qualityReviewEnabled && run.generation_state === "succeeded" && verificationBlocked && (
        <p role="alert" className="model-lab-error">
          {t("Automated quality checking could not finish. You can still view and download the video, but approval is unavailable until the check is restored.")}
        </p>
      )}
      {qualityReviewEnabled && run.generation_state === "succeeded" && terraBlocked && (
        <p role="alert" className="model-lab-error">
          {t("The final quality summary could not be completed. You can still view and download the video, but approval is unavailable.")}
        </p>
      )}
      {qualityReviewEnabled && run.generation_state === "succeeded" && run.quality_review_error_code === "retry_budget_exhausted" && (
        <p className="media-lab-review-state">
          {t("Automatic revisions are complete. This exact version now requires human review.")}
        </p>
      )}
      {run.generation_state === "succeeded" && run.sources.length > 0 && (
        <section className="media-lab-verification-sources">
          <strong>{t("Images used for this video")}</strong>
          <p>{t("Compare these images with the video before approving it.")}</p>
          <div className="media-lab-review-frame-grid">
            {run.sources.map((source) => (
              <a key={source.source_id} href={source.url} target="_blank" rel="noreferrer">
                <img src={source.url} alt={t("Resolved video source")} />
                <span>{t(source.role.replaceAll("_", " "))} · {videoUsageLabel(source.usage, t)}</span>
              </a>
            ))}
          </div>
        </section>
      )}
      {run.generation_state === "succeeded" && (run.verification_frames.length > 0 || run.verification) && (
        <details className="media-lab-technical-details media-lab-evidence-details">
          <summary>{t("View quality check details")}</summary>
          <VideoVerificationEvidence
            frames={run.verification_frames}
            verification={run.verification}
          />
        </details>
      )}
      {run.generation_state === "succeeded" && run.quality_review && (
        <VideoQualityReviewCard review={run.quality_review} />
      )}
      {comparison.length > 0 && <VideoVersionComparison candidates={comparison} />}
      {run.generation_state === "succeeded" && run.output_url && (
        <div className="media-lab-output">
          <video controls src={run.output_url}>{t("Your browser cannot play this video.")}</video>
          <p className="media-lab-option-note">
            {run.aspect_ratio ?? t("Original ratio")} · {run.actual_width ?? "pending"}×{run.actual_height ?? "pending"} · {run.actual_duration_milliseconds ? `${(run.actual_duration_milliseconds / 1_000).toFixed(2)}s` : `${run.duration_seconds}s`} · {run.output_format.toUpperCase()}
          </p>
          {canHumanReview && (
            <div className="media-lab-review-actions">
              <strong>{t("Human review required")}</strong>
              <span>
                {t("Check the product details, full motion, unusual distortion or flicker, camera movement, and audio before approval.")}
              </span>
              <button className="primary-button" type="button" disabled={reviewing} onClick={() => onReview("approved")}>{t("Approve exact video")}</button>
              <button className="secondary-button" type="button" disabled={reviewing} onClick={() => onReview("rejected")}>{t("Reject")}</button>
            </div>
          )}
          <a className="secondary-button" href={run.output_url} download>{t("Download output")}</a>
        </div>
      )}
    </section>
  );
}


function VideoVersionComparison({
  candidates,
}: {
  candidates: MediaLabVideoRun[];
}) {
  const { t } = useI18n();
  return (
    <section className="media-lab-quality-review" aria-label={t("Video version comparison")}>
      <div className="media-lab-quality-review-header">
        <strong>{t("Version comparison")}</strong>
        <span>{candidates.length} {t("versions")}</span>
      </div>
      <p>{t("Compare every revision with the original sources before approving the latest version.")}</p>
      <div className="media-lab-review-frame-grid">
        {candidates.map((candidate) => (
          <article key={candidate.run_id}>
            {candidate.output_url ? (
              <video controls src={candidate.output_url}>{t("Your browser cannot play this video.")}</video>
            ) : (
              <p>{t("Output not available")}</p>
            )}
            <strong>C{candidate.regeneration_count}</strong>
            <small>{new Date(candidate.created_at).toLocaleString()}</small>
            <small>{candidate.quality_review?.summary ?? t("Quality review pending")}</small>
            {candidate.verification?.suspicious_timestamps_milliseconds.length ? (
              <small>{t("Suspicious timestamps")}: {candidate.verification.suspicious_timestamps_milliseconds.map((value) => `${(value / 1_000).toFixed(2)}s`).join(", ")}</small>
            ) : null}
          </article>
        ))}
      </div>
    </section>
  );
}

function VideoVerificationEvidence({
  frames,
  verification,
}: {
  frames: MediaLabVideoRun["verification_frames"];
  verification: MediaLabVideoRun["verification"];
}) {
  const { t } = useI18n();
  return (
    <section className="media-lab-verification" aria-label={t("Automated video quality checks")}>
      <div className="media-lab-verification-header">
        <strong>{t("Automated quality check evidence")}</strong>
        {verification && <span className="status-chip">{t(verification.status)}</span>}
      </div>
      <p className="media-lab-evidence-summary">
        {t("These checks help identify possible issues. Human approval is still required before publishing.")}
      </p>
      {frames.length > 0 && (
        <div>
          <strong>{t("Persisted temporal evidence")}</strong>
          <div className="media-lab-review-frame-grid">
            {frames.map((frame) => (
              <a key={`${frame.label}-${frame.timestamp_milliseconds}`} href={frame.url} target="_blank" rel="noreferrer">
                <img src={frame.url} alt={`${frame.label} at ${(frame.timestamp_milliseconds / 1_000).toFixed(2)} seconds`} />
                <span>{(frame.timestamp_milliseconds / 1_000).toFixed(2)}s</span>
              </a>
            ))}
          </div>
        </div>
      )}
      {verification && (
        <>
          <div className="media-lab-verification-stages">
            {verification.stages.map((stage) => (
              <article key={`${stage.stage}-${stage.model}`}>
                <header>
                  <strong>{stage.stage.replaceAll("_", " ")}</strong>
                  <span className="status-chip">{t(stage.status)}</span>
                </header>
                <small>{t(stage.status)}</small>
                {stage.observations.length > 0 && (
                  <ul>
                    {stage.observations.map((observation) => (
                      <li key={observation.observation_id}>
                        <b>{observation.severity}</b>: {observation.description}
                        {observation.start_timestamp_milliseconds !== null && ` (${(observation.start_timestamp_milliseconds / 1000).toFixed(2)}s)`}
                      </li>
                    ))}
                  </ul>
                )}
              </article>
            ))}
          </div>
          {verification.suspicious_timestamps_milliseconds.length > 0 && (
            <p className="media-lab-evidence-summary">
              {t("Suspicious timestamps")}: {verification.suspicious_timestamps_milliseconds.map((value) => `${(value / 1000).toFixed(2)}s`).join(", ")}
            </p>
          )}
          {verification.uncertainties.length > 0 && (
            <ul>
              {verification.uncertainties.map((item) => <li key={item}>{item}</li>)}
            </ul>
          )}
        </>
      )}
    </section>
  );
}

function VideoQualityReviewCard({
  review,
}: {
  review: NonNullable<MediaLabVideoRun["quality_review"]>;
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


function videoUsageLabel(usage: "generation" | "verification" | "both", t: (source: string) => string): string {
  if (usage === "generation") return t("Used to create");
  if (usage === "verification") return t("Used for quality checking");
  return t("Used to create and check quality");
}

function isVideoRunInFlight(run: MediaLabVideoRun): boolean {
  return (
    ["queued", "running"].includes(run.generation_state)
    || run.verification_state === "verifying"
    || ["reviewing", "regenerating"].includes(run.quality_review_state)
  );
}
