import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Clapperboard, Copy, Download, FileText, ImageIcon, RotateCcw, Sparkles, X } from "lucide-react";
import { useState } from "react";
import { EmptyState, PageHeader, Panel, SkeletonPage } from "../components/ui";
import { useI18n } from "../hooks/useI18n";
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
  product_size?: string;
  selling_angle: string;
  target_audience: string;
  style: string[];
  colors: string[];
  shots?: Shot[];
  selected_reference_ids: string[];
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
const STEPS: { id: Step; label: string }[] = [
  { id: "brief", label: "Brief" },
  { id: "person", label: "Person" },
  { id: "images", label: "Images" },
  { id: "clips", label: "Clips" },
  { id: "voice", label: "Voice and video" },
  { id: "post", label: "Post" },
];
const TEXT_FIELDS: { key: "scene" | "product_placement" | "product_size" | "selling_angle" | "target_audience"; label: string; rows: number }[] = [
  { key: "scene", label: "Scene", rows: 3 },
  { key: "product_placement", label: "Product placement", rows: 3 },
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

  return (
    <>
      <PageHeader eyebrow="Affiliate content" title="Briefs" variant="operator" />
      {selectedIds.length === 0 && (
        <EmptyState icon={<FileText />} title="No products selected" text="Select products for content on the Products page first." />
      )}
      {selectedIds.map((productId) => (
        <BriefCard
          key={productId}
          productId={productId}
          productType={selections.data?.[productId] ?? null}
          product={productById.get(productId)}
          record={briefById.get(productId)}
          imageById={imageById}
          t={t}
        />
      ))}
    </>
  );
}

