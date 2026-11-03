import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Clapperboard, Copy, Download, FileText, ImageIcon, RotateCcw, Sparkles, X } from "lucide-react";
import { useState } from "react";
import { EmptyState, PageHeader, Panel, SkeletonPage } from "../components/ui";
import { useI18n } from "../hooks/useI18n";
import { getJson, postJson, putJson } from "../services/http";

type PostPackage = { captions: string[]; hashtags: string[]; product_url: string; warnings?: string[]; ai_label_reminder?: string };
type Shot = {
  role: string;
  description: string;
  keyframe_prompt: string;
  motion_prompt: string;
  duration_seconds: number;
  on_screen_text: string;
  voiceover: string;
};
type Brief = {
  title: string;
  format?: string;
  warnings?: string[];
  reference_rationale: string;
  scene: string;
  product_placement: string;
  selling_angle: string;
  target_audience: string;
  style: string[];
  colors: string[];
  shots?: Shot[];
  selected_reference_ids: string[];
  post_package?: PostPackage;
};
type BriefRecord = { product_id: string; user_idea: string; brief: Brief; status: "draft" | "approved" };
type Keyframe = { shot_index: number; status: "ready" | "approved" | "rejected" | "failed"; attempts: number; error: string | null; qa_problem: string };
type Clip = { shot_index: number; status: "processing" | "ready" | "failed"; seconds: number; attempts: number; error: string | null };
type Product = { product_id: string; title: string | null; images: string[] };
type ReferenceImage = { image_id: string; image_url: string };

