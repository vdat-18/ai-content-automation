import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Package, X } from "lucide-react";
import { useState } from "react";
import { EmptyState, PageHeader, Panel } from "../components/ui";
import { useI18n } from "../hooks/useI18n";
import { useLightbox } from "../hooks/useLightbox";
import { deleteJson, getJson, postJson, putJson } from "../services/http";

export type ReferenceProfile = { product_type: string; keywords: string[]; status: string };
type Screening = {
  usable: boolean;
  description?: string;
  scene_description?: string;
  reject_reason?: string | null;
  setting?: string | null;
  surface_and_props?: string[] | null;
  lighting?: string | null;
  color_palette?: string[] | null;
  style?: string[] | null;
  camera?: string | null;
  people?: string | null;
  placement?: string | null;
  suits?: string[] | null;
  motion_ideas?: string[] | null;
  quality?: number | null;
};

const DETAILS: { key: keyof Screening; label: string }[] = [
  { key: "setting", label: "Setting" },
  { key: "surface_and_props", label: "Props" },
  { key: "lighting", label: "Light" },
  { key: "color_palette", label: "Colors" },
  { key: "style", label: "Style" },
  { key: "camera", label: "Camera" },
  { key: "people", label: "People" },
  { key: "placement", label: "Product spot" },
  { key: "suits", label: "Fits shots" },
  { key: "motion_ideas", label: "Motion ideas" },
];
const detailText = (value: unknown) => (Array.isArray(value) ? value.join(", ") : String(value ?? ""));
type ReferenceImage = { image_id: string; product_type: string; query: string; image_url: string; pin_url: string; title: string; status: string; screening: Screening | null };
type ScreenReport = { reviewed: number; usable: number; rejected: number; failed: number };

const API = "/api/v1/products";

export function ReferencesPage() {
  return (
    <>
      <PageHeader
        eyebrow="Affiliate content"
        title="References"
        description="Pinterest search keywords and the reference images crawled with them."
      />
      <ReferenceProfiles />
      <ReferenceImages />
    </>
  );
}

function ReferenceProfiles() {
  const { t } = useI18n();
  const client = useQueryClient();
  const query = useQuery({ queryKey: ["reference-profiles"], queryFn: ({ signal }) => getJson<ReferenceProfile[]>(`${API}/reference-profiles`, signal) });
  const save = useMutation({
    mutationFn: (profile: ReferenceProfile) => putJson<ReferenceProfile>(`${API}/reference-profiles/${encodeURIComponent(profile.product_type)}`, profile),
    onSuccess: () => client.invalidateQueries({ queryKey: ["reference-profiles"] }),
  });
  if (!query.data?.length) return null;
  const lines = (text: string) => text.split("\n").map((line) => line.trim()).filter(Boolean);
  return (
    <Panel>
      <div className="panel-header">
        <div>
          <h2>{t("Pinterest search keywords")}</h2>
          <p>{t("Review the keywords for each product type, then approve them to start crawling.")}</p>
        </div>
      </div>
      {query.data.map((profile) => (
        <form
          key={`${profile.product_type}-${profile.keywords.join("|")}-${profile.status}`}
          className="reference-profile"
          onSubmit={(event) => {
            event.preventDefault();
            const data = new FormData(event.currentTarget);
            save.mutate({
              product_type: profile.product_type,
              keywords: lines(String(data.get("keywords"))),
              status: "approved",
            });
          }}
        >
          <div className="reference-profile__head">
            <strong>{profile.product_type}</strong>
            <span className={`badge badge--${profile.status === "approved" ? "success" : "warning"}`}>{profile.status}</span>
            <span className="reference-profile__count">{`${profile.keywords.length} ${t("keywords")}`}</span>
          </div>
          <div className="reference-profile__fields">
            <label>
              <span>{t("Keywords (one per line)")}</span>
              <textarea name="keywords" rows={Math.min(Math.max(profile.keywords.length + 1, 4), 9)} defaultValue={profile.keywords.join("\n")} />
            </label>
          </div>
          <div className="reference-profile__actions">
            <button className="primary-button" type="submit" disabled={save.isPending}>{t("Save and approve")}</button>
          </div>
        </form>
      ))}
    </Panel>
  );
}

