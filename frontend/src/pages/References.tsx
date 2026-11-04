import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Package } from "lucide-react";
import { useState } from "react";
import { EmptyState, PageHeader, Panel } from "../components/ui";
import { useI18n } from "../hooks/useI18n";
import { deleteJson, getJson, postJson, putJson } from "../services/http";

export type ReferenceProfile = { product_type: string; keywords: string[]; status: string };
type Screening = { usable: boolean; description?: string; scene_description?: string };
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
          <p>{t("Images crawled from Pinterest that Gemini accepted as scenes to borrow, newest first. Remove the ones you do not want.")}</p>
        </div>
        <div className="reference-review">
          <button className="primary-button" disabled={screen.isPending || !pending.data?.length} onClick={() => screen.mutate()}>
            {screen.isPending ? t("Reviewing…") : `${t("Review pending")} (${pending.data?.length ?? 0})`}
          </button>
        </div>
      </div>
      {screen.data && <p role="status">{`${t("Reviewed")} ${screen.data.reviewed} · ${t("usable")} ${screen.data.usable} · ${t("rejected")} ${screen.data.rejected} · ${t("failed")} ${screen.data.failed}`}</p>}
      {screen.error && <p role="alert">{screen.error.message}</p>}
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
            <option value="">{t("All")}</option>
          </select>
        </label>
        <span className="pf-count">{`${images.data?.length ?? 0} ${t("images")}`}</span>
      </div>
      {images.data?.length ? (
        <div className="reference-grid">
          {images.data.map((image) => (
            <figure key={image.image_id} className="reference-card">
              <a href={`https://www.pinterest.com${image.pin_url}`} target="_blank" rel="noreferrer">
                <img src={image.image_url} alt={image.title} loading="lazy" referrerPolicy="no-referrer" />
              </a>
              <figcaption>
                <span className="reference-card__query">{image.query}</span>
                {image.screening && (
                  <small title={image.screening.description ?? image.screening.scene_description}>
                    {`${image.screening.usable ? "" : "✕ "}${image.screening.description ?? image.screening.scene_description ?? ""}`}
                  </small>
                )}
                <div>
                  <button type="button" className="pt-button" disabled={remove.isPending || image.status === "removed"} onClick={() => remove.mutate(image.image_id)}>{t("Remove")}</button>
                </div>
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
