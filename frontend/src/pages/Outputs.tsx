import { useQuery } from "@tanstack/react-query";
import { Download, Film } from "lucide-react";
import { Link, useSearchParams } from "react-router-dom";
import { EmptyState, PageHeader, Panel, SkeletonPage } from "../components/ui";
import { useI18n } from "../hooks/useI18n";
import { getJson } from "../services/http";

type OutputItem = {
  product_id: string;
  title: string | null;
  product_title: string | null;
  image: string | null;
  built_at: string | null;
  seconds: number | null;
  shots: number;
  voice: string | null;
  has_cover: boolean;
};
type OutputShot = {
  index: number;
  role: string | null;
  delivery: "narrated" | "talking";
  description: string | null;
  voiceover: string | null;
  on_screen_text: string | null;
  has_keyframe: boolean;
  keyframe_attempts: number | null;
  has_clip: boolean;
  clip_attempts: number | null;
  in_video: boolean;
};
type OutputDetail = {
  product: { product_id: string; title: string | null; url: string | null; image: string | null };
  brief: { title: string | null; status: string; format: string | null; user_idea: string; selling_angle: string | null; target_audience: string | null; product_size: string | null };
  product_photos: string[];
  references: { image_id: string; image_url: string; pin_url: string | null; title: string | null }[];
  persona: { description: string; has_image: boolean } | null;
  shots: OutputShot[];
  video: { built_at: string | null; seconds: number | null; captions: boolean | null; voice: string | null; has_cover: boolean; exists: boolean };
};

const API = "/api/v1/products";
const when = (value: string | null) => (value ? new Date(value).toLocaleString() : null);

export function OutputsPage() {
  const [params] = useSearchParams();
  const productId = params.get("product");
  return productId ? <OutputDetailView productId={productId} /> : <OutputList />;
}

function OutputList() {
  const { t } = useI18n();
  const outputs = useQuery({ queryKey: ["outputs"], queryFn: ({ signal }) => getJson<OutputItem[]>(`${API}/outputs`, signal) });
  if (outputs.isLoading) return <SkeletonPage />;
  return (
    <>
      <PageHeader eyebrow="Affiliate content" title="Outputs" variant="operator" />
      {outputs.data?.length ? (
        <div className="output-grid">
          {outputs.data.map((item) => (
            <Link key={item.product_id} className="output-card" to={`?product=${item.product_id}`}>
              <img src={item.has_cover ? `${API}/${item.product_id}/cover` : (item.image ?? "")} alt="" loading="lazy" referrerPolicy="no-referrer" />
              <strong>{item.title ?? item.product_title ?? item.product_id}</strong>
              <small>{[item.seconds ? `${Math.round(item.seconds)}s` : null, `${item.shots} ${t("shots")}`, item.voice].filter(Boolean).join(" · ")}</small>
              {item.built_at && <small>{when(item.built_at)}</small>}
            </Link>
          ))}
        </div>
      ) : (
        <EmptyState icon={<Film />} title="No finished videos yet" text="Stitch a final video on the Briefs page and it appears here." />
      )}
    </>
  );
}

