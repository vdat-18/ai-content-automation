import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Clapperboard, Copy, Download, FileText, Film, ImageIcon, Loader2, Play, RotateCcw, Search, Sparkles, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { SplitHandle } from "../components/SplitHandle";
import { EmptyState, PageHeader, Panel, SkeletonPage } from "../components/ui";
import { useI18n } from "../hooks/useI18n";
import { useLightbox } from "../hooks/useLightbox";
import { useSplitResize } from "../hooks/useSplitResize";
import { getJson, postJson, putFile, putJson } from "../services/http";

type Persona = { description: string; image_path: string | null; status: "none" | "ready" | "approved" | "rejected"; attempts: number };
type PostPackage = { captions: string[]; hashtags: string[]; product_url: string; warnings?: string[]; ai_label_reminder?: string };
type Shot = {
  role: string;
  description: string;
  keyframe_prompt: string;
  motion_prompt: string;
  delivery?: "narrated" | "talking";
  duration_seconds: number;
  on_screen_text: string;
  voiceover: string;
};
type Brief = {
  title: string;
  script?: string;
  format?: string;
  warnings?: string[];
  quality_problems?: string[];
  reference_rationale: string;
  scene: string;
  product_placement: string;
  product_variant?: string;
  product_size?: string;
  selling_angle: string;
  target_audience: string;
  style: string[];
  colors: string[];
  shots?: Shot[];
  selected_reference_ids: string[];
  shot_references?: (string | null)[];
  product_photo_urls?: string[];
  post_package?: PostPackage;
  persona?: Persona;
};
type BriefRecord = { product_id: string; user_idea: string; brief: Brief; status: "draft" | "approved" };
type Keyframe = { shot_index: number; status: "ready" | "approved" | "rejected" | "failed"; attempts: number; error: string | null; qa_problem: string };
type Clip = { shot_index: number; status: "processing" | "ready" | "failed"; seconds: number; attempts: number; error: string | null };
type Product = { product_id: string; title: string | null; images: string[] };
type ReferenceImage = { image_id: string; image_url: string };
type Step = "brief" | "person" | "images" | "clips" | "voice" | "post";

const API = "/api/v1/products";
const CLIP_POLL_MS = 5000;
const CLIP_WAIT_MS = 20 * 60 * 1000;

// Clip jobs run for minutes; each GET also collects the jobs that have finished.
async function waitForClips(productId: string, shotCount: number): Promise<void> {
  const deadline = Date.now() + CLIP_WAIT_MS;
  for (;;) {
    const clips = await getJson<Clip[]>(`${API}/${productId}/clips`);
    const failed = clips.filter((clip) => clip.status === "failed");
    if (failed.length > 0) {
      const shots = failed.map((clip) => clip.shot_index + 1).join(", ");
      throw new Error(`The clip of shot ${shots} failed: ${failed[0].error ?? "video job failed"}. Retry it in the Clips step`);
    }
    if (clips.filter((clip) => clip.status === "ready").length >= shotCount) return;
    if (Date.now() > deadline) throw new Error("The clips are still being made; check the Clips step later");
    await new Promise<void>((resolve) => window.setTimeout(resolve, CLIP_POLL_MS));
  }
}
const STEPS: { id: Step; label: string }[] = [
  { id: "brief", label: "Brief" },
  { id: "person", label: "Person" },
  { id: "images", label: "Images" },
  { id: "clips", label: "Clips" },
  { id: "voice", label: "Voice and video" },
  { id: "post", label: "Post" },
];
const TEXT_FIELDS: { key: "scene" | "product_placement" | "product_variant" | "product_size" | "selling_angle" | "target_audience"; label: string; rows: number }[] = [
  { key: "scene", label: "Scene", rows: 3 },
  { key: "product_placement", label: "Product placement", rows: 3 },
  { key: "product_variant", label: "Product version shown (one color/size in the whole video)", rows: 2 },
  { key: "product_size", label: "Real product size (keeps the scale in the images)", rows: 2 },
  { key: "selling_angle", label: "Selling angle", rows: 2 },
  { key: "target_audience", label: "Target audience", rows: 2 },
];
const SHOT_FIELDS: { key: "description" | "voiceover" | "on_screen_text" | "keyframe_prompt" | "motion_prompt" }[] = [
  { key: "description" },
  { key: "voiceover" },
  { key: "on_screen_text" },
  { key: "keyframe_prompt" },
  { key: "motion_prompt" },
];
const FORMATS = ["problem_solution", "step_by_step", "before_after", "unboxing", "worth_it_text"];
const words = (text: string) => text.split(",").map((word) => word.trim()).filter(Boolean);
const wordCount = (text: string) => text.split(/\s+/).filter(Boolean).length;

function useKeyframes(productId: string, enabled: boolean) {
  return useQuery({
    queryKey: ["keyframes", productId],
    queryFn: ({ signal }) => getJson<Keyframe[]>(`${API}/${productId}/keyframes`, signal),
    enabled,
  });
}

function useClips(productId: string, enabled: boolean) {
  return useQuery({
    queryKey: ["clips", productId],
    queryFn: ({ signal }) => getJson<Clip[]>(`${API}/${productId}/clips`, signal),
    refetchInterval: (query) => (query.state.data?.some((clip) => clip.status === "processing") ? 5000 : false),
    enabled,
  });
}

function useVideoInfo(productId: string, enabled: boolean) {
  return useQuery({
    queryKey: ["video-info", productId],
    queryFn: ({ signal }) => getJson<{ exists: boolean; voiceover: boolean }>(`${API}/${productId}/video-info`, signal),
    enabled,
  });
}

