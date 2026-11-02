import { useMutation, useQuery } from "@tanstack/react-query";
import { Download, Film, Package } from "lucide-react";
import { useMemo, useState } from "react";
import { EmptyState, PageHeader, Panel, SkeletonPage } from "../components/ui";
import { useI18n } from "../hooks/useI18n";
import { getJson, postJson } from "../services/http";

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

const API = "/api/v1/products";
const toNumber = (value: number | string | null | undefined) => Number(String(value ?? 0).replace(/[.,]/g, "")) || 0;
const vnd = (value: string | null) => (value ? `${toNumber(value).toLocaleString("vi-VN")} ₫` : "-");
const revenue = (product: Product) => toNumber(product.price.sale) * toNumber(product.sold_count);
const SORTS = {
  sold: (product: Product) => toNumber(product.sold_count),
  reviews: (product: Product) => toNumber(product.review_count),
  rating: (product: Product) => Number(product.rating) || 0,
  revenue,
} as const;
type SortKey = keyof typeof SORTS;

export function ProductsPage() {
  const { t } = useI18n();
  const [search, setSearch] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("sold");
  const [minSold, setMinSold] = useState(0);
  const query = useQuery({ queryKey: ["products"], queryFn: ({ signal }) => getJson<Product[]>(API, signal), refetchInterval: 10000 });
  const media = useMutation({ mutationFn: () => postJson<MediaReport>(`${API}/media/download`) });

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
      <Panel>
        <div className="products-filters">
          <input type="search" placeholder={t("Search title or shop")} value={search} onChange={(event) => setSearch(event.target.value)} />
          <label>{t("Sort by")}{" "}
            <select value={sortKey} onChange={(event) => setSortKey(event.target.value as SortKey)}>
              <option value="sold">{t("Sold")}</option>
              <option value="reviews">{t("Reviews")}</option>
              <option value="rating">{t("Rating")}</option>
              <option value="revenue">{t("Est. revenue")}</option>
            </select>
          </label>
          <label>{t("Min sold")} <input type="number" min={0} value={minSold} onChange={(event) => setMinSold(Number(event.target.value) || 0)} /></label>
          <span>{rows.length} / {query.data.length}</span>
        </div>
        {rows.length ? (
          <table className="products-table">
            <thead>
              <tr><th></th><th>{t("Product")}</th><th>{t("Price")}</th><th>{t("Sold")}</th><th>{t("Reviews")}</th><th>{t("Rating")}</th><th>{t("Est. revenue")}</th></tr>
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
                    <td>{revenue(product).toLocaleString("vi-VN")} ₫</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <EmptyState icon={<Package />} title="No products" text="Run the extension on TikTok Shop to collect products." />
        )}
      </Panel>
    </>
  );
}
