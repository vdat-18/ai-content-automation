import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowDownToLine, ArrowUpToLine, Download, Film, Loader2, Package, RotateCcw, Search, Trash2 } from "lucide-react";
import { useMemo, useRef, useState } from "react";
import { EmptyState, PageHeader, Panel, SkeletonPage } from "../components/ui";
import { useI18n } from "../hooks/useI18n";
import { deleteJson, getJson, postJson } from "../services/http";
import type { ReferenceProfile } from "./References";

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
  const listRef = useRef<HTMLDivElement>(null);
  const [sortKey, setSortKey] = useState<SortKey>("sold");
  const [minSold, setMinSold] = useState(0);
  const query = useQuery({ queryKey: ["products"], queryFn: ({ signal }) => getJson<Product[]>(API, signal), refetchInterval: 10000 });
  const media = useMutation({ mutationFn: () => postJson<MediaReport>(`${API}/media/download`) });
  const client = useQueryClient();
  // a selected product whose keyword is not made yet has a null type; poll until the queue is empty
  const selections = useQuery({
    queryKey: ["product-selections"],
    queryFn: ({ signal }) => getJson<Record<string, string | null>>(`${API}/selections`, signal),
    refetchInterval: (query) => (Object.values(query.state.data ?? {}).some((type) => !type) ? 3000 : false),
  });
  const selectErrors = useQuery({
    queryKey: ["select-errors"],
    queryFn: ({ signal }) => getJson<Record<string, string>>(`${API}/select-errors`, signal),
    refetchInterval: (query) => (Object.values(selections.data ?? {}).some((type) => !type) || Object.keys(query.state.data ?? {}).length ? 3000 : false),
  });
  const select = useMutation({
    mutationFn: ({ productId, regenerate }: { productId: string; regenerate: boolean }) =>
      postJson<SelectResult>(`${API}/${productId}/select?regenerate=${regenerate}`),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["product-selections"] });
      void client.invalidateQueries({ queryKey: ["select-errors"] });
      void client.invalidateQueries({ queryKey: ["reference-profiles"] });
    },
  });

  const remove = useMutation({
    mutationFn: (productId: string) => deleteJson<{ deleted: boolean }>(`${API}/${productId}`),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["products"] });
      void client.invalidateQueries({ queryKey: ["product-selections"] });
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
          <label className="pf-search">
            <Search size={15} aria-hidden="true" />
            <input type="search" placeholder={t("Search title or shop")} value={search} onChange={(event) => setSearch(event.target.value)} />
          </label>
          <label className="pf-field">
            <span>{t("Sort by")}</span>
            <select value={sortKey} onChange={(event) => setSortKey(event.target.value as SortKey)}>
              <option value="sold">{t("Sold")}</option>
              <option value="reviews">{t("Reviews")}</option>
              <option value="rating">{t("Rating")}</option>
            </select>
          </label>
          <label className="pf-field">
            <span>{t("Min sold")}</span>
            <input type="number" min={0} value={minSold} onChange={(event) => setMinSold(Number(event.target.value) || 0)} />
          </label>
          <span className="pf-count">{`${rows.length} / ${query.data.length}`}</span>
          <span className="pf-scroll">
            <button type="button" className="icon-button" aria-label={t("Scroll to top")} title={t("Scroll to top")} onClick={() => listRef.current?.scrollTo({ top: 0, behavior: "smooth" })}><ArrowUpToLine size={16} /></button>
            <button type="button" className="icon-button" aria-label={t("Scroll to bottom")} title={t("Scroll to bottom")} onClick={() => listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: "smooth" })}><ArrowDownToLine size={16} /></button>
          </span>
        </div>
        {rows.length ? (
          <div className="products-scroll" ref={listRef}>
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
                      <div className="pt-actions">
                        {(() => {
                          const picked = product.product_id in (selections.data ?? {});
                          const keyword = selections.data?.[product.product_id];
                          const failure = selectErrors.data?.[product.product_id];
                          const queue = () => select.mutate({ productId: product.product_id, regenerate: true });
                          if (!picked) {
                            return <button type="button" className="pt-button" onClick={() => select.mutate({ productId: product.product_id, regenerate: false })}>{t("Select for content")}</button>;
                          }
                          if (keyword) {
                            return (
                              <>
                                <span className="pt-keyword" title={t("Keyword used to find reference images")}>{keyword}</span>
                                <button type="button" className="pt-icon" aria-label={t("Regenerate keywords")} title={t("Regenerate keywords")} onClick={queue}><RotateCcw size={14} /></button>
                              </>
                            );
                          }
                          if (failure) {
                            return (
                              <>
                                <span className="pt-error" title={failure}>{t("Keyword failed")}</span>
                                <button type="button" className="pt-icon" aria-label={t("Try again")} title={`${failure} · ${t("Try again")}`} onClick={queue}><RotateCcw size={14} /></button>
                              </>
                            );
                          }
                          return <span className="pt-queued"><Loader2 size={13} className="pt-spin" aria-hidden="true" />{t("Making keyword…")}</span>;
                        })()}
                        <button
                          type="button"
                          className="pt-icon pt-icon--danger"
                          aria-label={t("Delete product")}
                          title={t("Delete product")}
                          disabled={remove.isPending}
                          onClick={() => {
                            if (window.confirm(t("Delete this product and its brief, images, clips and video? It will not be collected again."))) remove.mutate(product.product_id);
                          }}
                        ><Trash2 size={14} /></button>
                      </div>
                    </td>
                </tr>
              ))}
            </tbody>
          </table>
          </div>
        ) : (
          <EmptyState icon={<Package />} title="No products" text="Run the extension on TikTok Shop to collect products." />
        )}
      </Panel>
    </>
  );
}
