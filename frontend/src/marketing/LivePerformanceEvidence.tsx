import { useState } from "react";
import { Link2Off, PackageSearch } from "lucide-react";
import { Link } from "react-router-dom";

import { Badge, EmptyState, Panel, PanelHeader } from "../components/ui";
import { useSourcePerformanceCandidates } from "../hooks/useDataSources";
import type { ProductPerformanceCandidate } from "../types/pilotApi";

const PERFORMANCE_LIST_LIMIT = 50;

export function LivePerformanceEvidence() {
  const [brand, setBrand] = useState<string>();
  const [selectedProductKey, setSelectedProductKey] = useState<string>();
  const candidates = useSourcePerformanceCandidates({ brand, limit: PERFORMANCE_LIST_LIMIT });
  const evidence = candidates.data;
  const products = evidence?.products ?? [];
  const selectedProduct = products.find((item) => productKey(item) === selectedProductKey) ?? products[0];

  return <div className="mkt-pilot-layout">
    <Panel className="performance-live-evidence">
      <PanelHeader
        title="Live SKU performance evidence"
        meta="Current Google Ads product metrics mapped to Shopify SKU. This screen is read only."
        action={<Link className="text-link" to="/data-sources">Source health →</Link>}
      />
      {candidates.error && <p className="form-error" role="alert">{candidates.error.message}</p>}
      {candidates.isLoading ? <p className="muted-copy">Loading current source snapshots…</p> : !evidence || !evidence.product_total ? <EmptyState icon={<PackageSearch />} title="No SKU performance evidence" text="Sync the Google Ads and Shopify sources before reviewing SKU metrics." /> : <>
        <div className="mkt-stats mkt-stats--compact performance-live-stats">
          <article><span>Product candidates</span><strong>{formatInteger(evidence.product_total)}</strong><small>Google Ads product items in this view</small></article>
          <article><span>Mapped to SKU</span><strong>{formatInteger(evidence.mapped_sku_total)}</strong><small>Matched through the latest Shopify catalog</small></article>
          <article><span>Meta Ads candidates</span><strong>{formatInteger(evidence.creative_total)}</strong><small>Ad-level evidence in the selected brand</small></article>
          <article><span>Creative files linked</span><strong>{formatInteger(evidence.creative_total - evidence.unlinked_creative_total)}</strong><small>Requires exact Lark creative/version mapping</small></article>
        </div>
        <div className="mkt-filterbar performance-live-filter">
          <label>Brand <select aria-label="Performance brand" value={brand ?? "all"} onChange={(event) => { setBrand(event.target.value === "all" ? undefined : event.target.value); setSelectedProductKey(undefined); }}><option value="all">All brands</option>{evidence.brands.map((item) => <option key={item} value={item}>{item}</option>)}</select></label>
          <p className="mkt-muted">Showing the top {Math.min(PERFORMANCE_LIST_LIMIT, evidence.product_total)} product items ranked by conversion value.</p>
        </div>
        <div className="mkt-filter-note"><strong>Evidence only.</strong><span>There is no approved attribution policy or business rule set on this data yet, so this page does not create a Performance decision or Creative request.</span></div>
        <div className="mkt-table-scroll">
          <table className="mkt-table performance-live-table">
            <thead><tr><th>SKU</th><th>Conversions</th><th>Conversion value</th><th>ROAS</th><th>Spend</th><th>Window</th></tr></thead>
            <tbody>{products.map((item) => <tr className={selectedProduct && productKey(item) === productKey(selectedProduct) ? "is-selected" : undefined} key={productKey(item)}>
              <td><button className="text-link mkt-record-title" onClick={() => setSelectedProductKey(productKey(item))}>{item.sku_id ?? item.sku_mapping_status}</button><small>{item.brand ?? item.source_id}</small><code>{item.product_item_id}</code></td>
              <td>{metricText(item.conversions)}</td>
              <td>{moneyText(item.conversion_value, item.currency)}</td>
              <td>{metricText(item.roas)}</td>
              <td>{moneyText(item.spend, item.currency)}</td>
              <td>{windowText(item.window_start, item.window_end)}</td>
            </tr>)}</tbody>
          </table>
        </div>
      </>}
    </Panel>
    {selectedProduct && <ProductEvidenceDetail item={selectedProduct} />}
    <Panel className="performance-live-evidence">
      <PanelHeader title="Meta Ads evidence awaiting creative lineage" meta="Ad metrics are available, but they are not attached to an exact Creative file or version." />
      {!evidence || !evidence.creative_total ? <p className="muted-copy">No Meta Ads snapshot is available for this brand.</p> : <>
        <div className="mkt-filter-note performance-live-lineage"><Link2Off size={16} /><span>{formatInteger(evidence.unlinked_creative_total)} Meta Ads records are unlinked. Do not use these rows to conclude that a specific file, image, or video performed well.</span></div>
        <div className="mkt-table-scroll">
          <table className="mkt-table performance-live-table">
            <thead><tr><th>Ad</th><th>Purchases</th><th>Purchase value</th><th>ROAS</th><th>Creative lineage</th><th>Window</th></tr></thead>
            <tbody>{evidence.creatives.map((item) => <tr key={`${item.source_id}-${item.ad_id}`}>
              <td><strong>{item.ad_name ?? item.ad_id}</strong><small>{item.brand ?? item.source_id}</small></td>
              <td>{metricText(item.purchases)}</td>
              <td>{moneyText(item.purchase_conversion_value, item.currency)}</td>
              <td>{metricText(item.roas)}</td>
              <td><Badge tone="warning">{item.creative_lineage_status}</Badge></td>
              <td>{item.window_label}</td>
            </tr>)}</tbody>
          </table>
        </div>
      </>}
    </Panel>
  </div>;
}

function ProductEvidenceDetail({ item }: { item: ProductPerformanceCandidate }) {
  return <Panel className="performance-live-detail">
    <PanelHeader title={item.sku_id ?? item.product_item_id} meta="Selected SKU evidence" />
    <dl className="mkt-facts mkt-facts--columns">
      <div><dt>Brand</dt><dd>{item.brand ?? "Unknown"}</dd></div>
      <div><dt>SKU mapping</dt><dd>{item.sku_mapping_status}</dd></div>
      <div><dt>Conversions</dt><dd>{metricText(item.conversions)}</dd></div>
      <div><dt>Conversion value</dt><dd>{moneyText(item.conversion_value, item.currency)}</dd></div>
      <div><dt>ROAS</dt><dd>{metricText(item.roas)}</dd></div>
      <div><dt>Source window</dt><dd>{windowText(item.window_start, item.window_end)}</dd></div>
    </dl>
    <p className="mkt-muted">This is a Google Ads product-level observation. Its conversion attribution and data window remain attached to the source; it is not an order count or an exact Creative result.</p>
  </Panel>;
}

function productKey(item: ProductPerformanceCandidate): string {
  return `${item.source_id}:${item.product_item_id}`;
}

function formatInteger(value: number): string {
  return new Intl.NumberFormat("en-US").format(value);
}

function metricText(value: string | null): string {
  if (value === null) return "—";
  const number = Number(value);
  return Number.isFinite(number) ? new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 }).format(number) : value;
}

function moneyText(value: string | null, currency: string | null): string {
  if (value === null) return "—";
  const number = Number(value);
  if (!currency || !Number.isFinite(number)) return value;
  return new Intl.NumberFormat("en-US", { style: "currency", currency, maximumFractionDigits: 2 }).format(number);
}

function windowText(start: string | null, end: string | null): string {
  return [start, end].filter(Boolean).join(" – ") || "Configured window";
}
