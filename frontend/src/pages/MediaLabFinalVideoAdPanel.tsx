import { useEffect, useState, type FormEvent } from "react";
import { AutoResizeTextarea } from "../components/AutoResizeTextarea";
import { MediaLabJobProgress } from "../components/MediaLabJobProgress";
import { useI18n } from "../hooks/useI18n";
import { pilotApi } from "../services/pilotApi";
import { marketingErrorMessage } from "../services/http";
import type {
  MediaAsset,
  MediaLabVideoAd,
  MediaLabVideoCapabilities,
  MediaLabVideoOrchestrationStatus,
} from "../types/pilotApi";

const imageAccept = "image/jpeg,image/png,image/webp,image/avif,image/tiff,.tif,.tiff";
const activeStates = new Set([
  "planning",
  "generating_shots",
  "selecting_segments",
  "assembling",
  "cancel_requested",
]);

type UploadItem = {
  id: string;
  name: string;
  progress: number;
  asset: MediaAsset | null;
  error: string | null;
};

export function MediaLabFinalVideoAdPanel() {
  const { t } = useI18n();
  const [request, setRequest] = useState("");
  const [brand, setBrand] = useState("");
  const [sku, setSku] = useState("");
  const [angle, setAngle] = useState("");
  const [cta, setCta] = useState("");
  const [duration, setDuration] = useState(22);
  const [aspectRatio, setAspectRatio] = useState<"1:1" | "9:16" | "16:9">("9:16");
  const [sources, setSources] = useState<UploadItem[]>([]);
  const [logo, setLogo] = useState<UploadItem | null>(null);
  const [job, setJob] = useState<MediaLabVideoAd | null>(null);
  const [capabilities, setCapabilities] = useState<MediaLabVideoCapabilities | null>(null);
  const [orchestration, setOrchestration] = useState<MediaLabVideoOrchestrationStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    Promise.all([
      pilotApi.mediaLabVideoCapabilities(controller.signal),
      pilotApi.mediaLabVideoOrchestration(controller.signal),
    ])
      .then(([videoCapabilities, videoOrchestration]) => {
        setCapabilities(videoCapabilities);
        setOrchestration(videoOrchestration);
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
    if (!job || !activeStates.has(job.state)) return;
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      void pilotApi
        .mediaLabVideoAd(job.job_id, controller.signal)
        .then(setJob)
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
  }, [job]);

  const uploading = sources.some((source) => source.asset === null && source.error === null)
    || (logo !== null && logo.asset === null && logo.error === null);
  const running = Boolean(job && activeStates.has(job.state));
  const available = Boolean(capabilities?.enabled && orchestration?.enabled);
  const interactionDisabled = running || loading || !available;

  const uploadSources = async (files: FileList | null) => {
    const selected = Array.from(files ?? []);
    if (sources.length + selected.length > 8) {
      setError(t("Attach at most 8 image sources."));
      return;
    }
    const items = selected.map((file) => ({
      id: crypto.randomUUID(),
      name: file.name,
      progress: 0,
      asset: null,
      error: null,
      file,
    }));
    setSources((current) => [
      ...current,
      ...items.map((item) => ({ id: item.id, name: item.name, progress: 0, asset: null, error: null })),
    ]);
    for (const item of items) {
      try {
        const asset = await pilotApi.uploadMediaAsset(item.file, "image", (progress) => {
          setSources((current) => current.map((source) => (
            source.id === item.id ? { ...source, progress } : source
          )));
        });
        setSources((current) => current.map((source) => (
          source.id === item.id ? { ...source, asset, progress: 100 } : source
        )));
      } catch (reason) {
        setSources((current) => current.map((source) => (
          source.id === item.id
            ? { ...source, error: marketingErrorMessage(reason) }
            : source
        )));
      }
    }
  };

  const uploadLogo = async (file: File | undefined) => {
    if (!file) return;
    const item: UploadItem = {
      id: crypto.randomUUID(),
      name: file.name,
      progress: 0,
      asset: null,
      error: null,
    };
    setLogo(item);
    try {
      const asset = await pilotApi.uploadMediaAsset(file, "image", (progress) => {
        setLogo((current) => current ? { ...current, progress } : current);
      });
      setLogo((current) => current ? { ...current, asset, progress: 100 } : current);
    } catch (reason) {
      setLogo((current) => current
        ? { ...current, error: marketingErrorMessage(reason) }
        : current);
    }
  };

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (uploading || interactionDisabled) return;
    if (!request.trim() || !brand.trim() || !sku.trim() || !angle.trim()) {
      setError(t("Request, brand, SKU, and angle are required."));
      return;
    }
    const failedUpload = sources.find((source) => source.asset === null);
    if (failedUpload) {
      setError(t("Remove failed uploads or upload them again before creating the Ad."));
      return;
    }
    setSubmitting(true);
    setError("");
    try {
      const created = await pilotApi.createMediaLabVideoAd({
        source_run_id: crypto.randomUUID(),
        user_request: request.trim(),
        brand: brand.trim(),
        sku: sku.trim(),
        angle: angle.trim(),
        source_asset_ids: sources.flatMap((source) => source.asset ? [source.asset.asset_id] : []),
        target_duration_seconds: duration,
        aspect_ratio: aspectRatio,
        candidate_count: 1,
        ...(cta.trim() ? { cta_text: cta.trim() } : {}),
        ...(logo?.asset ? { logo_asset_id: logo.asset.asset_id } : {}),
      });
      setJob(created);
    } catch (reason) {
      setError(marketingErrorMessage(reason));
    } finally {
      setSubmitting(false);
    }
  };

  const cancel = async () => {
    if (!job || !running) return;
    try {
      setJob(await pilotApi.cancelMediaLabVideoAd(job.job_id));
    } catch (reason) {
      setError(marketingErrorMessage(reason));
    }
  };

  return (
    <section className="panel media-lab-panel media-lab-video-panel">
      <div className="media-lab-section-heading">
        <div>
          <p className="eyebrow">AUTONOMOUS FINAL VIDEO AD</p>
          <h2>{t("Create a complete 20–25 second Ad")}</h2>
        </div>
        <span className={`media-lab-availability ${loading ? "is-checking" : available ? "is-ready" : "is-unavailable"}`}>
          {loading ? t("Checking availability") : available ? t("Ready") : t("Unavailable")}
        </span>
      </div>
      <p className="media-lab-guidance">
        {t("We plan the scenes, create each clip, and assemble the final Ad automatically. You only need to review the completed video.")}
      </p>

      {error && (
        <div role="alert" className="model-lab-error media-lab-friendly-error">
          <strong>{t("Something needs attention")}</strong>
          <p>{t(error)}</p>
        </div>
      )}
      {!loading && !available && (
        <div className="empty-note">
          <p>{t("Final Ad creation is temporarily unavailable.")}</p>
        </div>
      )}

      <form className="media-lab-form media-lab-final-ad-form" onSubmit={submit}>
        <label className="media-lab-prompt">
          <span>{t("Final Ad brief")}</span>
          <AutoResizeTextarea
            disabled={interactionDisabled}
            onChange={(event) => setRequest(event.target.value)}
            placeholder={t("Describe the product, audience, message, visual direction, and desired final Ad.")}
            value={request}
          />
        </label>
        <div className="media-lab-options">
          <label>
            <span>{t("Brand")}</span>
            <input disabled={interactionDisabled} onChange={(event) => setBrand(event.target.value)} value={brand} />
          </label>
          <label>
            <span>{t("SKU")}</span>
            <input disabled={interactionDisabled} onChange={(event) => setSku(event.target.value)} value={sku} />
          </label>
          <label>
            <span>{t("Marketing angle")}</span>
            <input disabled={interactionDisabled} onChange={(event) => setAngle(event.target.value)} value={angle} />
          </label>
          <label>
            <span>{t("Exact CTA (optional)")}</span>
            <input disabled={interactionDisabled} onChange={(event) => setCta(event.target.value)} value={cta} />
          </label>
          <label>
            <span>{t("Duration")}</span>
            <select disabled={interactionDisabled} onChange={(event) => setDuration(Number(event.target.value))} value={duration}>
              {[20, 21, 22, 23, 24, 25].map((value) => <option key={value} value={value}>{value}s</option>)}
            </select>
          </label>
          <label>
            <span>{t("Aspect ratio")}</span>
            <select
              disabled={interactionDisabled}
              onChange={(event) => setAspectRatio(event.target.value as "1:1" | "9:16" | "16:9")}
              value={aspectRatio}
            >
              <option value="9:16">9:16</option>
              <option value="1:1">1:1</option>
              <option value="16:9">16:9</option>
            </select>
          </label>
        </div>

        <fieldset className="media-lab-file-picker">
          <legend>{t("Product and reference images (optional, maximum 8)")}</legend>
          <label className="media-lab-upload-zone">
            <strong>{t("Choose image sources")}</strong>
            <input
              accept={imageAccept}
              disabled={interactionDisabled || uploading || sources.length >= 8}
              multiple
              onChange={(event) => {
                void uploadSources(event.target.files);
                event.target.value = "";
              }}
              type="file"
            />
          </label>
          {sources.length > 0 && (
            <ul className="media-lab-source-list">
              {sources.map((source) => (
                <li key={source.id}>
                  <span>{source.name} · {source.error ?? `${source.progress}%`}</span>
                  <button
                    className="secondary-button"
                    disabled={interactionDisabled || uploading}
                    onClick={() => setSources((current) => current.filter((item) => item.id !== source.id))}
                    type="button"
                  >
                    {t("Remove")}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </fieldset>

        <fieldset className="media-lab-file-picker">
          <legend>{t("Logo overlay (optional PNG or JPEG)")}</legend>
          <input
            accept="image/png,image/jpeg"
            disabled={interactionDisabled || uploading}
            onChange={(event) => {
              void uploadLogo(event.target.files?.[0]);
              event.target.value = "";
            }}
            type="file"
          />
          {logo && <p>{logo.name} · {logo.error ?? `${logo.progress}%`}</p>}
        </fieldset>

        <div className="media-lab-review-actions">
          <button className="primary-button" disabled={submitting || interactionDisabled || uploading} type="submit">
            {submitting ? t("Starting…") : t("Create final Ad")}
          </button>
          {running && (
            <button className="secondary-button" onClick={() => void cancel()} type="button">
              {t("Cancel")}
            </button>
          )}
        </div>
      </form>

      {job && <FinalVideoAdResult job={job} />}
    </section>
  );
}

function FinalVideoAdResult({ job }: { job: MediaLabVideoAd }) {
  const { t } = useI18n();
  const currentStep = job.state === "planning"
    ? 0
    : job.state === "generating_shots"
      ? 1
      : job.state === "selecting_segments"
        ? 2
        : job.state === "assembling"
          ? 3
          : 4;

  return (
    <section className="media-lab-result" aria-live="polite">
      <MediaLabJobProgress
        completedAt={job.completed_at}
        currentStep={currentStep}
        startedAt={job.created_at}
        status={t(job.state.replaceAll("_", " "))}
        steps={[
          t("Plan timeline"),
          t("Generate source shots"),
          t("Select usable segments"),
          t("Assemble final Ad"),
          t("Completed"),
        ]}
      />

      {job.summary && <p>{job.summary}</p>}
      {job.state === "needs_input" && (
        <div className="empty-note">
          <strong>{t("More information is required")}</strong>
          <ul>{job.questions.map((question) => <li key={question}>{question}</li>)}</ul>
        </div>
      )}
      {job.state === "failed" && (
        <p role="alert" className="model-lab-error">
          {t("We couldn't complete this Ad. Your brief and uploaded images are still saved on this page. Please try again.")}
        </p>
      )}
      {job.shots.length > 0 && (
        <details className="media-lab-scene-progress">
          <summary>{t("View scene progress")}</summary>
          <ol>
            {job.shots.map((shot) => (
              <li key={shot.shot_id}>
                <strong>{shot.purpose}</strong> · {shot.usable_duration_seconds.toFixed(1)}s
              </li>
            ))}
          </ol>
        </details>
      )}
      {job.state === "completed" && job.output_url && (
        <div className="media-lab-output">
          <video controls src={job.output_url}>{t("Your browser cannot play this video.")}</video>
          <p className="media-lab-option-note">
            {job.actual_width}×{job.actual_height} · {job.actual_duration_milliseconds
              ? `${(job.actual_duration_milliseconds / 1_000).toFixed(2)}s`
              : t("Duration unavailable")}
          </p>
          <a className="primary-button" download href={job.output_url}>{t("Download final MP4")}</a>
        </div>
      )}
    </section>
  );
}