function BriefCard({
  productId,
  productType,
  product,
  record,
  imageById,
  t,
}: {
  productId: string;
  productType: string | null;
  product: Product | undefined;
  record: BriefRecord | undefined;
  imageById: Map<string, string>;
  t: (key: string) => string;
}) {
  const client = useQueryClient();
  const [idea, setIdea] = useState(record?.user_idea ?? "");
  const [videoSeconds, setVideoSeconds] = useState(60);
  const [picked, setPicked] = useState<Step | null>(null);
  const [selectedShot, setSelectedShot] = useState(0);
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

  return (
    <Panel className="brief-card">
      <div className="brief-head">
        {product?.images[0] && <img src={product.images[0]} alt="" width={48} height={48} referrerPolicy="no-referrer" />}
        <div>
          <strong title={product?.title ?? productId}>{product?.title ?? productId}</strong>
          <small>{productType ?? t("No product type yet. Regenerate keywords on the Products page.")}</small>
        </div>
        {record && <span className={`badge badge--${approved ? "success" : "warning"}`}>{record.status}</span>}
      </div>
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
              <span>{t("Video length (about; each shot is one clip)")}</span>
              <select value={videoSeconds} onChange={(event) => setVideoSeconds(Number(event.target.value))}>
                {[15, 30, 45, 60, 75, 90].map((seconds) => (
                  <option key={seconds} value={seconds}>{`${seconds}s`}</option>
                ))}
              </select>
            </label>
            <button className="primary-button" disabled={create.isPending || !productType} onClick={() => create.mutate()}>
              <Sparkles size={15} /> {create.isPending ? t("Writing…") : record ? t("Regenerate brief") : t("Create brief")}
            </button>
          </div>
          {create.error && <p role="alert">{create.error.message}</p>}
          {record && (
            <BriefForm
              record={record}
              imageById={imageById}
              keyframeByShot={keyframeByShot}
              selectedShot={selectedShot}
              onSelect={setSelectedShot}
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
  selectedShot,
  onSelect,
  save,
  saving,
  error,
  t,
}: {
  record: BriefRecord;
  imageById: Map<string, string>;
  keyframeByShot: Map<number, Keyframe>;
  selectedShot: number;
  onSelect: (index: number) => void;
  save: (brief: Partial<Brief>, status: "draft" | "approved") => void;
  saving: boolean;
  error: string | undefined;
  t: (key: string) => string;
}) {
  const { brief } = record;
  const shots = brief.shots ?? [];
  const problems = brief.quality_problems ?? [];
  const warnings = brief.warnings ?? [];
  return (
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
      {!!problems.length && (
        <details className="brief-issues brief-issues--problem">
          <summary>{`${problems.length} ${t("storyboard issues found. Fix them before making images")}`}</summary>
          <ul>{problems.map((problem) => <li key={problem}>{problem}</li>)}</ul>
        </details>
      )}
      {!!warnings.length && (
        <details className="brief-issues">
          <summary>{`${warnings.length} ${t("words TikTok may flag. Rewrite them before posting")}`}</summary>
          <ul>{warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul>
        </details>
      )}
      <div className="brief-layout">
        <aside className="brief-summary">
          <h3>{brief.title}</h3>
          <dl>
            <dt>{t("Selling angle")}</dt>
            <dd>{brief.selling_angle}</dd>
            <dt>{t("Target audience")}</dt>
            <dd>{brief.target_audience}</dd>
            {brief.product_size && (
              <>
                <dt>{t("Real product size")}</dt>
                <dd>{brief.product_size}</dd>
              </>
            )}
          </dl>
          {!!brief.product_photo_urls?.length && (
            <>
              <h4>{t("Product photos the image model sees")}</h4>
              <div className="brief-thumbs">
                {brief.product_photo_urls.map((url) => <img key={url} src={url} alt="" width={44} height={44} referrerPolicy="no-referrer" />)}
              </div>
            </>
          )}
          {!!brief.selected_reference_ids.length && (
            <>
              <h4>{t("Scene reference")}</h4>
              <div className="brief-thumbs">
                {brief.selected_reference_ids.map((id) => imageById.get(id) && <img key={id} src={imageById.get(id)} alt="" width={44} height={58} referrerPolicy="no-referrer" />)}
              </div>
              <p className="brief-note">{brief.reference_rationale}</p>
            </>
          )}
          <details className="brief-edit">
            <summary>{t("Edit brief details")}</summary>
            <label className="brief-field">
              <span>{t("Title")}</span>
              <input name="title" defaultValue={brief.title} />
            </label>
            <label className="brief-field">
              <span>{t("Video format")}</span>
              <select name="format" defaultValue={brief.format ?? FORMATS[0]}>
                {FORMATS.map((format) => <option key={format} value={format}>{format.replaceAll("_", " ")}</option>)}
              </select>
            </label>
            {TEXT_FIELDS.map((field) => (
              <label className="brief-field" key={field.key}>
                <span>{t(field.label)}</span>
                <textarea name={field.key} rows={field.rows} defaultValue={String(brief[field.key] ?? "")} />
              </label>
            ))}
            <label className="brief-field">
              <span>{t("Style (comma separated)")}</span>
              <input name="style" defaultValue={brief.style.join(", ")} />
            </label>
            <label className="brief-field">
              <span>{t("Colors (comma separated)")}</span>
              <input name="colors" defaultValue={brief.colors.join(", ")} />
            </label>
          </details>
        </aside>
        <div className="brief-main">
          <h3>{t("Storyboard")}</h3>
          <div className="storyboard">
            {shots.map((shot, index) => {
              const keyframe = keyframeByShot.get(index);
              return (
                <button key={index} type="button" className={`shot-card${index === selectedShot ? " shot-card--on" : ""}`} onClick={() => onSelect(index)}>
                  <span className="shot-card__role">{`${index + 1}. ${shot.role.replaceAll("_", " ")}`}</span>
                  {keyframe && keyframe.status !== "failed" ? (
                    <img src={`${API}/${record.product_id}/keyframes/${index}/image?v=${keyframe.attempts}`} alt="" loading="lazy" />
                  ) : (
                    <span className="shot-card__empty">{t("No image yet")}</span>
                  )}
                  <span className="shot-card__text">{shot.description}</span>
                  <span className="shot-card__chips">
                    <span className="chip">{shot.delivery === "talking" ? t("Talking") : t("Narrated")}</span>
                    <span className="chip">{`${wordCount(shot.voiceover)} ${t("words")}`}</span>
                  </span>
                </button>
              );
            })}
          </div>
          {shots.map((shot, index) => (
            <section className="shot-editor" key={`${index}-${shot.keyframe_prompt}`} hidden={index !== selectedShot}>
              <h4>{`${index + 1}. ${shot.role.replaceAll("_", " ")}`}</h4>
              <label className="brief-field">
                <span>{t("Voice-over")}</span>
                <textarea name={`shot_${index}_voiceover`} rows={4} defaultValue={shot.voiceover} />
              </label>
              <label className="brief-field">
                <span>{t("Text on screen")}</span>
                <input name={`shot_${index}_on_screen_text`} defaultValue={shot.on_screen_text} />
              </label>
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
              <details className="brief-edit">
                <summary>{t("Prompts for the models")}</summary>
                <label className="brief-field">
                  <span>{t("Keyframe image prompt")}</span>
                  <textarea name={`shot_${index}_keyframe_prompt`} rows={5} defaultValue={shot.keyframe_prompt} />
                </label>
                <label className="brief-field">
                  <span>{t("Motion prompt")}</span>
                  <textarea name={`shot_${index}_motion_prompt`} rows={4} defaultValue={shot.motion_prompt} />
                </label>
              </details>
            </section>
          ))}
          {!shots.length && <p>{t("This brief has no storyboard yet. Regenerate it.")}</p>}
        </div>
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
  const personaPending = !!persona?.description && persona.status !== "approved";
  const clipByShot = new Map(clips.map((clip) => [clip.shot_index, clip]));
  const approvedShots = shots.filter((_, index) => byShot.get(index)?.status === "approved").length;
  const readyClips = [...clipByShot.values()].filter((clip) => clip.status === "ready").length;
  const masterApproved = byShot.get(0)?.status === "approved";
  const allApproved = shots.length > 0 && shots.every((_, index) => byShot.get(index)?.status === "approved");
  const next = !byShot.has(0) || !masterApproved ? t("Generate master keyframe") : t("Generate the other shots");

  return (
    <section className="keyframes">
      {step === "person" && (
        <div className="persona">
          <h3>{t("Person in the video")}</h3>
          <p className="brief-note">{t("A synthetic person; one portrait is reused in every shot.")}</p>
          {persona?.description ? (
            <div className="persona-body">
              {persona.image_path && <img src={`${API}/${productId}/persona/image?v=${persona.attempts}`} alt="" width={120} />}
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
                    <img src={`${API}/${productId}/keyframes/${index}/image?v=${keyframe.attempts}`} alt={shot.description} loading="lazy" />
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
