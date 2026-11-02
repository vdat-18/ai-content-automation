import { useMutation, useQuery } from "@tanstack/react-query";
import { Download, Film, Package } from "lucide-react";
import { Fragment, useMemo, useState } from "react";
import { EmptyState, PageHeader, Panel, SkeletonPage } from "../components/ui";
import { useI18n } from "../hooks/useI18n";
import { getJson, postJson } from "../services/http";

type Product = {
  product_id: string;
  title: string | null;
  url: string;
  price: { sale: string | null; original: string | null; discount: string | null };
  sold_count: number | string | null;
  rating: number | string | null;
  review_count: number | string | null;
  seller: { name: string | null; rating?: number | string | null };
  images: string[];
  categories?: string[];
  rating_distribution?: Record<string, string | number> | null;
  variants?: { sku_id: string; variant: string; stock: number | null; price: string | null }[];
  specifications?: Record<string, string>;
  description?: string;
  shipping?: { free_shipping?: boolean | null; delivery_name?: string | null };
  shop?: { followers_count?: number | string | null; on_sell_product_count?: number | string | null };
  raw_product_info?: { header_video?: { duration?: number; video_infos?: { main_url?: string; height?: number }[] }; desc_video?: unknown };
};

type MediaReport = { downloaded: number; duplicates: number; skipped: number; failed: number };

const API = "/api/v1/products";
const STARS = ["5", "4", "3", "2", "1"];
const toNumber = (value: number | string | null | undefined) => Number(String(value ?? 0).replace(/[.,]/g, "")) || 0;
const vnd = (value: string | null) => (value ? `${toNumber(value).toLocaleString("vi-VN")} ₫` : "-");
const hasVideo = (product: Product) => Boolean(product.raw_product_info?.header_video || product.raw_product_info?.desc_video);

export function ProductsPage() {
  const { t } = useI18n();
  const [search, setSearch] = useState("");
  const [onlyVideo, setOnlyVideo] = useState(false);
  const [minSold, setMinSold] = useState(0);
  const query = useQuery({ queryKey: ["products"], queryFn: ({ signal }) => getJson<Product[]>(API, signal), refetchInterval: 10000 });
  const [openId, setOpenId] = useState<string | null>(null);
  const media = useMutation({ mutationFn: () => postJson<MediaReport>(`${API}/media/download`) });

  const rows = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return (query.data ?? [])
      .filter((product) => (!needle || `${product.title} ${product.seller?.name}`.toLowerCase().includes(needle)))
      .filter((product) => !onlyVideo || hasVideo(product))
      .filter((product) => toNumber(product.sold_count) >= minSold)
      .sort((a, b) => toNumber(b.sold_count) - toNumber(a.sold_count));
  }, [query.data, search, onlyVideo, minSold]);

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
          <label><input type="checkbox" checked={onlyVideo} onChange={(event) => setOnlyVideo(event.target.checked)} /> {t("Has video")}</label>
          <label>{t("Min sold")} <input type="number" min={0} value={minSold} onChange={(event) => setMinSold(Number(event.target.value) || 0)} /></label>
          <span>{rows.length} / {query.data.length}</span>
        </div>
        {rows.length ? (
          <table className="products-table">
            <thead>
              <tr><th></th><th>{t("Product")}</th><th>{t("Price")}</th><th>{t("Discount")}</th><th>{t("Sold")}</th><th>{t("Rating")}</th><th>{t("Video")}</th></tr>
            </thead>
            <tbody>
              {rows.map((product) => (
                <Fragment key={product.product_id}>
                  <tr onClick={() => setOpenId(openId === product.product_id ? null : product.product_id)} style={{ cursor: "pointer" }}>
                    <td>{product.images[0] && <img src={product.images[0]} alt="" width={48} height={48} loading="lazy" />}</td>
                    <td><a href={product.url.split("?")[0]} target="_blank" rel="noreferrer" onClick={(event) => event.stopPropagation()}>{product.title}</a><small>{product.seller?.name}</small></td>
                    <td>{vnd(product.price.sale)}</td>
                    <td>{product.price.discount ?? ""}</td>
                    <td>{toNumber(product.sold_count).toLocaleString("vi-VN")}</td>
                    <td>{product.rating ?? "-"} ({toNumber(product.review_count).toLocaleString("vi-VN")})</td>
                    <td>{hasVideo(product) ? "✓" : ""}</td>
                  </tr>
                  {openId === product.product_id && (
                    <tr><td colSpan={7}><ProductDetail product={product} /></td></tr>
                  )}
                </Fragment>
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

function ProductDetail({ product }: { product: Product }) {
  const { t } = useI18n();
  const total = STARS.reduce((sum, star) => sum + toNumber(product.rating_distribution?.[star]), 0) || 1;
  const video = product.raw_product_info?.header_video;
  const videoUrl = video?.video_infos?.[0]?.main_url;
  return (
    <div className="product-detail">
      <p><strong>{t("Category")}:</strong> {product.categories?.join(" > ") || "-"}</p>
      <p>
        <strong>{t("Shop")}:</strong> {product.seller?.name} · {t("followers")} {toNumber(product.shop?.followers_count).toLocaleString("vi-VN")} · {t("products")} {toNumber(product.shop?.on_sell_product_count).toLocaleString("vi-VN")}
        {" · "}{product.shipping?.free_shipping ? t("Free shipping") : product.shipping?.delivery_name}
      </p>
      <div className="product-detail__images">
        {product.images.map((url) => <img key={url} src={url} alt="" width={72} height={72} loading="lazy" />)}
      </div>
      {videoUrl && <p><strong>{t("Video")}:</strong> {video?.duration}s · <a href={videoUrl} target="_blank" rel="noreferrer">{t("Open")}</a></p>}
      <p><strong>{t("Ratings by star")}:</strong></p>
      {STARS.map((star) => {
        const count = toNumber(product.rating_distribution?.[star]);
        return <div key={star}>{star}★ <progress value={count} max={total} /> {count.toLocaleString("vi-VN")}</div>;
      })}
      <p><strong>{t("Variants")} ({product.variants?.length ?? 0}):</strong></p>
      <ul>
        {(product.variants ?? []).slice(0, 30).map((variant) => (
          <li key={variant.sku_id}>{variant.variant || "-"} · {vnd(variant.price)} · {t("stock")} {variant.stock ?? "-"}</li>
        ))}
      </ul>
      <p><strong>{t("Specifications")}:</strong></p>
      <ul>
        {Object.entries(product.specifications ?? {}).map(([name, value]) => <li key={name}>{name}: {value}</li>)}
      </ul>
      <p><strong>{t("Description")}:</strong></p>
      <pre className="product-detail__description">{product.description}</pre>
    </div>
  );
}
