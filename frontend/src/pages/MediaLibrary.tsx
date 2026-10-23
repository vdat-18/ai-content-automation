import { useEffect, useMemo, useState } from "react";
import { Download, Image as ImageIcon, Plus, RefreshCw, RotateCcw, Search, Trash2, Video } from "lucide-react";
import { Link } from "react-router-dom";

import { Badge, EmptyState, PageHeader, SkeletonPage, StatusBadge } from "../components/ui";
import { useI18n } from "../hooks/useI18n";
import { marketingErrorMessage } from "../services/http";
import { pilotApi } from "../services/pilotApi";
import type {
  MarketingCreativeAutomationDetail,
  MarketingCreativeAutomationItem,
} from "../types/pilotApi";

type LibraryFilter = "all" | "image" | "video";
const HIDDEN_MEDIA_OUTPUTS_KEY = "aic-hidden-media-output-ids";
type CreativeProductionVersion = MarketingCreativeAutomationDetail["production_versions"][number];
type LibraryItem = {
  id: string;
  kind: "image" | "video";
  createdAt: string;
  request: MarketingCreativeAutomationItem;
  detail: MarketingCreativeAutomationDetail;
  version: CreativeProductionVersion;
};

export function MediaLibraryPage() {
  const { language, t } = useI18n();
  const [creativeOutputs, setCreativeOutputs] = useState<LibraryItem[]>([]);
  const [filter, setFilter] = useState<LibraryFilter>("all");
  const [query, setQuery] = useState("");
  const [selectedId, setSelectedId] = useState("");
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [hiddenOutputIds, setHiddenOutputIds] = useState<string[]>(readHiddenMediaOutputs);
  const [error, setError] = useState("");

  const load = async (signal?: AbortSignal, refresh = false) => {
    if (refresh) setRefreshing(true);
    setError("");
    try {
      const automationResponse = await pilotApi.marketingCreativeAutomations(signal);
      const creativeDetails = await Promise.allSettled(
        automationResponse.items
          .filter((request) => request.asset_count > 0)
          .map(async (request) => ({
            request,
            detail: await pilotApi.marketingCreativeAutomation(request.request_id, signal),
          })),
      );
      setCreativeOutputs(creativeDetails.flatMap((result) => {
        if (result.status !== "fulfilled") return [];
        const { request, detail } = result.value;
        return detail.production_versions
          .filter((version) => version.success && Boolean(version.artifact_web_url))
          .map((version): LibraryItem => ({
            id: `creative:${request.request_id}:${version.asset_version_id}`,
            kind: version.media_kind,
            createdAt: detail.updated_at,
            request,
            detail,
            version,
          }));
      }));
    } catch (reason: unknown) {
      if (!signal?.aborted) setError(marketingErrorMessage(reason));
    } finally {
      if (!signal?.aborted) {
        setLoading(false);
        setRefreshing(false);
      }
    }
  };

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, []);

  const allItems = useMemo<LibraryItem[]>(
    () => [...creativeOutputs].sort((left, right) => Date.parse(right.createdAt) - Date.parse(left.createdAt)),
    [creativeOutputs],
  );
  const items = useMemo(
    () => allItems.filter((item) => !hiddenOutputIds.includes(item.id)),
    [allItems, hiddenOutputIds],
  );

  const filteredItems = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase();
    return items.filter((item) => {
      if (filter !== "all" && item.kind !== filter) return false;
      if (!normalizedQuery) return true;
      return librarySearchText(item).toLowerCase().includes(normalizedQuery);
    });
  }, [filter, items, query]);

  const selected = filteredItems.find((item) => item.id === selectedId)
    ?? filteredItems.find((item) => outputUrl(item))
    ?? filteredItems[0]
    ?? null;
  const outputCount = items.filter((item) => outputUrl(item)).length;
  const dateLocale = language === "vi" ? "vi-VN" : "en-US";

  const removeItem = (item: LibraryItem) => {
    if (!window.confirm(t("Remove this output from Media Library? The audit record will be kept and can be restored."))) return;
    saveHiddenMediaOutputs([...new Set([...hiddenOutputIds, item.id])], setHiddenOutputIds);
    if (selectedId === item.id) setSelectedId("");
  };

  if (loading) return <SkeletonPage />;

  return <>
    <PageHeader
      eyebrow="Saved outputs"
      title="Generated media"
      description="Open generated images and videos with their original request, version and review status."
      variant="library"
      actions={<div className="media-library-header-actions">
        <Badge tone="violet">{outputCount} {t("saved outputs")}</Badge>
        {hiddenOutputIds.length > 0 && <button
          className="secondary-button"
          type="button"
          onClick={() => saveHiddenMediaOutputs([], setHiddenOutputIds)}
        ><RotateCcw size={16} />{t("Restore hidden")} ({hiddenOutputIds.length})</button>}
        <button className="secondary-button" disabled={refreshing} onClick={() => void load(undefined, true)}>
          <RefreshCw size={16} className={refreshing ? "is-spinning" : ""} />{t("Refresh")}
        </button>
        <Link className="primary-button" to="/creative-production"><Plus size={16} />{t("Create new")}</Link>
      </div>}
    />

    {error && <div role="alert" className="model-lab-error media-lab-friendly-error">
      <strong>{t("The library could not be refreshed")}</strong><p>{error}</p>
    </div>}

    <div className="media-library-toolbar">
      <label className="media-library-search">
        <Search size={17} />
        <span className="sr-only">{t("Search saved media")}</span>
        <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder={t("Search request, summary or brand")} />
      </label>
      <div className="media-library-filters" role="group" aria-label={t("Filter media type")}>
        {([
          ["all", "All", items.length],
          ["image", "Images", items.filter((item) => item.kind === "image").length],
          ["video", "Short videos", items.filter((item) => item.kind === "video").length],
        ] as const).map(([value, label, count]) => <button
          className={filter === value ? "is-active" : ""}
          key={value}
          onClick={() => setFilter(value)}
          aria-pressed={filter === value}
        >{t(label)} <span>{count}</span></button>)}
      </div>
    </div>

    {filteredItems.length ? <div className="media-library-layout">
      <div className="media-library-grid" aria-label={t("Saved media results")}>
        {filteredItems.map((item) => <LibraryCard
          dateLocale={dateLocale}
          item={item}
          key={item.id}
          selected={item.id === selected?.id}
          onSelect={() => setSelectedId(item.id)}
          onDelete={() => removeItem(item)}
        />)}
      </div>
      {selected && <LibraryDetail dateLocale={dateLocale} item={selected} />}
    </div> : <EmptyState
      icon={filter === "image" ? <ImageIcon /> : <Video />}
      title="No saved media found"
      text={items.length ? "Try another search or media filter." : "Creative Production output will appear here automatically."}
    />}
  </>;
}