const API = "/api/v1/products";
const TEXT_FIELDS: { key: "scene" | "product_placement" | "selling_angle" | "target_audience"; label: string; rows: number }[] = [
  { key: "scene", label: "Scene", rows: 3 },
  { key: "product_placement", label: "Product placement", rows: 3 },
  { key: "selling_angle", label: "Selling angle", rows: 2 },
  { key: "target_audience", label: "Target audience", rows: 2 },
];
const SHOT_FIELDS: { key: "description" | "keyframe_prompt" | "motion_prompt" | "on_screen_text" | "voiceover"; label: string; rows: number }[] = [
  { key: "description", label: "What the viewer sees", rows: 2 },
  { key: "keyframe_prompt", label: "Keyframe image prompt", rows: 5 },
  { key: "motion_prompt", label: "Motion prompt", rows: 2 },
  { key: "on_screen_text", label: "Text on screen", rows: 1 },
  { key: "voiceover", label: "Voice-over", rows: 2 },
];
const FORMATS = ["problem_solution", "step_by_step", "before_after", "unboxing", "worth_it_text"];
const words = (text: string) => text.split(",").map((word) => word.trim()).filter(Boolean);

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
      <PageHeader
        eyebrow="Affiliate content"
        title="Briefs"
        description="The agent writes one brief per selected product from its best live reference scenes. Add your own idea and the agent builds on it."
      />
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
  const [videoSeconds, setVideoSeconds] = useState(15);
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

  return (
    <Panel>
      <div className="brief-head">
        {product?.images[0] && <img src={product.images[0]} alt="" width={56} height={56} />}
        <div>
          <strong>{product?.title ?? productId}</strong>
          <small>{productType ?? t("No product type yet. Regenerate keywords on the Products page.")}</small>
        </div>
        {record && <span className={`badge badge--${record.status === "approved" ? "success" : "warning"}`}>{record.status}</span>}
      </div>
      <label className="brief-field">
        <span>{t("Your idea (optional)")}</span>
        <textarea rows={2} value={idea} onChange={(event) => setIdea(event.target.value)} placeholder={t("e.g. sunny balcony, tidy feeling for small apartments")} />
      </label>
      <label className="brief-field">
        <span>{t("Video length (each shot is one 15 second clip)")}</span>
        <select value={videoSeconds} onChange={(event) => setVideoSeconds(Number(event.target.value))}>
          {[15, 30, 45, 60, 75, 90].map((seconds) => (
            <option key={seconds} value={seconds}>{`${seconds}s · ${seconds / 15} ${seconds === 15 ? t("shot") : t("shots")}`}</option>
          ))}
        </select>
      </label>
      <div className="brief-actions">
        <button className="primary-button" disabled={create.isPending || !productType} onClick={() => create.mutate()}>
          <Sparkles size={15} /> {create.isPending ? t("Writing…") : record ? t("Regenerate brief") : t("Create brief")}
        </button>
      </div>
      {create.error && <p role="alert">{create.error.message}</p>}
      {record && (
        <form
          key={`${record.product_id}-${record.status}-${record.brief.title}`}
          className="brief-form"
          onSubmit={(event) => {
            event.preventDefault();
            const submitter = (event.nativeEvent as SubmitEvent).submitter as HTMLButtonElement | null;
            const data = new FormData(event.currentTarget);
            const brief: Partial<Brief> = {
              title: String(data.get("title")),
              format: String(data.get("format")),
              style: words(String(data.get("style"))),
              colors: words(String(data.get("colors"))),
            };
            for (const field of TEXT_FIELDS) Object.assign(brief, { [field.key]: String(data.get(field.key)) });
            brief.shots = (record.brief.shots ?? []).map((shot, index) => {
              const next: Shot = { ...shot, duration_seconds: Number(data.get(`shot_${index}_duration`)) || shot.duration_seconds };
              for (const field of SHOT_FIELDS) next[field.key] = String(data.get(`shot_${index}_${field.key}`));
              return next;
            });
            save.mutate({ brief, status: submitter?.value === "approved" ? "approved" : "draft" });
          }}
        >
          <label className="brief-field">
            <span>{t("Title")}</span>
            <input name="title" defaultValue={record.brief.title} />
          </label>
          <label className="brief-field">
            <span>{t("Video format")}</span>
            <select name="format" defaultValue={record.brief.format ?? FORMATS[0]}>
              {FORMATS.map((format) => <option key={format} value={format}>{format.replaceAll("_", " ")}</option>)}
            </select>
          </label>
          {!!record.brief.warnings?.length && (
            <div role="alert" className="compliance-warning">
              <strong>{t("TikTok may flag these words. Rewrite them before posting:")}</strong>
              <ul>{record.brief.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul>
            </div>
          )}
          <div className="brief-references">
            {record.brief.selected_reference_ids.map((id) => imageById.get(id) && <img key={id} src={imageById.get(id)} alt="" width={72} height={96} referrerPolicy="no-referrer" />)}
            <p>{record.brief.reference_rationale}</p>
          </div>
          {TEXT_FIELDS.map((field) => (
            <label className="brief-field" key={field.key}>
              <span>{t(field.label)}</span>
              <textarea name={field.key} rows={field.rows} defaultValue={String(record.brief[field.key] ?? "")} />
            </label>
          ))}
          {(record.brief.shots ?? []).map((shot, index) => (
            <fieldset className="brief-shot" key={`${index}-${shot.keyframe_prompt}`}>
              <legend>{`${index + 1}. ${shot.role}`}</legend>
              <label className="brief-field">
                <span>{t("Seconds")}</span>
                <input name={`shot_${index}_duration`} type="number" min={1} max={15} defaultValue={shot.duration_seconds} />
              </label>
              {SHOT_FIELDS.map((field) => (
                <label className="brief-field" key={field.key}>
                  <span>{t(field.label)}</span>
                  <textarea name={`shot_${index}_${field.key}`} rows={field.rows} defaultValue={shot[field.key]} />
                </label>
              ))}
            </fieldset>
          ))}
          {!record.brief.shots?.length && <p>{t("This brief has no storyboard yet. Regenerate it.")}</p>}
          <label className="brief-field">
            <span>{t("Style (comma separated)")}</span>
            <input name="style" defaultValue={record.brief.style.join(", ")} />
          </label>
          <label className="brief-field">
            <span>{t("Colors (comma separated)")}</span>
            <input name="colors" defaultValue={record.brief.colors.join(", ")} />
          </label>
          <div className="brief-actions">
            <button className="secondary-button" type="submit" value="draft" disabled={save.isPending}>{t("Save draft")}</button>
            <button className="primary-button" type="submit" value="approved" disabled={save.isPending}>{t("Approve brief")}</button>
          </div>
          {save.error && <p role="alert">{save.error.message}</p>}
        </form>
      )}
      {record?.status === "approved" && <Keyframes productId={productId} shots={record.brief.shots ?? []} postPackage={record.brief.post_package} t={t} />}
    </Panel>
  );
}

