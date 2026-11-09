import { useQuery } from "@tanstack/react-query";
import { Download, Film, Sparkles, Layers, Image as ImageIcon, ExternalLink, ArrowLeft } from "lucide-react";
import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { EmptyState, PageHeader, SkeletonPage } from "../components/ui";
import { useI18n } from "../hooks/useI18n";
import { useLightbox } from "../hooks/useLightbox";
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
  persona: { photos: number } | null;
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
              <div className="output-card__thumb">
                <img src={item.has_cover ? `${API}/${item.product_id}/cover` : (item.image ?? "")} alt="" loading="lazy" referrerPolicy="no-referrer" />
                {item.seconds && <span className="output-card__duration">{Math.round(item.seconds)}s</span>}
              </div>
              <div className="output-card__meta">
                <strong>{item.title ?? item.product_title ?? item.product_id}</strong>
                <div className="output-card__tags">
                  <span className="chip chip--sm">{item.shots} {t("shots")}</span>
                  {item.voice && <span className="chip chip--sm">{item.voice}</span>}
                </div>
                {item.built_at && <small className="output-card__date">{when(item.built_at)}</small>}
                <div className="output-card__actions">
                  <a
                    className="primary-button output-card__btn-download"
                    href={`${API}/${item.product_id}/video?download=true`}
                    onClick={(e) => e.stopPropagation()}
                    title={t("Download video")}
                  >
                    <Download size={13} /> {t("Download")}
                  </a>
                </div>
              </div>
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
  const lightbox = useLightbox();
  const [activeTab, setActiveTab] = useState<"shots" | "specs">("shots");
  const output = useQuery({ queryKey: ["output", productId], queryFn: ({ signal }) => getJson<OutputDetail>(`${API}/${productId}/output`, signal) });

  if (output.isLoading) return <SkeletonPage />;
  if (!output.data) return <EmptyState icon={<Film />} title="Output not found" text="This product has no brief or video yet." />;

  const { product, brief, video, shots } = output.data;
  const photos = output.data.product_photos.map((src) => ({ src }));
  const references = output.data.references.map((image) => ({
    src: image.image_url,
    label: image.title ?? undefined,
    href: image.pin_url ? `https://www.pinterest.com${image.pin_url}` : undefined,
  }));
  const frames = shots.filter((shot) => shot.has_keyframe).map((shot) => ({
    index: shot.index,
    src: `${API}/${productId}/keyframes/${shot.index}/image?v=${shot.keyframe_attempts ?? 0}`,
    label: `${shot.index + 1}. ${(shot.role ?? "").replaceAll("_", " ")}`,
  }));

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
        actions={<Link className="secondary-button" to="/outputs"><ArrowLeft size={14} /> {t("Back to outputs")}</Link>}
      />
      <div className="output-studio">
        {/* Left Column: Phone Mockup Frame & Main Actions */}
        <aside className="output-studio__stage">
          <div className="phone-mockup">
            <div className="phone-mockup__notch" />
            <div className="phone-mockup__screen">
              {video.exists ? (
                <video
                  src={`${API}/${productId}/video`}
                  poster={video.has_cover ? `${API}/${productId}/cover` : undefined}
                  controls
                  playsInline
                />
              ) : (
                <div className="phone-mockup__empty">
                  <Film size={36} />
                  <p>{t("The video file is missing.")}</p>
                </div>
              )}
            </div>
          </div>

          <div className="output-studio__actions">
            <a className="primary-button output-studio__btn-main" href={`${API}/${productId}/video?download=true`}>
              <Download size={16} /> {t("Download video")}
            </a>
            {video.has_cover && (
              <a className="secondary-button" href={`${API}/${productId}/cover?download=true`}>
                <ImageIcon size={14} /> {t("Download cover picture")}
              </a>
            )}
            <Link className="secondary-button" to="/briefs">
              <Sparkles size={14} /> {t("Open in Briefs")}
            </Link>
          </div>

          <div className="output-specs-card">
            <dl className="output-facts">
              <dt>{t("Made")}</dt>
              <dd>{made.join(" · ") || t("unknown")}</dd>
              <dt>{t("Voice")}</dt>
              <dd>{video.voice ?? t("unknown")}</dd>
              <dt>{t("On-screen text burned in")}</dt>
              <dd>{video.captions === null ? t("unknown") : video.captions ? t("yes") : t("no")}</dd>
            </dl>
          </div>
        </aside>

        {/* Right Column: Organized Workspace */}
        <main className="output-studio__content">
          {/* Product Banner */}
          <section className="output-hero-product">
            {product.image && (
              <img
                src={product.image}
                alt=""
                width={64}
                height={64}
                referrerPolicy="no-referrer"
                {...lightbox.zoom([{ src: product.image }], 0)}
              />
            )}
            <div className="output-hero-product__info">
              <span className="eyebrow">{t("Product")}</span>
              <strong>{product.title ?? productId}</strong>
              {product.url && (
                <a href={product.url} target="_blank" rel="noreferrer" className="output-hero-product__link">
                  {t("Open the product page")} <ExternalLink size={12} />
                </a>
              )}
            </div>
          </section>

          {/* Navigation Tabs */}
          <nav className="output-tabs" aria-label="Output views">
            <button
              type="button"
              className={`output-tab${activeTab === "shots" ? " output-tab--active" : ""}`}
              onClick={() => setActiveTab("shots")}
            >
              <Layers size={14} /> {t("Images, clips and voice-over of each shot")} ({shots.length})
            </button>
            <button
              type="button"
              className={`output-tab${activeTab === "specs" ? " output-tab--active" : ""}`}
              onClick={() => setActiveTab("specs")}
            >
              <Sparkles size={14} /> {t("What the brief looked at")}
            </button>
          </nav>

          {/* Tab 1: Shots Timeline */}
          {activeTab === "shots" && (
            <section className="output-shots-timeline">
              {shots.map((shot) => (
                <div key={shot.index} className={`output-shot-card${shot.in_video ? "" : " output-shot-card--unused"}`}>
                  <div className="output-shot-card__media">
                    {shot.has_clip ? (
                      <div className="output-shot-card__video-wrap">
                        <video
                          src={`${API}/${productId}/clips/${shot.index}/video?v=${shot.clip_attempts ?? 0}`}
                          controls
                          playsInline
                          preload="metadata"
                        />
                        {shot.has_keyframe && (
                          <button
                            type="button"
                            className="output-shot-card__kf-badge"
                            title={t("View draft keyframe image")}
                            onClick={() => lightbox.open(frames, frames.findIndex((frame) => frame.index === shot.index))}
                          >
                            <ImageIcon size={11} /> {t("Keyframe")}
                          </button>
                        )}
                      </div>
                    ) : shot.has_keyframe ? (
                      <div className="output-shot-card__video-wrap">
                        <img
                          src={`${API}/${productId}/keyframes/${shot.index}/image?v=${shot.keyframe_attempts ?? 0}`}
                          alt=""
                          loading="lazy"
                          {...lightbox.zoom(frames, frames.findIndex((frame) => frame.index === shot.index))}
                        />
                        <span className="output-shot-card__kf-tag">{t("Keyframe only")}</span>
                      </div>
                    ) : (
                      <div className="output-shot-card__placeholder">{t("No media yet")}</div>
                    )}
                  </div>
                  <div className="output-shot-card__body">
                    <div className="output-shot-card__head">
                      <span className="output-shot-card__index">{shot.index + 1}</span>
                      <strong>{(shot.role ?? "").replaceAll("_", " ")}</strong>
                      <span className="chip chip--accent">{shot.delivery === "talking" ? t("Talking") : t("Narrated")}</span>
                      {!shot.in_video && <span className="chip chip--warning">{t("not in the video")}</span>}
                    </div>
                    <p className="output-shot-card__voiceover">{shot.voiceover}</p>
                    {shot.on_screen_text && (
                      <div className="output-shot-card__subtitle">
                        <span className="chip chip--outline">{t("Text on screen")}</span>
                        <span>{shot.on_screen_text}</span>
                      </div>
                    )}
                    <div className="output-shot-card__stats">
                      <span>{`${t("Image tries")}: ${shot.keyframe_attempts ?? 0}`}</span>
                      <span>·</span>
                      <span>{`${t("Clip tries")}: ${shot.clip_attempts ?? 0}`}</span>
                    </div>
                  </div>
                </div>
              ))}
            </section>
          )}

          {/* Tab 2: Specs & Source Brief */}
          {activeTab === "specs" && (
            <div className="output-specs-view">
              <section className="panel-section">
                <h3>{t("Brief")}</h3>
                <dl className="output-facts-grid">
                  <div>
                    <dt>{t("Format")}</dt>
                    <dd>{(brief.format ?? "").replaceAll("_", " ")}</dd>
                  </div>
                  <div>
                    <dt>{t("Selling angle")}</dt>
                    <dd>{brief.selling_angle}</dd>
                  </div>
                  <div>
                    <dt>{t("Target audience")}</dt>
                    <dd>{brief.target_audience}</dd>
                  </div>
                  {brief.product_size && (
                    <div>
                      <dt>{t("Real product size")}</dt>
                      <dd>{brief.product_size}</dd>
                    </div>
                  )}
                </dl>
              </section>

              {!!output.data.product_photos.length && (
                <section className="panel-section">
                  <h3>{t("Product photos the image model saw")}</h3>
                  <div className="output-gallery">
                    {photos.map((photo, index) => (
                      <img
                        key={photo.src}
                        src={photo.src}
                        alt=""
                        width={80}
                        height={80}
                        referrerPolicy="no-referrer"
                        {...lightbox.zoom(photos, index)}
                      />
                    ))}
                  </div>
                </section>
              )}

              {!!output.data.references.length && (
                <section className="panel-section">
                  <h3>{t("Scene reference")}</h3>
                  <div className="output-gallery">
                    {references.map((image, index) => (
                      <img
                        key={image.src}
                        src={image.src}
                        alt={image.label ?? ""}
                        width={80}
                        height={106}
                        referrerPolicy="no-referrer"
                        {...lightbox.zoom(references, index)}
                      />
                    ))}
                  </div>
                </section>
              )}

              {output.data.persona && (
                <section className="panel-section">
                  <h3>{t("Person")}</h3>
                  <div className="output-row">
                    {Array.from({ length: output.data.persona.photos }, (_, index) => `${API}/${productId}/persona/image?n=${index}`).map((src, index, all) => (
                      <img key={src} src={src} alt="" width={72} height={128} {...lightbox.zoom(all.map((item) => ({ src: item, label: t("Person") })), index)} />
                    ))}
                  </div>
                </section>
              )}

              {brief.user_idea && (
                <section className="panel-section">
                  <h3>{t("Your idea")}</h3>
                  <p>{brief.user_idea}</p>
                </section>
              )}
            </div>
          )}
        </main>
      </div>
      {lightbox.node}
    </>
  );
}