function LibraryCard({ item, selected, onSelect, onDelete, dateLocale }: {
  item: LibraryItem;
  selected: boolean;
  onSelect: () => void;
  onDelete: () => void;
  dateLocale: string;
}) {
  const { t } = useI18n();
  const source = outputUrl(item);
  const title = itemTitle(item);
  return <article className={`media-library-card ${selected ? "is-selected" : ""}`}>
    <button type="button" className="media-library-card-select" onClick={onSelect} aria-pressed={selected} aria-label={title}>
      <div className="media-library-card-preview">
        {item.kind === "image" && source && <img src={source} alt="" loading="lazy" />}
        {item.kind !== "image" && source && <video src={source} preload="metadata" muted aria-hidden="true" />}
        {!source && <div className="media-library-card-placeholder">
          {item.kind === "image" ? <ImageIcon size={28} /> : <Video size={28} />}
          <span>{t("Output not ready")}</span>
        </div>}
        <span className="media-library-kind">{t(kindLabel(item.kind))}</span>
        <div className="media-library-card-hover" aria-hidden="true">
          <strong>{title}</strong>
          <span>{originalRequest(item)}</span>
          <small>{formatLabel(item)} · {versionLabel(item)}</small>
        </div>
      </div>
      <div className="media-library-card-copy">
        <div><StatusBadge status={itemStatus(item)} /><small>{formatDate(item.createdAt, dateLocale)}</small></div>
        <strong>{compactCardTitle(item)}</strong>
        <span>{compactCardSubtitle(item)}</span>
      </div>
    </button>
    <button
      type="button"
      className="media-library-card-delete"
      onClick={onDelete}
      aria-label={t("Remove from Media Library")}
      title={t("Remove from Media Library")}
    ><Trash2 size={15} /></button>
  </article>;
}