function Keyframes({ productId, shots, postPackage, t }: { productId: string; shots: Shot[]; postPackage?: PostPackage; t: (key: string) => string }) {
  const client = useQueryClient();
  const keyframes = useQuery({
    queryKey: ["keyframes", productId],
    queryFn: ({ signal }) => getJson<Keyframe[]>(`${API}/${productId}/keyframes`, signal),
  });
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
  const clips = useQuery({
    queryKey: ["clips", productId],
    queryFn: ({ signal }) => getJson<Clip[]>(`${API}/${productId}/clips`, signal),
    refetchInterval: (query) => (query.state.data?.some((clip) => clip.status === "processing") ? 5000 : false),
  });
  const refreshClips = () => client.invalidateQueries({ queryKey: ["clips", productId] });
  const makeClips = useMutation({
    mutationFn: (shotIndex: number | null) => postJson<Clip[]>(`${API}/${productId}/clips`, { shot_index: shotIndex }),
    onSuccess: refreshClips,
  });
  const [videoVersion, setVideoVersion] = useState(0);
  const videoInfo = useQuery({
    queryKey: ["video-info", productId],
    queryFn: ({ signal }) => getJson<{ exists: boolean }>(`${API}/${productId}/video-info`, signal),
  });
  const hasVideo = videoVersion > 0 || !!videoInfo.data?.exists;
  const stitchVideo = useMutation({
    mutationFn: () => postJson<{ video: string }>(`${API}/${productId}/video`),
    onSuccess: () => {
      setVideoVersion((version) => version + 1);
      client.invalidateQueries({ queryKey: ["video-info", productId] });
    },
  });
  const byShot = new Map((keyframes.data ?? []).map((keyframe) => [keyframe.shot_index, keyframe]));
  const writePackage = useMutation({
    mutationFn: () => postJson<PostPackage>(`${API}/${productId}/post-package`),
    onSuccess: () => client.invalidateQueries({ queryKey: ["briefs"] }),
  });
  const copy = (text: string) => navigator.clipboard?.writeText(text).catch(() => undefined);
  const clipByShot = new Map((clips.data ?? []).map((clip) => [clip.shot_index, clip]));
  const approvedShots = shots.filter((_, index) => byShot.get(index)?.status === "approved").length;
  const readyClips = [...clipByShot.values()].filter((clip) => clip.status === "ready").length;
  const masterApproved = byShot.get(0)?.status === "approved";
  const allApproved = shots.length > 0 && shots.every((_, index) => byShot.get(index)?.status === "approved");
  const next = !byShot.has(0) || !masterApproved ? t("Generate master keyframe") : t("Generate the other shots");

  return (
    <section className="keyframes">
      <h3>{t("Keyframes")}</h3>
      <p>{t("The master keyframe (shot 1) sets the scene. Approve it first; the other shots are made from it and cost one image each.")}</p>
      <div className="brief-actions">
        <button className="primary-button" disabled={generate.isPending || allApproved || (byShot.has(0) && !masterApproved)} onClick={() => generate.mutate(null)}>
          <ImageIcon size={15} /> {generate.isPending ? t("Generating…") : next}
        </button>
      </div>
      {generate.error && <p role="alert">{generate.error.message}</p>}
      <div className="brief-actions">
        <button className="primary-button" disabled={makeClips.isPending || approvedShots === 0} onClick={() => makeClips.mutate(null)}>
          <Clapperboard size={15} /> {makeClips.isPending ? t("Starting…") : t("Make clips for approved shots")}
        </button>
        <button className="secondary-button" disabled={stitchVideo.isPending || readyClips === 0 || readyClips < approvedShots} onClick={() => stitchVideo.mutate()}>
          {stitchVideo.isPending ? t("Stitching…") : t("Stitch final video")}
        </button>
      </div>
      {makeClips.error && <p role="alert">{makeClips.error.message}</p>}
      {stitchVideo.error && <p role="alert">{stitchVideo.error.message}</p>}
      {hasVideo && <video className="final-video" src={`${API}/${productId}/video?v=${videoVersion}`} controls playsInline />}
      {hasVideo && (
        <div className="brief-actions">
          <a className="secondary-button" href={`${API}/${productId}/video?download=true`}>
            <Download size={14} /> {t("Download video")}
          </a>
          <button className="secondary-button" disabled={writePackage.isPending} onClick={() => writePackage.mutate()}>
            {writePackage.isPending ? t("Writing…") : postPackage ? t("Rewrite caption and hashtags") : t("Write caption and hashtags")}
          </button>
        </div>
      )}
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
      <div className="keyframe-grid">
        {shots.map((shot, index) => {
          const keyframe = byShot.get(index);
          return (
            <figure key={index} className={`keyframe keyframe--${keyframe?.status ?? "empty"}`}>
              {keyframe && keyframe.status !== "failed" ? (
                <img src={`${API}/${productId}/keyframes/${index}/image?v=${keyframe.attempts}`} alt={shot.description} loading="lazy" />
              ) : (
                <div className="keyframe-empty">{keyframe?.error ?? t("Not generated yet")}</div>
              )}
              <figcaption>
                <strong>{`${index + 1}. ${shot.role}`}</strong>
                {keyframe && <span className="badge">{`${keyframe.status} · ×${keyframe.attempts}`}</span>}
                {keyframe?.qa_problem && <small role="alert">{`${t("Check flagged")}: ${keyframe.qa_problem}`}</small>}
                {clipByShot.get(index)?.status === "ready" && (
                  <video src={`${API}/${productId}/clips/${index}/video?v=${clipByShot.get(index)?.attempts}`} controls playsInline preload="metadata" />
                )}
                {clipByShot.get(index)?.status === "processing" && <small>{t("Making the clip…")}</small>}
                {clipByShot.get(index)?.status === "failed" && <small role="alert">{clipByShot.get(index)?.error}</small>}
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
              </figcaption>
            </figure>
          );
        })}
      </div>
    </section>
  );
}