export function BriefsPage() {
  const { t } = useI18n();
  const [params, setParams] = useSearchParams();
  const targetProduct = params.get("product");
  const [search, setSearch] = useState("");
  const detailPanelRef = useRef<HTMLElement>(null);
  const split = useSplitResize("aic-studio-split", 520, 1100, detailPanelRef);

  const selections = useQuery({ queryKey: ["product-selections"], queryFn: ({ signal }) => getJson<Record<string, string | null>>(`${API}/selections`, signal) });
  const products = useQuery({ queryKey: ["products"], queryFn: ({ signal }) => getJson<Product[]>(API, signal) });
  const briefs = useQuery({ queryKey: ["briefs"], queryFn: ({ signal }) => getJson<BriefRecord[]>(`${API}/briefs`, signal) });
  const references = useQuery({
    queryKey: ["reference-images", "live"],
    queryFn: ({ signal }) => getJson<ReferenceImage[]>(`${API}/reference-images?status=live`, signal),
  });

  if (selections.isLoading || products.isLoading || briefs.isLoading) return <SkeletonPage />;
  const selectedIds = Object.keys(selections.data ?? {});
  const productById = new Map((products.data ?? []).map((product) => [product.product_id, product]));
  const briefById = new Map((briefs.data ?? []).map((record) => [record.product_id, record]));
  const imageById = new Map((references.data ?? []).map((image) => [image.image_id, image.image_url]));

  const activeProductId = targetProduct && selectedIds.includes(targetProduct)
    ? targetProduct
    : selectedIds[0] ?? null;

  const selectProduct = (id: string) => {
    setParams({ product: id });
  };

  const filteredSelectedIds = selectedIds.filter((id) => {
    if (!search.trim()) return true;
    const prod = productById.get(id);
    const title = prod?.title ?? id;
    return title.toLowerCase().includes(search.trim().toLowerCase());
  });

  return (
    <>
      <PageHeader eyebrow="Affiliate content" title="Video Studio" variant="operator" />
      {selectedIds.length === 0 ? (
        <EmptyState icon={<FileText />} title="No products selected" text="Select products for content on the Products page first." />
      ) : (
        <div className={`studio-layout${split.active ? " split-active" : ""}`} style={split.style}>
          {/* Left panel: Product selection list */}
          <aside className="studio-sidebar">
            <div className="studio-sidebar__head">
              <span className="studio-sidebar__count">{`${selectedIds.length} ${t("products in studio")}`}</span>
              <label className="studio-sidebar__search">
                <Search size={14} aria-hidden="true" />
                <input
                  type="search"
                  placeholder={t("Filter products…")}
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                />
              </label>
            </div>
            <div className="studio-product-list">
              {filteredSelectedIds.map((productId) => {
                const prod = productById.get(productId);
                const rec = briefById.get(productId);
                const pType = selections.data?.[productId];
                const isSelected = activeProductId === productId;
                return (
                  <button
                    key={productId}
                    type="button"
                    className={`studio-product-item${isSelected ? " studio-product-item--active" : ""}`}
                    onClick={() => selectProduct(productId)}
                  >
                    <div className="studio-product-item__thumb">
                      {prod?.images[0] ? (
                        <img src={prod.images[0]} alt="" referrerPolicy="no-referrer" />
                      ) : (
                        <Film size={20} />
                      )}
                    </div>
                    <div className="studio-product-item__info">
                      <strong title={prod?.title ?? productId}>{prod?.title ?? productId}</strong>
                      <div className="studio-product-item__meta">
                        <small>{pType ?? t("Keywords pending")}</small>
                        {rec && (
                          <span className={`badge badge--${rec.status === "approved" ? "success" : "warning"}`}>
                            {rec.status}
                          </span>
                        )}
                      </div>
                    </div>
                  </button>
                );
              })}
            </div>
          </aside>

          {/* Right panel: Studio workspace */}
          {activeProductId && (
            <main ref={detailPanelRef} className="studio-main">
              <SplitHandle label="Resize studio layout" {...split.handleProps} />
              <BriefCard
                key={activeProductId}
                productId={activeProductId}
                productType={selections.data?.[activeProductId] ?? null}
                product={productById.get(activeProductId)}
                record={briefById.get(activeProductId)}
                imageById={imageById}
                isTarget={true}
                t={t}
              />
            </main>
          )}
        </div>
      )}
    </>
  );
}