function LibraryDetail({ item, dateLocale }: { item: LibraryItem; dateLocale: string }) {
  const { t } = useI18n();
  const source = outputUrl(item);
  const promptVersion = plannerPromptVersion(item);
  return <aside className="panel media-library-detail" aria-label={t("Selected media details")}>
    <div className="media-library-detail-heading">
      <div><p className="eyebrow">{t(kindLabel(item.kind))}</p><h2>{itemTitle(item)}</h2></div>
      <StatusBadge status={itemStatus(item)} />
    </div>

    <div className="media-library-detail-preview">
      {item.kind === "image" && source && <img src={source} alt={itemTitle(item)} />}
      {item.kind !== "image" && source && <video controls src={source} preload="metadata" />}
      {!source && <div className="media-library-detail-placeholder">
        {item.kind === "image" ? <ImageIcon size={36} /> : <Video size={36} />}
        <strong>{t("Output is not available yet")}</strong>
        <span>{t("The saved run and its status remain available for the team.")}</span>
      </div>}
    </div>

    <div className="media-library-meta">
      <div><span>{t("Created")}</span><strong>{formatDate(item.createdAt, dateLocale, true)}</strong></div>
      <div><span>{t("Version")}</span><strong>{versionLabel(item)}</strong></div>
      <div><span>{t("Format")}</span><strong>{formatLabel(item)}</strong></div>
      <div><span>{t("Review")}</span><strong>{reviewLabel(item)}</strong></div>
    </div>

    <section className="media-library-prompt">
      <h3>{t("Original request")}</h3>
      <p>{originalRequest(item)}</p>
    </section>

    {source && <a className="primary-button media-library-download" href={source} download>
      <Download size={17} />{t("Download output")}
    </a>}

    <details className="audit-details media-library-audit">
      <summary>{t("Prompt and audit details")}</summary>
      <dl className="detail-list">
        <div><dt>{t("Prompt version")}</dt><dd><code>{promptVersion ?? t("Not available")}</code></dd></div>
        <div><dt>{t("Saved record")}</dt><dd><code>{recordId(item)}</code></dd></div>
        <div><dt>{t("Output checksum")}</dt><dd><code>{outputChecksum(item) ?? t("Not available")}</code></dd></div>
      </dl>
    </details>
  </aside>;
}

function outputUrl(item: LibraryItem): string | null {
  return item.version.artifact_web_url;
}

function outputChecksum(item: LibraryItem): string | null {
  return item.version.checksum_sha256;
}

function originalRequest(item: LibraryItem): string {
  const direction = item.detail.trace?.request.additional_requirements;
  return typeof direction === "string" && direction.trim()
    ? direction
    : `${item.request.sku_id} · ${item.version.variation_key}`;
}

function plannerPromptVersion(item: LibraryItem): string | null {
  return item.detail.trace?.plan?.prompt_version ?? null;
}

function itemTitle(item: LibraryItem): string {
  return `${item.request.sku_id} · ${item.version.variation_key}`;
}

function itemStatus(item: LibraryItem): string {
  return item.version.outcome;
}

function compactCardTitle(item: LibraryItem): string {
  return item.request.sku_id;
}

function compactCardSubtitle(item: LibraryItem): string {
  return humanizeIdentifier(item.version.variation_key);
}

function humanizeIdentifier(value: string): string {
  return value.replaceAll(/[_-]+/g, " ").replaceAll(/\s+/g, " ").trim();
}

function readHiddenMediaOutputs(): string[] {
  try {
    const value = JSON.parse(globalThis.localStorage?.getItem(HIDDEN_MEDIA_OUTPUTS_KEY) ?? "[]");
    return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
  } catch {
    return [];
  }
}

function saveHiddenMediaOutputs(ids: string[], update: (ids: string[]) => void): void {
  update(ids);
  try {
    globalThis.localStorage?.setItem(HIDDEN_MEDIA_OUTPUTS_KEY, JSON.stringify(ids));
  } catch {
    // Keep the current session usable when browser storage is unavailable.
  }
}

function reviewLabel(item: LibraryItem): string {
  return item.detail.review_decision?.asset_version_ids.includes(item.version.asset_version_id)
    ? item.detail.review_decision.decision.replaceAll("_", " ")
    : "Pending review";
}

function versionLabel(item: LibraryItem): string {
  return item.version.asset_version_id;
}

function formatLabel(item: LibraryItem): string {
  const format = item.version.content_type?.split("/").at(-1)?.toUpperCase() ?? item.kind.toUpperCase();
  const dimensions = item.version.actual_width && item.version.actual_height
    ? `${item.version.actual_width}×${item.version.actual_height}`
    : null;
  const duration = item.version.actual_duration_seconds ? `${item.version.actual_duration_seconds}s` : null;
  return [format, dimensions, duration].filter(Boolean).join(" · ");
}

function recordId(item: LibraryItem): string {
  return item.version.asset_version_id;
}

function kindLabel(kind: LibraryItem["kind"]): string {
  return kind === "image" ? "Image" : "Short video";
}

function librarySearchText(item: LibraryItem): string {
  return [item.request.sku_id, item.version.variation_key, originalRequest(item)].join(" ");
}

function formatDate(value: string, locale: string, includeTime = false): string {
  return new Intl.DateTimeFormat(locale, includeTime
    ? { dateStyle: "medium", timeStyle: "short" }
    : { dateStyle: "medium" }).format(new Date(value));
}
