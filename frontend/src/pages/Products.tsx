import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, Film, Package } from "lucide-react";
import { useMemo, useState } from "react";
import { EmptyState, PageHeader, Panel, SkeletonPage } from "../components/ui";
import { useI18n } from "../hooks/useI18n";
import { getJson, postJson, putJson } from "../services/http";

type Product = {
  product_id: string;
  title: string | null;
  url: string;
  price: { sale: string | null };
  sold_count: number | string | null;
  rating: number | string | null;
  review_count: number | string | null;
  seller: { name: string | null; rating?: number | string | null };
  images: string[];
};

type MediaReport = { downloaded: number; duplicates: number; skipped: number; failed: number };
type SelectResult = { product_id: string; profile: ReferenceProfile | null; error: string | null };
type ReferenceProfile = { product_type: string; keywords: string[]; exclude_keywords: string[]; status: string };

const API = "/api/v1/products";
const toNumber = (value: number | string | null | undefined) => Number(String(value ?? 0).replace(/[.,]/g, "")) || 0;
const vnd = (value: string | null) => (value ? `${toNumber(value).toLocaleString("vi-VN")} ₫` : "-");
const SORTS = {
  sold: (product: Product) => toNumber(product.sold_count),
  reviews: (product: Product) => toNumber(product.review_count),
  rating: (product: Product) => Number(product.rating) || 0,
} as const;
type SortKey = keyof typeof SORTS;

export function ProductsPage() {
  const { t } = useI18n();
  const [search, setSearch] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("sold");
  const [minSold, setMinSold] = useState(0);
  const query = useQuery({ queryKey: ["products"], queryFn: ({ signal }) => getJson<Product[]>(API, signal), refetchInterval: 10000 });
  const media = useMutation({ mutationFn: () => postJson<MediaReport>(`${API}/media/download`) });
  const client = useQueryClient();
  const selections = useQuery({ queryKey: ["product-selections"], queryFn: ({ signal }) => getJson<Record<string, string | null>>(`${API}/selections`, signal) });
  const select = useMutation({
    mutationFn: ({ productId, regenerate }: { productId: string; regenerate: boolean }) =>
      postJson<SelectResult>(`${API}/${productId}/select?regenerate=${regenerate}`),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["product-selections"] });
      void client.invalidateQueries({ queryKey: ["reference-profiles"] });
    },
  });

  const rows = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return (query.data ?? [])
      .filter((product) => (!needle || `${product.title} ${product.seller?.name}`.toLowerCase().includes(needle)))
      .filter((product) => toNumber(product.sold_count) >= minSold)
      .sort((a, b) => SORTS[sortKey](b) - SORTS[sortKey](a));
  }, [query.data, search, sortKey, minSold]);

  if (query.isLoading) return <SkeletonPage />;
  if (query.error || !query.data) {
    return <EmptyState icon={<Package />} title="Could not load products" text={query.error?.message ?? "The product service returned no data."} />;
  }

  return (
    <>
      <PageHeader
        eyebrow="Affiliate content"
        title="Products"
        description="Products collected from TikTok Shop by the browser extension."
        actions={
          <>
            <a className="secondary-button" href={`${API}/export?format=xlsx`}><Download size={15} /> Excel</a>
            <a className="secondary-button" href={`${API}/export?format=json`}><Download size={15} /> JSON</a>
            <button className="secondary-button" disabled={media.isPending} onClick={() => media.mutate()}>
              <Film size={15} /> {media.isPending ? t("Downloading…") : t("Download media")}
            </button>
          </>
        }
      />
      {media.data && (
        <p role="status">{`${t("New")} ${media.data.downloaded} · ${t("duplicates")} ${media.data.duplicates} · ${t("already saved")} ${media.data.skipped} · ${t("failed")} ${media.data.failed}`}</p>
      )}
      {media.error && <p role="alert">{media.error.message}</p>}
      {select.data?.error && <p role="alert">{select.data.error}</p>}
      {select.error && <p role="alert">{select.error.message}</p>}
      <Panel>
        <div className="products-filters">
          <input type="search" placeholder={t("Search title or shop")} value={search} onChange={(event) => setSearch(event.target.value)} />
          <label>{t("Sort by")}{" "}
            <select value={sortKey} onChange={(event) => setSortKey(event.target.value as SortKey)}>
              <option value="sold">{t("Sold")}</option>
              <option value="reviews">{t("Reviews")}</option>
              <option value="rating">{t("Rating")}</option>
            </select>
          </label>
          <label>{t("Min sold")} <input type="number" min={0} value={minSold} onChange={(event) => setMinSold(Number(event.target.value) || 0)} /></label>
          <span>{rows.length} / {query.data.length}</span>
        </div>
        {rows.length ? (
          <table className="products-table">
            <thead>
              <tr><th></th><th>{t("Product")}</th><th>{t("Price")}</th><th>{t("Sold")}</th><th>{t("Reviews")}</th><th>{t("Rating")}</th><th></th></tr>
            </thead>
            <tbody>
              {rows.map((product) => (
                <tr key={product.product_id}>
                    <td>{product.images[0] && <img src={product.images[0]} alt="" width={48} height={48} loading="lazy" />}</td>
                    <td><a href={product.url.split("?")[0]} target="_blank" rel="noreferrer">{product.title}</a><small>{product.seller?.name}</small></td>
                    <td>{vnd(product.price.sale)}</td>
                    <td>{toNumber(product.sold_count).toLocaleString("vi-VN")}</td>
                    <td>{toNumber(product.review_count).toLocaleString("vi-VN")}</td>
                    <td>{product.rating ?? "-"}</td>
                    <td>
                      {product.product_id in (selections.data ?? {}) ? (
                        <>
                          <span className="badge badge--success">{selections.data?.[product.product_id] || t("Selected")}</span>
                          <button className="secondary-button" disabled={select.isPending} onClick={() => select.mutate({ productId: product.product_id, regenerate: true })}>{t("Regenerate keywords")}</button>
                        </>
                      ) : (
                        <button className="secondary-button" disabled={select.isPending} onClick={() => select.mutate({ productId: product.product_id, regenerate: false })}>{t("Select for content")}</button>
                      )}
                    </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <EmptyState icon={<Package />} title="No products" text="Run the extension on TikTok Shop to collect products." />
        )}
      </Panel>
      <ReferenceProfiles />
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
              exclude_keywords: lines(String(data.get("exclude"))),
              status: "approved",
            });
          }}
        >
          <div className="reference-profile__head">
            <strong>{profile.product_type}</strong>
            <span className={`badge badge--${profile.status === "approved" ? "success" : "warning"}`}>{profile.status}</span>
          </div>
          <div className="reference-profile__fields">
            <label>
              <span>{t("Keywords (one per line)")}</span>
              <textarea name="keywords" rows={5} defaultValue={profile.keywords.join("\n")} />
            </label>
            <label>
              <span>{t("Exclude words")}</span>
              <textarea name="exclude" rows={5} defaultValue={profile.exclude_keywords.join("\n")} />
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