function BriefCard({
  productId,
  productType,
  product,
  record,
  imageById,
  isTarget,
  t,
}: {
  productId: string;
  productType: string | null;
  product: Product | undefined;
  record: BriefRecord | undefined;
  imageById: Map<string, string>;
  isTarget?: boolean;
  t: (key: string) => string;
}) {
  const cardRef = useRef<HTMLDivElement>(null);
  const client = useQueryClient();
  const [idea, setIdea] = useState(record?.user_idea ?? "");
  const [videoSeconds, setVideoSeconds] = useState(60);
  const [picked, setPicked] = useState<Step | null>(null);
  const [autoRunning, setAutoRunning] = useState(false);
  const [autoStatus, setAutoStatus] = useState<string | null>(null);
  const events = useQuery({
    queryKey: ["run-log", productId],
    queryFn: ({ signal }) => getJson<RunEvent[]>(`${API}/${productId}/events`, signal),
    refetchInterval: autoRunning ? 2000 : 5000,
  });
  const latestEvent = events.data?.[events.data.length - 1];

  const runAutoPipeline = async () => {
    if (autoRunning) return;
    setAutoRunning(true);
    setAutoStatus(t("Starting automated creation…"));
    try {
      let currentRecord = record;
      // 1. Create or get brief
      if (!currentRecord) {
        setAutoStatus(t("Writing storyboard brief…"));
        currentRecord = await postJson<BriefRecord>(`${API}/${productId}/brief`, { idea, video_seconds: videoSeconds });
        await refresh();
      }

      // 2. Approve brief if draft
      if (currentRecord.status !== "approved") {
        setAutoStatus(t("Approving brief…"));
        currentRecord = await putJson<BriefRecord>(`${API}/${productId}/brief`, { brief: currentRecord.brief, status: "approved" });
        await refresh();
      }

      // 3. Approve persona if persona exists
      if (currentRecord.brief.persona?.description && currentRecord.brief.persona.status !== "approved") {
        setAutoStatus(t("Approving persona…"));
        if (!currentRecord.brief.persona.image_path) {
          await postJson<Persona>(`${API}/${productId}/persona`, { description: currentRecord.brief.persona.description });
        }
        await putJson(`${API}/${productId}/persona`, { status: "approved" });
        await refresh();
      }

      const shotCount = currentRecord.brief.shots?.length ?? 0;
      const keyframes = await getJson<Keyframe[]>(`${API}/${productId}/keyframes`);

      // 4. Generate the master keyframe (shot 0) unless it is already approved
      if (keyframes.find((keyframe) => keyframe.shot_index === 0)?.status !== "approved") {
        setAutoStatus(t("Generating master keyframe…"));
        const made = await postJson<Keyframe[]>(`${API}/${productId}/keyframes`, { shot_index: 0 });
        const master = made.find((keyframe) => keyframe.shot_index === 0);
        if (master?.status !== "ready") {
          throw new Error(`Master keyframe failed: ${master?.error ?? "no image"}. Retry it in the Images step`);
        }
        if (master.qa_problem) {
          throw new Error(`Master keyframe needs a look (${master.qa_problem}). Review it in the Images step, then run again`);
        }
        await putJson(`${API}/${productId}/keyframes/0`, { status: "approved" });
      }

      // 5. Generate the other keyframes and approve only the clean ones
      setAutoStatus(t("Generating remaining scene keyframes…"));
      const rest = await postJson<Keyframe[]>(`${API}/${productId}/keyframes`, { shot_index: null });
      const toReview: number[] = [];
      for (let i = 1; i < shotCount; i++) {
        const keyframe = rest.find((item) => item.shot_index === i);
        if (keyframe?.status === "approved") continue;
        if (keyframe?.status === "ready" && !keyframe.qa_problem) {
          await putJson(`${API}/${productId}/keyframes/${i}`, { status: "approved" });
        } else {
          toReview.push(i + 1);
        }
      }
      await client.invalidateQueries({ queryKey: ["keyframes", productId] });
      if (toReview.length > 0) {
        throw new Error(`Review the images of shot ${toReview.join(", ")} (failed or flagged by the image check), then run again`);
      }

      // 6. Start the clips that are not made yet, then wait until every clip is ready
      setAutoStatus(t("Creating video clips (this takes a few minutes)…"));
      const started = await getJson<Clip[]>(`${API}/${productId}/clips`);
      if (started.filter((clip) => clip.status === "ready" || clip.status === "processing").length < shotCount) {
        await postJson<Clip[]>(`${API}/${productId}/clips`, { shot_index: null });
      }
      await waitForClips(productId, shotCount);
      await client.invalidateQueries({ queryKey: ["clips", productId] });

      // 7. Generate voiceover
      setAutoStatus(t("Synthesizing voiceover…"));
      const savedVoice = window.localStorage.getItem("aic-voice") || null;
      await postJson<{ seconds: number[]; too_long_shots: number[] }>(`${API}/${productId}/voiceover`, { voice: savedVoice });

      // 8. Stitch video
      setAutoStatus(t("Stitching final video with transitions and music…"));
      await postJson<{ video: string }>(`${API}/${productId}/video`, { captions: false });
      await client.invalidateQueries({ queryKey: ["video-info", productId] });

      // 9. Post package
      setAutoStatus(t("Writing TikTok caption and hashtags…"));
      await postJson<PostPackage>(`${API}/${productId}/post-package`);
      await refresh();

      setPicked("voice");
      setAutoStatus(t("Video completed successfully!"));
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      setAutoStatus(`${t("Automation paused")}: ${message}`);
    } finally {
      setAutoRunning(false);
    }
  };

  useEffect(() => {
    if (isTarget && cardRef.current) {
      cardRef.current.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }, [isTarget]);
  const approved = record?.status === "approved";
  const shots = record?.brief.shots ?? [];
  const keyframes = useKeyframes(productId, !!record);
  const clips = useClips(productId, approved);
  const videoInfo = useVideoInfo(productId, approved);
  const refresh = () => client.invalidateQueries({ queryKey: ["briefs"] });
  const create = useMutation({
    mutationFn: () => postJson<BriefRecord>(`${API}/${productId}/brief`, { idea, video_seconds: videoSeconds }),
    onSuccess: refresh,
  });
  const save = useMutation({
    mutationFn: ({ brief, status }: { brief: Partial<Brief>; status: "draft" | "approved" }) =>
      putJson<BriefRecord>(`${API}/${productId}/brief`, { brief, status }),
    onSuccess: refresh,
  });

  const keyframeByShot = new Map((keyframes.data ?? []).map((keyframe) => [keyframe.shot_index, keyframe]));
  const persona = record?.brief.persona;
  const done: Record<Step, boolean> = {
    brief: approved,
    person: approved && (!persona?.description || persona.status === "approved"),
    images: shots.length > 0 && shots.every((_, index) => keyframeByShot.get(index)?.status === "approved"),
    clips: shots.length > 0 && (clips.data ?? []).filter((clip) => clip.status === "ready").length >= shots.length,
    voice: !!videoInfo.data?.exists,
    post: !!record?.brief.post_package,
  };
  const suggested = STEPS.find((item) => !done[item.id])?.id ?? "post";
  const step: Step = !record ? "brief" : approved ? (picked ?? suggested) : "brief";
  const completedStepsCount = STEPS.filter((item) => done[item.id]).length;
  const progressPercent = Math.round((completedStepsCount / STEPS.length) * 100);

  return (
    <Panel className={`brief-card${isTarget ? " brief-card--highlight" : ""}`}>
      <div ref={cardRef} className="brief-head">
        {product?.images[0] && <img src={product.images[0]} alt="" width={48} height={48} referrerPolicy="no-referrer" />}
        <div>
          <strong title={product?.title ?? productId}>{product?.title ?? productId}</strong>
          <small>{productType ?? t("No product type yet. Regenerate keywords on the Products page.")}</small>
        </div>
        {record && (
          <div className="brief-head__status">
            <span className="brief-progress-label">{`${completedStepsCount}/${STEPS.length} ${t("steps")}`}</span>
            <span className={`badge badge--${approved ? "success" : "warning"}`}>{record.status}</span>
            <button
              type="button"
              className="primary-button brief-head__btn-auto"
              disabled={autoRunning || !productType}
              onClick={runAutoPipeline}
              title={t("Automatically generate and stitch the entire video in 1 click")}
            >
              {autoRunning ? <Loader2 size={13} className="pt-spin" /> : <Play size={13} />}
              {autoRunning ? t("Processing…") : t("1-Click Auto Pipeline")}
            </button>
          </div>
        )}
      </div>
      {autoStatus ? (
        <div className={`brief-auto-status${autoRunning ? " brief-auto-status--running" : ""}`}>
          {autoRunning && <Loader2 size={14} className="pt-spin" />}
          <span>{autoStatus}</span>
        </div>
      ) : latestEvent && !done.post ? (
        <div className="brief-auto-status brief-auto-status--live">
          <span className="live-indicator" />
          <span><strong>{t("Live progress")}:</strong> {latestEvent.message}</span>
        </div>
      ) : null}
      {record && (
        <div className="brief-progress-bar-wrap" title={`${progressPercent}% completed`}>
          <div className="brief-progress-bar" style={{ width: `${progressPercent}%` }} />
        </div>
      )}
      {record && (
        <nav className="brief-steps" aria-label={t("Steps")}>
          {STEPS.map((item, index) => (
            <button
              key={item.id}
              type="button"
              disabled={!approved && item.id !== "brief"}
              className={`brief-step${step === item.id ? " brief-step--on" : ""}${done[item.id] ? " brief-step--done" : ""}`}
              onClick={() => setPicked(item.id)}
            >
              <span>{done[item.id] ? <Check size={12} /> : index + 1}</span>
              {t(item.label)}
            </button>
          ))}
        </nav>
      )}
      {step === "brief" && (
        <>
          <div className="brief-create">
            <label className="brief-field">
              <span>{t("Your idea (optional)")}</span>
              <textarea rows={2} value={idea} onChange={(event) => setIdea(event.target.value)} placeholder={t("e.g. sunny balcony, tidy feeling for small apartments")} />
            </label>
            <label className="brief-field">
              <span>{t("Video length")}</span>
              <select value={videoSeconds} onChange={(event) => setVideoSeconds(Number(event.target.value))}>
                {[15, 30, 45, 60, 75, 90].map((seconds) => (
                  <option key={seconds} value={seconds}>{`${seconds}s`}</option>
                ))}
              </select>
            </label>
            <button className="primary-button" disabled={create.isPending || !productType} onClick={() => create.mutate()}>
              <Sparkles size={15} /> {create.isPending ? t("Writing…") : record ? t("Regenerate brief") : t("Create brief")}
            </button>
            {!record && (
              <button
                type="button"
                className="primary-button brief-btn-auto-large"
                disabled={autoRunning || !productType}
                onClick={runAutoPipeline}
              >
                {autoRunning ? <Loader2 size={15} className="pt-spin" /> : <Play size={15} />}
                {autoRunning ? t("Processing…") : t("1-Click Auto Pipeline")}
              </button>
            )}
          </div>
          {create.error && <p role="alert">{create.error.message}</p>}
          {record && (
            <BriefForm
              record={record}
              imageById={imageById}
              keyframeByShot={keyframeByShot}
              save={(brief, status) => save.mutate({ brief, status })}
              saving={save.isPending}
              error={save.error?.message}
              t={t}
            />
          )}
        </>
      )}
      {record && approved && step !== "brief" && (
        <Pipeline
          key={`${productId}-${record.brief.title}`}
          productId={productId}
          step={step}
          shots={shots}
          postPackage={record.brief.post_package}
          persona={persona}
          keyframes={keyframes.data ?? []}
          clips={clips.data ?? []}
          hasVideoFile={!!videoInfo.data?.exists}
          hasVoiceFile={!!videoInfo.data?.voiceover}
          t={t}
        />
      )}
      {record && <RunLog productId={productId} t={t} />}
    </Panel>
  );
}

function BriefForm({
  record,
  imageById,
  keyframeByShot,
  save,
  saving,
  error,
  t,
}: {
  record: BriefRecord;
  imageById: Map<string, string>;
  keyframeByShot: Map<number, Keyframe>;
  save: (brief: Partial<Brief>, status: "draft" | "approved") => void;
  saving: boolean;
  error: string | undefined;
  t: (key: string) => string;
}) {
  const lightbox = useLightbox();
  const { brief } = record;
  const shots = brief.shots ?? [];
  const photos = (brief.product_photo_urls ?? []).map((src) => ({ src }));
  const scenes = brief.selected_reference_ids.flatMap((id) => (imageById.get(id) ? [{ src: imageById.get(id) as string }] : []));
  const problems = brief.quality_problems ?? [];
  const warnings = brief.warnings ?? [];
  return (
    <>
      <form
        key={`${record.product_id}-${record.status}-${brief.title}`}
        className="brief-form"
        onSubmit={(event) => {
          event.preventDefault();
          const submitter = (event.nativeEvent as SubmitEvent).submitter as HTMLButtonElement | null;
          const data = new FormData(event.currentTarget);
          const next: Partial<Brief> = {
            title: String(data.get("title")),
            format: String(data.get("format")),
            style: words(String(data.get("style"))),
            colors: words(String(data.get("colors"))),
          };
          for (const field of TEXT_FIELDS) Object.assign(next, { [field.key]: String(data.get(field.key)) });
          const edited = shots.map((shot, index) => {
            const changed: Shot = { ...shot, duration_seconds: Number(data.get(`shot_${index}_duration`)) || shot.duration_seconds };
            for (const field of SHOT_FIELDS) changed[field.key] = String(data.get(`shot_${index}_${field.key}`));
            changed.delivery = data.get(`shot_${index}_delivery`) === "talking" ? "talking" : "narrated";
            return changed;
          });
          next.shots = edited;
          next.script = edited.map((shot) => shot.voiceover.trim()).filter(Boolean).join(" ");
          save(next, submitter?.value === "approved" ? "approved" : "draft");
        }}
      >
        <div className="brief-title">
          <input name="title" defaultValue={brief.title} aria-label={t("Title")} />
        </div>
        {problems.length ? (
          <details className="brief-status brief-status--problem" open>
            <summary>{`${problems.length} ${t("storyboard issues found. Fix them before making images")}`}</summary>
            <ul>{problems.map((problem) => <li key={problem}>{problem}</li>)}</ul>
          </details>
        ) : (
          <p className="brief-status brief-status--ok">{t("The storyboard passed the review.")}</p>
        )}
        {!!warnings.length && (
          <details className="brief-status">
            <summary>{`${warnings.length} ${t("words TikTok may flag. Rewrite them before posting")}`}</summary>
            <ul>{warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul>
          </details>
        )}
        <details className="brief-more">
          <summary>
            <strong>{t("Product and scene")}</strong>
            <span>{[brief.product_variant, brief.selling_angle].filter(Boolean).join(" · ")}</span>
          </summary>
          <div className="brief-thumbs">
            {photos.map((photo, index) => <img key={photo.src} src={photo.src} alt="" width={44} height={44} referrerPolicy="no-referrer" {...lightbox.zoom(photos, index)} />)}
            {scenes.map((scene, index) => <img key={scene.src} src={scene.src} alt="" width={44} height={58} referrerPolicy="no-referrer" {...lightbox.zoom(scenes, index)} />)}
          </div>
          {brief.reference_rationale && <p className="brief-note">{brief.reference_rationale}</p>}
          <div className="brief-grid">
            {TEXT_FIELDS.map((field) => (
              <label className="brief-field" key={field.key}>
                <span>{t(field.label)}</span>
                <textarea name={field.key} rows={field.rows} defaultValue={String(brief[field.key] ?? "")} />
              </label>
            ))}
            <label className="brief-field">
              <span>{t("Video format")}</span>
              <select name="format" defaultValue={brief.format ?? FORMATS[0]}>
                {FORMATS.map((format) => <option key={format} value={format}>{format.replaceAll("_", " ")}</option>)}
              </select>
            </label>
            <label className="brief-field">
              <span>{t("Style (comma separated)")}</span>
              <input name="style" defaultValue={brief.style.join(", ")} />
            </label>
            <label className="brief-field">
              <span>{t("Colors (comma separated)")}</span>
              <input name="colors" defaultValue={brief.colors.join(", ")} />
            </label>
          </div>
        </details>
        <div className="shot-list">
          {shots.map((shot, index) => {
            const keyframe = keyframeByShot.get(index);
            const src = keyframe && keyframe.status !== "failed" ? `${API}/${record.product_id}/keyframes/${index}/image?v=${keyframe.attempts}` : null;
            const referenceId = brief.shot_references?.[index];
            const referenceSrc = referenceId ? imageById.get(referenceId) : undefined;
            return (
              <section className="shot-row" key={`${index}-${shot.keyframe_prompt}`}>
                <div className="shot-row__side">
                  <div className="shot-row__image">
                    {src ? <img src={src} alt="" loading="lazy" {...lightbox.zoom([{ src }], 0)} /> : <span>{t("No image yet")}</span>}
                  </div>
                  {referenceSrc ? (
                    <div className="shot-row__reference"><img src={referenceSrc} alt="" loading="lazy" referrerPolicy="no-referrer" title={t("Reference photo for this shot")} {...lightbox.zoom([{ src: referenceSrc }], 0)} /></div>
                  ) : (
                    <small className="brief-note">{t("No reference")}</small>
                  )}
                </div>
                <div className="shot-row__body">
                  <div className="shot-row__head">
                    <strong>{`${index + 1}. ${shot.role.replaceAll("_", " ")}`}</strong>
                    <span className="chip">{shot.delivery === "talking" ? t("Talking") : t("Narrated")}</span>
                    <span className="chip">{`${wordCount(shot.voiceover)} ${t("words")}`}</span>
                  </div>
                  <label className="brief-field">
                    <span>{t("Voice-over")}</span>
                    <textarea name={`shot_${index}_voiceover`} rows={3} defaultValue={shot.voiceover} />
                  </label>
                  <label className="brief-field">
                    <span>{t("Text on screen")}</span>
                    <input name={`shot_${index}_on_screen_text`} defaultValue={shot.on_screen_text} />
                  </label>
                  <details className="brief-more brief-more--small">
                    <summary>{t("More about this shot")}</summary>
                    <label className="brief-field">
                      <span>{t("What the viewer sees")}</span>
                      <textarea name={`shot_${index}_description`} rows={2} defaultValue={shot.description} />
                    </label>
                    <div className="brief-row">
                      <label className="brief-field">
                        <span>{t("Delivery")}</span>
                        <select name={`shot_${index}_delivery`} defaultValue={shot.delivery ?? "narrated"}>
                          <option value="narrated">{t("Narrated (voice-over, mouth not shown speaking)")}</option>
                          <option value="talking">{t("Talking (person speaks to the camera, voice follows the mouth)")}</option>
                        </select>
                      </label>
                      <label className="brief-field">
                        <span>{t("Seconds")}</span>
                        <input name={`shot_${index}_duration`} type="number" min={1} max={15} defaultValue={shot.duration_seconds} />
                      </label>
                    </div>
                    <label className="brief-field">
                      <span>{t("Keyframe image prompt")}</span>
                      <textarea name={`shot_${index}_keyframe_prompt`} rows={4} defaultValue={shot.keyframe_prompt} />
                    </label>
                    <label className="brief-field">
                      <span>{t("Motion prompt")}</span>
                      <textarea name={`shot_${index}_motion_prompt`} rows={4} defaultValue={shot.motion_prompt} />
                    </label>
                  </details>
                </div>
              </section>
            );
          })}
          {!shots.length && <p>{t("This brief has no storyboard yet. Regenerate it.")}</p>}
        </div>
        <div className="brief-bar">
          <span>{record.status === "approved" ? t("Approved. Pick the next step above.") : t("Approve the brief to make the person and the images.")}</span>
          <div className="brief-actions">
            <button className="secondary-button" type="submit" value="draft" disabled={saving}>{t("Save draft")}</button>
            <button className="primary-button" type="submit" value="approved" disabled={saving}>{t("Approve brief")}</button>
          </div>
        </div>
        {error && <p role="alert">{error}</p>}
      </form>
      {lightbox.node}
    </>
  );
}

function Pipeline({
  productId,
  step,
  shots,
  postPackage,
  persona,
  keyframes,
  clips,
  hasVideoFile,
  hasVoiceFile,
  t,
}: {
  productId: string;
  step: Step;
  shots: Shot[];
  postPackage?: PostPackage;
  persona?: Persona;
  keyframes: Keyframe[];
  clips: Clip[];
  hasVideoFile: boolean;
  hasVoiceFile: boolean;
  t: (key: string) => string;
}) {
  const client = useQueryClient();
  const lightbox = useLightbox();
  const refresh = () => client.invalidateQueries({ queryKey: ["keyframes", productId] });
  const generate = useMutation({
    mutationFn: (shotIndex: number | null) => postJson<Keyframe[]>(`${API}/${productId}/keyframes`, { shot_index: shotIndex }),
    onSuccess: refresh,
  });
  const review = useMutation({
    mutationFn: ({ shotIndex, status }: { shotIndex: number; status: Keyframe["status"] }) =>
      putJson(`${API}/${productId}/keyframes/${shotIndex}`, { status }),
    onSuccess: refresh,
  });
  const refreshClips = () => client.invalidateQueries({ queryKey: ["clips", productId] });
  const makeClips = useMutation({
    mutationFn: (shotIndex: number | null) => postJson<Clip[]>(`${API}/${productId}/clips`, { shot_index: shotIndex }),
    onSuccess: refreshClips,
  });
  const [videoVersion, setVideoVersion] = useState(0);
  const hasVideo = videoVersion > 0 || hasVideoFile;
  const voices = useQuery({
    queryKey: ["voices"],
    queryFn: ({ signal }) => getJson<{ id: string; label: string }[]>(`${API}/voices`, signal),
    staleTime: Infinity,
  });
  const [pickedVoice, setPickedVoice] = useState(() => {
    try {
      return window.localStorage.getItem("aic-voice") ?? "";
    } catch {
      return "";
    }
  });
  const voice = pickedVoice || (voices.data ?? []).find((option) => option.id !== "auto")?.id || "";
  const setVoice = (next: string) => {
    setPickedVoice(next);
    try {
      window.localStorage.setItem("aic-voice", next);
    } catch {
      /* the choice just is not remembered */
    }
  };
  const makeVoice = useMutation({
    mutationFn: () => postJson<{ seconds: number[]; too_long_shots: number[] }>(`${API}/${productId}/voiceover`, { voice: voice || null }),
    onSuccess: () => {
      setVoiceVersion((version) => version + 1);
      client.invalidateQueries({ queryKey: ["video-info", productId] });
    },
  });
  const [voiceVersion, setVoiceVersion] = useState(0);
  const uploadVoice = useMutation({
    mutationFn: (file: File) => putFile<{ voiceover: string }>(`${API}/${productId}/voiceover`, file),
    onSuccess: () => {
      setVoiceVersion((version) => version + 1);
      client.invalidateQueries({ queryKey: ["video-info", productId] });
    },
  });
  const [captions, setCaptions] = useState(false);
  const stitchVideo = useMutation({
    mutationFn: () => postJson<{ video: string }>(`${API}/${productId}/video`, { captions }),
    onSuccess: () => {
      setVideoVersion((version) => version + 1);
      client.invalidateQueries({ queryKey: ["video-info", productId] });
    },
  });
  const byShot = new Map(keyframes.map((keyframe) => [keyframe.shot_index, keyframe]));
  const writePackage = useMutation({
    mutationFn: () => postJson<PostPackage>(`${API}/${productId}/post-package`),
    onSuccess: () => client.invalidateQueries({ queryKey: ["briefs"] }),
  });
  const copy = (text: string) => navigator.clipboard?.writeText(text).catch(() => undefined);
  const [personaText, setPersonaText] = useState(persona?.description ?? "");
  const refreshBriefs = () => client.invalidateQueries({ queryKey: ["briefs"] });
  const makePersona = useMutation({
    mutationFn: () => postJson<Persona>(`${API}/${productId}/persona`, { description: personaText }),
    onSuccess: refreshBriefs,
  });
  const reviewPersona = useMutation({
    mutationFn: (status: Persona["status"]) => putJson(`${API}/${productId}/persona`, { status }),
    onSuccess: refreshBriefs,
  });
  const [rights, setRights] = useState(false);
  const uploadPersona = useMutation({
    mutationFn: (file: File) => putFile<Persona>(`${API}/${productId}/persona/image?rights=confirmed`, file),
    onSuccess: refreshBriefs,
  });
  const personaPending = !!persona?.description && persona.status !== "approved";
  const clipByShot = new Map(clips.map((clip) => [clip.shot_index, clip]));
  const approvedShots = shots.filter((_, index) => byShot.get(index)?.status === "approved").length;
  const readyClips = [...clipByShot.values()].filter((clip) => clip.status === "ready").length;
  const masterApproved = byShot.get(0)?.status === "approved";
  const allApproved = shots.length > 0 && shots.every((_, index) => byShot.get(index)?.status === "approved");
  const next = !byShot.has(0) || !masterApproved ? t("Generate master keyframe") : t("Generate the other shots");
  const frames = shots.flatMap((shot, index) => {
    const keyframe = byShot.get(index);
    return keyframe && keyframe.status !== "failed"
      ? [{ index, src: `${API}/${productId}/keyframes/${index}/image?v=${keyframe.attempts}`, label: `${index + 1}. ${shot.role.replaceAll("_", " ")}` }]
      : [];
  });

  return (
    <section className="keyframes">
      {step === "person" && (
        <div className="persona">
          <h3>{t("Person in the video")}</h3>
          <p className="brief-note">{t("One portrait is reused in every shot: make a synthetic person or upload your own photo.")}</p>
          <div className="brief-actions">
            <label>
              <input type="checkbox" checked={rights} onChange={(event) => setRights(event.target.checked)} /> {t("I have the right to use this person's image in ads")}
            </label>
            <input
              type="file"
              accept="image/jpeg,image/png,image/webp"
              disabled={!rights || uploadPersona.isPending}
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (file) uploadPersona.mutate(file);
                event.target.value = "";
              }}
            />
          </div>
          {uploadPersona.error && <p role="alert">{uploadPersona.error.message}</p>}
          {persona?.description ? (
            <div className="persona-body">
              {persona.image_path && <img src={`${API}/${productId}/persona/image?v=${persona.attempts}`} alt="" width={120} {...lightbox.zoom([{ src: `${API}/${productId}/persona/image?v=${persona.attempts}` }], 0)} />}
              <div>
                <textarea rows={3} value={personaText} onChange={(event) => setPersonaText(event.target.value)} />
                <div className="brief-actions">
                  <button className="secondary-button" disabled={makePersona.isPending || !personaText.trim()} onClick={() => makePersona.mutate()}>
                    <RotateCcw size={14} /> {makePersona.isPending ? t("Generating…") : persona.image_path ? t("Regenerate portrait") : t("Generate portrait")}
                  </button>
                  {persona.image_path && persona.status !== "approved" && (
                    <button className="primary-button" disabled={reviewPersona.isPending} onClick={() => reviewPersona.mutate("approved")}>
                      <Check size={14} /> {t("Approve person")}
                    </button>
                  )}
                  {persona.status === "approved" && <span className="badge badge--success">{t("approved")}</span>}
                </div>
                {(makePersona.error || reviewPersona.error) && <p role="alert">{(makePersona.error ?? reviewPersona.error)?.message}</p>}
              </div>
            </div>
          ) : (
            <p>{t("This brief has no person. Images use only the product.")}</p>
          )}
        </div>
      )}
      {(step === "images" || step === "clips") && (
        <>
          {step === "images" ? (
            <>
              <p className="brief-note">{t("The master keyframe (shot 1) sets the scene. Approve it first; the other shots are made from it and cost one image each.")}</p>
              <div className="brief-actions">
                <button className="primary-button" disabled={generate.isPending || allApproved || personaPending || (byShot.has(0) && !masterApproved)} onClick={() => generate.mutate(null)}>
                  <ImageIcon size={15} /> {generate.isPending ? t("Generating…") : next}
                </button>
              </div>
              {personaPending && <p role="alert">{t("Approve the person first.")}</p>}
              {generate.error && <p role="alert">{generate.error.message}</p>}
            </>
          ) : (
            <>
              <p className="brief-note">{t("Each approved image becomes one clip. A clip takes a few minutes.")}</p>
              <div className="brief-actions">
                <button className="primary-button" disabled={makeClips.isPending || approvedShots === 0} onClick={() => makeClips.mutate(null)}>
                  <Clapperboard size={15} /> {makeClips.isPending ? t("Starting…") : t("Make clips for approved shots")}
                </button>
              </div>
              {makeClips.error && <p role="alert">{makeClips.error.message}</p>}
            </>
          )}
          <div className="keyframe-grid">
            {shots.map((shot, index) => {
              const keyframe = byShot.get(index);
              const clip = clipByShot.get(index);
              return (
                <figure key={index} className={`keyframe keyframe--${keyframe?.status ?? "empty"}`}>
                  {step === "clips" && clip?.status === "ready" ? (
                    <video src={`${API}/${productId}/clips/${index}/video?v=${clip.attempts}`} controls playsInline preload="metadata" />
                  ) : keyframe && keyframe.status !== "failed" ? (
                    <img src={`${API}/${productId}/keyframes/${index}/image?v=${keyframe.attempts}`} alt={shot.description} loading="lazy" {...lightbox.zoom(frames, frames.findIndex((frame) => frame.index === index))} />
                  ) : (
                    <div className="keyframe-empty">{keyframe?.error ?? t("Not generated yet")}</div>
                  )}
                  <figcaption>
                    <strong>{`${index + 1}. ${shot.role.replaceAll("_", " ")}`}</strong>
                    {step === "images" && keyframe && <span className="badge">{`${keyframe.status} · ×${keyframe.attempts}`}</span>}
                    {step === "images" && keyframe?.qa_problem && <small role="alert">{`${t("Check flagged")}: ${keyframe.qa_problem}`}</small>}
                    {step === "clips" && clip?.status === "processing" && <small>{t("Making the clip…")}</small>}
                    {step === "clips" && clip?.status === "failed" && <small role="alert">{clip.error}</small>}
                    {step === "images" && (
                      <div className="keyframe-actions">
                        {keyframe && keyframe.status !== "failed" && (
                          <>
                            <button className="secondary-button" disabled={review.isPending} onClick={() => review.mutate({ shotIndex: index, status: "approved" })}>
                              <Check size={14} /> {t("Approve")}
                            </button>
                            <button className="secondary-button" disabled={review.isPending} onClick={() => review.mutate({ shotIndex: index, status: "rejected" })}>
                              <X size={14} /> {t("Reject")}
                            </button>
                          </>
                        )}
                        {(keyframe || index === 0) && (index === 0 || masterApproved) && (
                          <button className="secondary-button" disabled={generate.isPending} onClick={() => generate.mutate(index)}>
                            <RotateCcw size={14} /> {t("Regenerate")}
                          </button>
                        )}
                      </div>
                    )}
                  </figcaption>
                </figure>
              );
            })}
          </div>
        </>
      )}
      {step === "voice" && (
        <>
          <label className="brief-field">
            <span>{t("Voice (press play to hear a sample)")}</span>
            <select value={voice} onChange={(event) => setVoice(event.target.value)}>
              {(voices.data ?? []).map((option) => (
                <option key={option.id} value={option.id}>{option.label}</option>
              ))}
            </select>
          </label>
          {voice && <audio key={voice} controls preload="none" src={`${API}/voices/${encodeURIComponent(voice)}/sample`} />}
          <div className="brief-actions">
            <button className="secondary-button" disabled={makeVoice.isPending || approvedShots === 0} onClick={() => makeVoice.mutate()}>
              {makeVoice.isPending ? t("Reading…") : t("Read the voice-over")}
            </button>
          </div>
          {makeVoice.error && <p role="alert">{makeVoice.error.message}</p>}
          {!!makeVoice.data?.too_long_shots.length && <p role="alert">{`${t("These shots have more words than fit in 15 seconds; shorten their voice-over:")} ${makeVoice.data.too_long_shots.join(", ")}`}</p>}
          {hasVoiceFile && <audio controls src={`${API}/${productId}/voiceover?v=${voiceVersion}`} />}
          <details className="brief-edit">
            <summary>{t("Use your own voice-over file")}</summary>
            <label className="brief-field">
              <span>{t("mp3, wav or m4a. It is laid over the video the next time you stitch")}</span>
              <input type="file" accept="audio/mpeg,audio/wav,audio/mp4" onChange={(event) => { const file = event.target.files?.[0]; if (file) uploadVoice.mutate(file); }} />
            </label>
          </details>
          {uploadVoice.isSuccess && <p>{t("Voice-over saved. Stitch the video again to use it.")}</p>}
          {uploadVoice.error && <p role="alert">{uploadVoice.error.message}</p>}
          <label className="brief-check">
            <input type="checkbox" checked={captions} onChange={(event) => setCaptions(event.target.checked)} />
            <span>{t("Burn the on-screen text into the video (it can cover the product)")}</span>
          </label>
          <div className="brief-actions">
            <button className="primary-button" disabled={stitchVideo.isPending || readyClips === 0 || readyClips < approvedShots} onClick={() => stitchVideo.mutate()}>
              {stitchVideo.isPending ? t("Stitching…") : t("Stitch final video")}
            </button>
          </div>
          {stitchVideo.error && <p role="alert">{stitchVideo.error.message}</p>}
          {hasVideo && <video className="final-video" src={`${API}/${productId}/video?v=${videoVersion}`} controls playsInline />}
          {hasVideo && (
            <div className="brief-actions">
              <a className="secondary-button" href={`${API}/${productId}/video?download=true`}>
                <Download size={14} /> {t("Download video")}
              </a>
              <a className="secondary-button" href={`${API}/${productId}/cover?download=true`}>
                <Download size={14} /> {t("Download cover picture")}
              </a>
            </div>
          )}
        </>
      )}
      {step === "post" && (
        <>
          {!hasVideo && <p>{t("Stitch the final video first.")}</p>}
          <div className="brief-actions">
            <button className="primary-button" disabled={writePackage.isPending || !hasVideo} onClick={() => writePackage.mutate()}>
              {writePackage.isPending ? t("Writing…") : postPackage ? t("Rewrite caption and hashtags") : t("Write caption and hashtags")}
            </button>
          </div>
          {writePackage.error && <p role="alert">{writePackage.error.message}</p>}
          {postPackage && (
            <div className="post-package">
              {postPackage.ai_label_reminder && <p><strong>{postPackage.ai_label_reminder}</strong></p>}
              {!!postPackage.warnings?.length && (
                <div role="alert" className="compliance-warning">
                  <strong>{t("TikTok may flag these words. Rewrite them before posting:")}</strong>
                  <ul>{postPackage.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul>
                </div>
              )}
              {postPackage.captions.map((caption, index) => (
                <div className="post-caption" key={index}>
                  <p>{caption}</p>
                  <button className="secondary-button" onClick={() => copy(caption)}><Copy size={14} /> {t("Copy")}</button>
                </div>
              ))}
              <div className="post-caption">
                <p>{postPackage.hashtags.join(" ")}</p>
                <button className="secondary-button" onClick={() => copy(postPackage.hashtags.join(" "))}><Copy size={14} /> {t("Copy")}</button>
              </div>
              {postPackage.product_url && <p><a href={postPackage.product_url} target="_blank" rel="noreferrer">{t("Product link (replace with your affiliate link)")}</a></p>}
            </div>
          )}
        </>
      )}
      {lightbox.node}
    </section>
  );
}

type RunEvent = { id: number; at: string; step: string; shot_index: number | null; status: string; message: string };

function RunLog({ productId, t }: { productId: string; t: (key: string) => string }) {
  const events = useQuery({
    queryKey: ["run-log", productId],
    queryFn: ({ signal }) => getJson<RunEvent[]>(`${API}/${productId}/events`, signal),
    refetchInterval: 5000,
  });
  const rows = [...(events.data ?? [])].reverse();
  return (
    <details className="run-log">
      <summary>{`${t("Run log")} (${rows.length})`}</summary>
      {rows.length === 0 && <p>{t("Nothing has run yet.")}</p>}
      <ul>
        {rows.map((event) => (
          <li key={event.id} className={`run-log--${event.status}`}>
            <time dateTime={event.at}>{new Date(event.at.includes("T") ? event.at : `${event.at.replace(" ", "T")}Z`).toLocaleTimeString()}</time>
            <strong>{event.shot_index === null ? event.step : `${event.step} · ${t("shot")} ${event.shot_index + 1}`}</strong>
            <span className="badge">{event.status}</span>
            <span>{event.message}</span>
          </li>
        ))}
      </ul>
    </details>
  );
}