function ReferenceImages() {
  const { t } = useI18n();
  const lightbox = useLightbox();
  const client = useQueryClient();
  const [productType, setProductType] = useState("");
  const [status, setStatus] = useState("live");
  const params = new URLSearchParams();
  if (productType) params.set("product_type", productType);
  if (status) params.set("status", status);
  const profiles = useQuery({ queryKey: ["reference-profiles"], queryFn: ({ signal }) => getJson<ReferenceProfile[]>(`${API}/reference-profiles`, signal) });
  const images = useQuery({
    queryKey: ["reference-images", productType, status],
    queryFn: ({ signal }) => getJson<ReferenceImage[]>(`${API}/reference-images?${params}`, signal),
    refetchInterval: 10000,
  });
  const remove = useMutation({
    mutationFn: (imageId: string) => deleteJson(`${API}/reference-images/${imageId}`),
    onSuccess: () => client.invalidateQueries({ queryKey: ["reference-images"] }),
  });
  const pending = useQuery({
    queryKey: ["reference-images", "pending"],
    queryFn: ({ signal }) => getJson<ReferenceImage[]>(`${API}/reference-images?status=pending`, signal),
    refetchInterval: 10000,
  });
  const recheck = useMutation({
    mutationFn: () => postJson<{ checked: number; marked_duplicate: number }>(`${API}/reference-images/recheck-duplicates`),
    onSuccess: () => client.invalidateQueries({ queryKey: ["reference-images"] }),
  });
  // a few images per request, so no request runs into the server's time limit; repeat until none is left
  const [described, setDescribed] = useState<{ done: number; failed: number; left: number } | null>(null);
  const redescribe = useMutation({
    mutationFn: async () => {
      let done = 0;
      let failed = 0;
      for (;;) {
        const batch = await postJson<{ described: number; failed: number; left: number }>(`${API}/reference-images/redescribe?limit=4`);
        done += batch.described;
        failed += batch.failed;
        setDescribed({ done, failed, left: batch.left });
        void client.invalidateQueries({ queryKey: ["reference-images"] });
        if (!batch.described || batch.left <= failed) return { done, failed };
      }
    },
  });
  const screen = useMutation({
    mutationFn: () => postJson<ScreenReport>(`${API}/reference-images/screen?limit=30`),
    onSuccess: () => client.invalidateQueries({ queryKey: ["reference-images"] }),
  });
  if (!profiles.data?.length) return null;
  return (
    <Panel>
      <div className="panel-header">
        <div>
          <h2>{t("Reference images")}</h2>
          <p>{t("Images crawled from Pinterest that Gemini accepted as scenes to borrow, newest first. Press the ✕ on a picture to remove the ones you do not want.")}</p>
        </div>
        <div className="reference-review">
          {(images.data ?? []).some((image) => image.screening && !image.screening.setting) && (
            <button className="secondary-button" disabled={redescribe.isPending} onClick={() => redescribe.mutate()} title={t("Ask the vision model for a full description of images reviewed before details were saved")}>
              {redescribe.isPending ? t("Describing…") : t("Describe in detail")}
            </button>
          )}
          <button className="secondary-button" disabled={recheck.isPending} onClick={() => recheck.mutate()} title={t("Mark images that look like an earlier one (80% similar or more) as duplicates")}>
            {recheck.isPending ? t("Checking…") : t("Re-check duplicates")}
          </button>
          <button className="primary-button" disabled={screen.isPending || !pending.data?.length} onClick={() => screen.mutate()}>
            {screen.isPending ? t("Reviewing…") : `${t("Review pending")} (${pending.data?.length ?? 0})`}
          </button>
        </div>
      </div>
      {screen.data && <p role="status">{`${t("Reviewed")} ${screen.data.reviewed} · ${t("usable")} ${screen.data.usable} · ${t("rejected")} ${screen.data.rejected} · ${t("failed")} ${screen.data.failed}`}</p>}
      {screen.error && <p role="alert">{screen.error.message}</p>}
      {recheck.data && <p role="status">{`${t("Checked")} ${recheck.data.checked} · ${t("new duplicates")} ${recheck.data.marked_duplicate}`}</p>}
      {recheck.error && <p role="alert">{recheck.error.message}</p>}
      {described && <p role="status">{`${t("Described")} ${described.done} · ${t("failed")} ${described.failed} · ${t("left")} ${described.left}`}</p>}
      {redescribe.error && <p role="alert">{redescribe.error.message}</p>}
      <div className="products-filters">
        <label className="pf-field">
          <span>{t("Product type")}</span>
          <select value={productType} onChange={(event) => setProductType(event.target.value)}>
            <option value="">{t("All")}</option>
            {profiles.data.map((profile) => <option key={profile.product_type} value={profile.product_type}>{profile.product_type}</option>)}
          </select>
        </label>
        <label className="pf-field">
          <span>{t("Status")}</span>
          <select value={status} onChange={(event) => setStatus(event.target.value)}>
            <option value="live">{t("Live")}</option>
            <option value="rejected">{t("Rejected by Gemini")}</option>
            <option value="removed">{t("Removed")}</option>
            <option value="duplicate">{t("Duplicates")}</option>
            <option value="check_failed">{t("Duplicate check failed")}</option>
            <option value="">{t("All")}</option>
          </select>
        </label>
        <span className="pf-count">{`${images.data?.length ?? 0} ${t("images")}`}</span>
      </div>
      {images.data?.length ? (
        <div className="reference-grid">
          {images.data.map((image, index) => (
            <figure key={image.image_id} className="reference-card">
              <img
                src={image.image_url}
                alt={image.title}
                loading="lazy"
                referrerPolicy="no-referrer"
                {...lightbox.zoom(
                  images.data.map((item) => ({ src: item.image_url, label: item.title, href: `https://www.pinterest.com${item.pin_url}` })),
                  index,
                )}
              />
              {image.status !== "removed" && (
                <button type="button" className="reference-card__remove" aria-label={t("Remove")} title={t("Remove")} disabled={remove.isPending} onClick={() => remove.mutate(image.image_id)}>
                  <X size={14} />
                </button>
              )}
              <figcaption>
                <span className="reference-card__query">{image.query}</span>
                {image.screening && (
                  <small title={image.screening.description ?? image.screening.scene_description}>
                    {`${image.screening.usable ? "" : "✕ "}${image.screening.description ?? image.screening.scene_description ?? ""}`}
                  </small>
                )}
                {image.screening && DETAILS.some(({ key }) => image.screening?.[key]) && (
                  <details className="reference-card__details">
                    <summary>{image.screening.quality ? `${t("Details")} · ${image.screening.quality}/5` : t("Details")}</summary>
                    <dl>
                      {DETAILS.filter(({ key }) => image.screening?.[key]).map(({ key, label }) => (
                        <div key={key}>
                          <dt>{t(label)}</dt>
                          <dd>{detailText(image.screening?.[key])}</dd>
                        </div>
                      ))}
                      {image.screening.reject_reason && <div><dt>{t("Rejected because")}</dt><dd>{image.screening.reject_reason}</dd></div>}
                    </dl>
                  </details>
                )}
              </figcaption>
            </figure>
          ))}
        </div>
      ) : (
        <EmptyState icon={<Package />} title="No reference images" text="Approve keywords, then run the Pinterest crawl from the extension." />
      )}
    </Panel>
  );
}
