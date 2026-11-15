import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Chrome, Download, Package, Search, ShoppingBag, Sparkles, Trash2 } from "lucide-react";
import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Empty, ErrorNote, PageHead, Skeleton } from "../components/ui";
import { API, useBriefs, useProducts } from "../hooks/useStudio";
import { toNumber, vnd } from "../lib/studio";
import { deleteJson, getJson, postJson } from "../services/http";
import type { Product } from "../types/studio";

const SORTS = {
  sold: (product: Product) => toNumber(product.sold_count),
  rating: (product: Product) => Number(product.rating) || 0,
} as const;
type SortKey = keyof typeof SORTS;

export function ProductsPage() {
  const navigate = useNavigate();
  const client = useQueryClient();
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState<SortKey>("sold");
  const [category, setCategory] = useState("");
  const products = useProducts();
  const briefs = useBriefs();
  const refresh = () => {
    void client.invalidateQueries({ queryKey: ["product-selections"] });
  };
  const start = useMutation({
    mutationFn: (productId: string) => postJson(`${API}/${productId}/select`),
    onSuccess: (_data, productId) => {
      refresh();
      navigate(`/studio/${productId}`);
    },
  });
  const remove = useMutation({
    mutationFn: (productId: string) => deleteJson(`${API}/${productId}`),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["products"] });
      refresh();
    },
  });
  const waiting = useQuery({
    queryKey: ["products-waiting"],
    queryFn: ({ signal }) => getJson<string[]>(`${API}/queue?limit=100000`, signal),
    refetchInterval: 15000,
  });
  const media = useMutation({ mutationFn: () => postJson<{ downloaded: number }>(`${API}/media/download`) });

  const rows = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return (products.data ?? [])
      .filter((product) => !category || product.category === category)
      .filter((product) => !needle || `${product.title} ${product.seller?.name}`.toLowerCase().includes(needle))
      .sort((a, b) => SORTS[sort](b) - SORTS[sort](a));
  }, [products.data, search, sort, category]);
  const categories = useMemo(() => {
    const counts = new Map<string, number>();
    for (const product of products.data ?? []) if (product.category) counts.set(product.category, (counts.get(product.category) ?? 0) + 1);
    return [...counts.entries()].sort((a, b) => b[1] - a[1]);
  }, [products.data]);

  if (products.isLoading) return <div className="page"><Skeleton /></div>;
  if (products.error || !products.data) {
    return <div className="page"><ErrorNote error={products.error ?? new Error("No data")} /></div>;
  }
  const briefIds = new Set((briefs.data ?? []).map((record) => record.product_id));

  return (
    <div className="page">
      <PageHead
        title="Products"
        text="Products you collected from TikTok Shop. Pick one and make a video."
        actions={<a className="btn" href={`${API}/export?format=xlsx`}><Download size={16} aria-hidden="true" />Download Excel</a>}
      />
      <ErrorNote error={start.error ?? remove.error} />

      {products.data.length > 0 && (
        <div className="toolbar">
          <label className="sr-only" htmlFor="product-search">Search products</label>
          <div style={{ position: "relative" }}>
            <Search size={16} aria-hidden="true" style={{ position: "absolute", left: 12, top: 14, color: "var(--muted)" }} />
            <input id="product-search" className="input" style={{ paddingLeft: 36 }} type="search" placeholder="Search by name or shop" value={search} onChange={(event) => setSearch(event.target.value)} />
          </div>
          {categories.length > 0 && (
            <label className="row">
              <span className="muted small">Category</span>
              <select className="input" style={{ width: "auto" }} value={category} onChange={(event) => setCategory(event.target.value)}>
                <option value="">{`All (${products.data.length})`}</option>
                {categories.map(([name, count]) => <option key={name} value={name}>{`${name} (${count})`}</option>)}
              </select>
            </label>
          )}
          <label className="row">
            <span className="muted small">Sort by</span>
            <select className="input" style={{ width: "auto" }} value={sort} onChange={(event) => setSort(event.target.value as SortKey)}>
              <option value="sold">Most sold</option>
              <option value="rating">Best rated</option>
            </select>
          </label>
          <span className="muted small">{`${rows.length} of ${products.data.length}`}</span>
          {!!waiting.data?.length && <span className="muted small">{`${waiting.data.length} more waiting for their page to be read`}</span>}
        </div>
      )}

      {rows.length ? (
        <div className="product-grid">
          {rows.map((product) => {
            const hasVideoWork = briefIds.has(product.product_id);
            return (
              <article className="card product-card" key={product.product_id}>
                <div className="thumb">
                  {product.images[0] ? <img src={product.images[0]} alt="" loading="lazy" referrerPolicy="no-referrer" /> : <Package size={28} />}
                  {product.price.sale && <span className="price">{vnd(product.price.sale)}</span>}
                </div>
                <div className="body">
                  <a className="title" href={product.url.split("?")[0]} target="_blank" rel="noreferrer" title={product.title ?? ""}>{product.title}</a>
                  <span className="muted small">{product.seller?.name || "Unknown shop"}</span>
                  <span className="small">{`${toNumber(product.sold_count).toLocaleString("en-US")} sold`}{product.rating ? ` · ★ ${product.rating}` : ""}</span>
                  <div className="foot">
                    <button className="btn btn-primary btn-block" disabled={start.isPending} onClick={() => start.mutate(product.product_id)}>
                      {hasVideoWork ? "Open" : <><Sparkles size={16} aria-hidden="true" />Make a video</>}
                    </button>
                    <button
                      className="icon-button"
                      aria-label="Delete product"
                      title="Delete product"
                      disabled={remove.isPending}
                      onClick={() => {
                        if (window.confirm("Delete this product and everything made for it? It will not be collected again.")) remove.mutate(product.product_id);
                      }}
                    ><Trash2 size={16} /></button>
                  </div>
                </div>
              </article>
            );
          })}
        </div>
      ) : (
        <Empty icon={<Package size={32} aria-hidden="true" />} title={products.data.length ? "No product matches" : "No products yet"} text={products.data.length ? "Try a different search." : "Collect products from TikTok Shop in three steps."}>
          {!products.data.length && (
            <div className="steps-3">
              <div className="card"><span className="num">1</span><Chrome size={20} aria-hidden="true" /><strong>Install the Chrome extension</strong><span className="muted small">Add it to your Chrome browser.</span></div>
              <div className="card"><span className="num">2</span><ShoppingBag size={20} aria-hidden="true" /><strong>Browse TikTok Shop</strong><span className="muted small">Open the products you want to promote.</span></div>
              <div className="card"><span className="num">3</span><Sparkles size={20} aria-hidden="true" /><strong>Click Collect, then come back here</strong><span className="muted small">Your products appear on this page.</span></div>
            </div>
          )}
        </Empty>
      )}

      <details>
        <summary className="muted small" style={{ cursor: "pointer" }}>More tools</summary>
        <div className="row" style={{ marginTop: 12 }}>
          <a className="btn btn-sm" href={`${API}/export?format=json`}>Download JSON</a>
          <button className="btn btn-sm" disabled={media.isPending} onClick={() => media.mutate()}>{media.isPending ? "Saving pictures…" : "Save product pictures to the server"}</button>
          {media.data && <span className="muted small">{`${media.data.downloaded} new pictures saved`}</span>}
        </div>
      </details>
    </div>
  );
}