function OutputDetailView({ productId }: { productId: string }) {
  const { t } = useI18n();
  const output = useQuery({ queryKey: ["output", productId], queryFn: ({ signal }) => getJson<OutputDetail>(`${API}/${productId}/output`, signal) });
  if (output.isLoading) return <SkeletonPage />;
  if (!output.data) return <EmptyState icon={<Film />} title="Output not found" text="This product has no brief or video yet." />;
  const { product, brief, video, shots } = output.data;
  const made = [
    video.seconds ? `${Math.round(video.seconds)}s` : null,
    video.built_at ? when(video.built_at) : null,
  ].filter(Boolean);
  return (
    <>
      <PageHeader
        eyebrow="Outputs"
        title={brief.title ?? product.title ?? productId}
        variant="operator"
        actions={<Link className="secondary-button" to="/outputs">{t("Back to outputs")}</Link>}
      />
      <Panel>
        <div className="output-detail">
          <div className="output-player">
            {video.exists ? <video src={`${API}/${productId}/video`} poster={video.has_cover ? `${API}/${productId}/cover` : undefined} controls playsInline /> : <p>{t("The video file is missing.")}</p>}
            <div className="brief-actions">
              <a className="secondary-button" href={`${API}/${productId}/video?download=true`}><Download size={14} /> {t("Download video")}</a>
              {video.has_cover && <a className="secondary-button" href={`${API}/${productId}/cover?download=true`}><Download size={14} /> {t("Download cover picture")}</a>}
            </div>
            <dl className="output-facts">
              <dt>{t("Made")}</dt>
              <dd>{made.join(" · ") || t("unknown")}</dd>
              <dt>{t("Voice")}</dt>
              <dd>{video.voice ?? t("unknown")}</dd>
              <dt>{t("On-screen text burned in")}</dt>
              <dd>{video.captions === null ? t("unknown") : video.captions ? t("yes") : t("no")}</dd>
            </dl>
            <Link className="secondary-button" to="/briefs">{t("Open in Briefs")}</Link>
          </div>
          <div className="output-flow">
            <section className="output-block">
              <h3>{t("Product")}</h3>
              <div className="output-row">
                {product.image && <img src={product.image} alt="" width={56} height={56} referrerPolicy="no-referrer" />}
                <div>
                  <strong>{product.title ?? productId}</strong>
                  {product.url && <p><a href={product.url} target="_blank" rel="noreferrer">{t("Open the product page")}</a></p>}
                </div>
              </div>
            </section>
            <section className="output-block">
              <h3>{t("What the brief looked at")}</h3>
              {!!output.data.product_photos.length && (
                <>
                  <p className="brief-note">{t("Product photos the image model saw")}</p>
                  <div className="output-thumbs">
                    {output.data.product_photos.map((url) => <img key={url} src={url} alt="" width={56} height={56} referrerPolicy="no-referrer" />)}
                  </div>
                </>
              )}
              {!!output.data.references.length && (
                <>
                  <p className="brief-note">{t("Scene reference")}</p>
                  <div className="output-thumbs">
                    {output.data.references.map((image) => (
                      <a key={image.image_id} href={image.pin_url ? `https://www.pinterest.com${image.pin_url}` : image.image_url} target="_blank" rel="noreferrer">
                        <img src={image.image_url} alt={image.title ?? ""} width={56} height={74} referrerPolicy="no-referrer" />
                      </a>
                    ))}
                  </div>
                </>
              )}
              {brief.user_idea && <p><span className="brief-note">{t("Your idea")}:</span> {brief.user_idea}</p>}
            </section>
            {output.data.persona && (
              <section className="output-block">
                <h3>{t("Person")}</h3>
                <div className="output-row">
                  {output.data.persona.has_image && <img src={`${API}/${productId}/persona/image`} alt="" width={64} height={114} />}
                  <p>{output.data.persona.description}</p>
                </div>
              </section>
            )}
            <section className="output-block">
              <h3>{t("Brief")}</h3>
              <dl className="output-facts">
                <dt>{t("Format")}</dt>
                <dd>{(brief.format ?? "").replaceAll("_", " ")}</dd>
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
            </section>
            <section className="output-block">
              <h3>{t("Images, clips and voice-over of each shot")}</h3>
              <div className="output-shots">
                {shots.map((shot) => (
                  <div key={shot.index} className={`output-shot${shot.in_video ? "" : " output-shot--unused"}`}>
                    {shot.has_keyframe ? <img src={`${API}/${productId}/keyframes/${shot.index}/image?v=${shot.keyframe_attempts ?? 0}`} alt="" loading="lazy" /> : <span />}
                    {shot.has_clip ? <video src={`${API}/${productId}/clips/${shot.index}/video?v=${shot.clip_attempts ?? 0}`} controls playsInline preload="metadata" /> : <span />}
                    <div>
                      <strong>{`${shot.index + 1}. ${(shot.role ?? "").replaceAll("_", " ")}`}</strong>
                      <span className="chip">{shot.delivery === "talking" ? t("Talking") : t("Narrated")}</span>
                      {!shot.in_video && <span className="chip">{t("not in the video")}</span>}
                      <p>{shot.voiceover}</p>
                      {shot.on_screen_text && <p className="brief-note">{`${t("Text on screen")}: ${shot.on_screen_text}`}</p>}
                      <p className="brief-note">{`${t("Image tries")}: ${shot.keyframe_attempts ?? 0} · ${t("Clip tries")}: ${shot.clip_attempts ?? 0}`}</p>
                    </div>
                  </div>
                ))}
              </div>
            </section>
          </div>
        </div>
      </Panel>
    </>
  );
}
