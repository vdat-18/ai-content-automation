import { useEffect, useMemo, useState } from "react";
import { Download, Film, Image as ImageIcon, Plus, RefreshCw, RotateCcw, Search, Trash2, Video } from "lucide-react";
import { Link } from "react-router-dom";

import { Badge, EmptyState, PageHeader, SkeletonPage, StatusBadge } from "../components/ui";
import { useI18n } from "../hooks/useI18n";
import { marketingErrorMessage } from "../services/http";
import { pilotApi } from "../services/pilotApi";
import type {
  MarketingCreativeAutomationDetail,
  MarketingCreativeAutomationItem,
  MediaLabImageRun,
  MediaLabVideoAd,
  MediaLabVideoRun,
} from "../types/pilotApi";

type LibraryFilter = "all" | "image" | "video" | "ad";
const legacyLocalModelsEnabled = import.meta.env.VITE_ENABLE_LEGACY_LOCAL_MODELS === "true";
const emptyMediaRuns = { items: [], total: 0 };
const HIDDEN_MEDIA_OUTPUTS_KEY = "aic-hidden-media-output-ids";
type CreativeProductionVersion = MarketingCreativeAutomationDetail["production_versions"][number];
type LibraryItem =
  | { source: "media-lab"; id: string; kind: "image"; createdAt: string; run: MediaLabImageRun }
  | { source: "media-lab"; id: string; kind: "video"; createdAt: string; run: MediaLabVideoRun }
  | { source: "media-lab"; id: string; kind: "ad"; createdAt: string; run: MediaLabVideoAd }
  | {
    source: "creative-production";
    id: string;
    kind: "image" | "video";
    createdAt: string;
    request: MarketingCreativeAutomationItem;
    detail: MarketingCreativeAutomationDetail;
    version: CreativeProductionVersion;
  };

export function MediaLibraryPage() {
  const { language, t } = useI18n();
  const [images, setImages] = useState<MediaLabImageRun[]>([]);
  const [videos, setVideos] = useState<MediaLabVideoRun[]>([]);
  const [ads, setAds] = useState<MediaLabVideoAd[]>([]);
  const [creativeOutputs, setCreativeOutputs] = useState<LibraryItem[]>([]);
  const [filter, setFilter] = useState<LibraryFilter>("all");
  const [query, setQuery] = useState("");
  const [selectedId, setSelectedId] = useState("");
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [deletingId, setDeletingId] = useState("");
  const [hiddenOutputIds, setHiddenOutputIds] = useState<string[]>(readHiddenMediaOutputs);
  const [error, setError] = useState("");

  const load = async (signal?: AbortSignal, refresh = false) => {
    if (refresh) setRefreshing(true);
    setError("");
    try {
      const [imageResponse, videoResponse, adResponse, automationResponse] = await Promise.all([
        legacyLocalModelsEnabled ? pilotApi.mediaLabImageRuns(signal) : Promise.resolve(emptyMediaRuns),
        legacyLocalModelsEnabled ? pilotApi.mediaLabVideoRuns(signal) : Promise.resolve(emptyMediaRuns),
        legacyLocalModelsEnabled ? pilotApi.mediaLabVideoAds(signal) : Promise.resolve(emptyMediaRuns),
        pilotApi.marketingCreativeAutomations(signal),
      ]);
      const creativeDetails = await Promise.allSettled(
        automationResponse.items
          .filter((request) => request.asset_count > 0)
          .map(async (request) => ({
            request,
            detail: await pilotApi.marketingCreativeAutomation(request.request_id, signal),
          })),
      );
      setImages(imageResponse.items);
      setVideos(videoResponse.items);
      setAds(adResponse.items);
      setCreativeOutputs(creativeDetails.flatMap((result) => {
        if (result.status !== "fulfilled") return [];
        const { request, detail } = result.value;
        return detail.production_versions
          .filter((version) => version.success && Boolean(version.artifact_web_url))
          .map((version): LibraryItem => ({
            source: "creative-production",
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

  const allItems = useMemo<LibraryItem[]>(() => [
    ...images.map((run) => ({ source: "media-lab" as const, id: `image:${run.run_id}`, kind: "image" as const, createdAt: run.created_at, run })),
    ...videos.map((run) => ({ source: "media-lab" as const, id: `video:${run.run_id}`, kind: "video" as const, createdAt: run.created_at, run })),
    ...ads.map((run) => ({ source: "media-lab" as const, id: `ad:${run.job_id}`, kind: "ad" as const, createdAt: run.created_at, run })),
    ...creativeOutputs,
  ].sort((left, right) => Date.parse(right.createdAt) - Date.parse(left.createdAt)), [ads, creativeOutputs, images, videos]);
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

  const removeItem = async (item: LibraryItem) => {
    if (item.source === "creative-production") {
      if (!window.confirm(t("Remove this output from Media Library? The audit record will be kept and can be restored."))) return;
      saveHiddenMediaOutputs([...new Set([...hiddenOutputIds, item.id])], setHiddenOutputIds);
      if (selectedId === item.id) setSelectedId("");
      return;
    }
    if (!window.confirm(t("Permanently delete this saved Media Lab item?"))) return;
    setDeletingId(item.id);
    setError("");
    try {
      if (item.kind === "image") {
        await pilotApi.deleteMediaLabImageRun(item.run.run_id);
        setImages((current) => current.filter((run) => run.run_id !== item.run.run_id));
      } else if (item.kind === "video") {
        await pilotApi.deleteMediaLabVideoRun(item.run.run_id);
        setVideos((current) => current.filter((run) => run.run_id !== item.run.run_id));
      } else {
        await pilotApi.deleteMediaLabVideoAd(item.run.job_id);
        setAds((current) => current.filter((run) => run.job_id !== item.run.job_id));
      }
      if (selectedId === item.id) setSelectedId("");
    } catch (reason: unknown) {
      setError(marketingErrorMessage(reason));
    } finally {
      setDeletingId("");
    }
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
          ["ad", "Final Ads", ads.length],
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
          deleting={item.id === deletingId}
          deletable={itemCanDelete(item)}
          onSelect={() => setSelectedId(item.id)}
          onDelete={() => void removeItem(item)}
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

function LibraryCard({ item, selected, deleting, deletable, onSelect, onDelete, dateLocale }: {
  item: LibraryItem;
  selected: boolean;
  deleting: boolean;
  deletable: boolean;
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
          {item.kind === "image" ? <ImageIcon size={28} /> : item.kind === "ad" ? <Film size={28} /> : <Video size={28} />}
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
      disabled={deleting || !deletable}
      onClick={onDelete}
      aria-label={t(deletable ? "Remove from Media Library" : "Wait for this item to finish before deleting it")}
      title={t(deletable ? "Remove from Media Library" : "Wait for this item to finish before deleting it")}
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

    {item.source === "media-lab" && item.kind === "ad" && <section className="media-library-prompt">
      <h3>{t("Campaign brief")}</h3>
      <dl className="detail-list">
        <div><dt>{t("Brand")}</dt><dd>{item.run.brand}</dd></div>
        <div><dt>{t("SKU")}</dt><dd>{item.run.sku}</dd></div>
        <div><dt>{t("Marketing angle")}</dt><dd>{item.run.angle}</dd></div>
        {item.run.cta_text && <div><dt>{t("Call to action")}</dt><dd>{item.run.cta_text}</dd></div>}
      </dl>
    </section>}

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
      {item.source === "media-lab" && item.kind !== "ad" && <div className="media-library-production-prompt">
        <h3>{t("Prepared generation prompt")}</h3><p>{item.run.production_prompt}</p>
      </div>}
      {item.source === "media-lab" && item.kind === "ad" && item.run.shots.length > 0 && <div className="media-library-shot-list">
        <h3>{t("Saved shot prompts")}</h3>
        <ol>{item.run.shots.map((shot) => <li key={shot.shot_id}><strong>{shot.purpose}</strong><p>{shot.prompt}</p></li>)}</ol>
      </div>}
    </details>
  </aside>;
}

function outputUrl(item: LibraryItem): string | null {
  if (item.source === "creative-production") return item.version.artifact_web_url;
  if (item.kind === "image") return item.run.master_output_url ?? item.run.output_url;
  return item.run.output_url;
}

function outputChecksum(item: LibraryItem): string | null {
  if (item.source === "creative-production") return item.version.checksum_sha256;
  return item.run.output_checksum_sha256;
}

function originalRequest(item: LibraryItem): string {
  if (item.source === "creative-production") {
    const direction = item.detail.trace?.request.additional_requirements;
    return typeof direction === "string" && direction.trim()
      ? direction
      : `${item.request.sku_id} · ${item.version.variation_key}`;
  }
  if (item.kind === "ad") return item.run.user_request;
  return item.run.orchestration?.user_request ?? item.run.production_prompt;
}

function plannerPromptVersion(item: LibraryItem): string | null {
  if (item.source === "creative-production") return item.detail.trace?.plan?.prompt_version ?? null;
  if (item.kind === "ad") return item.run.planner_prompt_version;
  return item.run.orchestration?.planner_prompt_version ?? null;
}

function itemTitle(item: LibraryItem): string {
  if (item.source === "creative-production") return `${item.request.sku_id} · ${item.version.variation_key}`;
  if (item.kind === "ad") return item.run.summary ?? "Final Video Ad";
  return item.run.orchestration?.summary ?? (item.kind === "image" ? "Generated image" : "Generated short video");
}

function itemStatus(item: LibraryItem): string {
  if (item.source === "creative-production") return item.version.outcome;
  if (item.kind === "ad") return item.run.state;
  return item.run.generation_state;
}

function itemCanDelete(item: LibraryItem): boolean {
  if (item.source === "creative-production") return true;
  if (item.kind === "ad") {
    return !["planning", "generating_shots", "selecting_segments", "assembling", "cancel_requested"].includes(item.run.state);
  }
  return !["queued", "running"].includes(item.run.generation_state);
}

function compactCardTitle(item: LibraryItem): string {
  if (item.source === "creative-production") return item.request.sku_id;
  return itemTitle(item);
}

function compactCardSubtitle(item: LibraryItem): string {
  if (item.source === "creative-production") return humanizeIdentifier(item.version.variation_key);
  return originalRequest(item);
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
  if (item.source === "creative-production") {
    return item.detail.review_decision?.asset_version_ids.includes(item.version.asset_version_id)
      ? item.detail.review_decision.decision.replaceAll("_", " ")
      : "Pending review";
  }
  if (item.kind === "ad") return item.run.state === "completed" ? "Completed" : item.run.state.replaceAll("_", " ");
  return item.run.review_state.replaceAll("_", " ");
}

function versionLabel(item: LibraryItem): string {
  if (item.source === "creative-production") return item.version.asset_version_id;
  if (item.kind === "ad") return "Final Ad";
  return `C${item.run.regeneration_count}`;
}

function formatLabel(item: LibraryItem): string {
  if (item.source === "creative-production") {
    const format = item.version.content_type?.split("/").at(-1)?.toUpperCase() ?? item.kind.toUpperCase();
    const dimensions = item.version.actual_width && item.version.actual_height
      ? `${item.version.actual_width}×${item.version.actual_height}`
      : null;
    const duration = item.version.actual_duration_seconds ? `${item.version.actual_duration_seconds}s` : null;
    return [format, dimensions, duration].filter(Boolean).join(" · ");
  }
  if (item.kind === "image") {
    const dimensions = item.run.width && item.run.height ? `${item.run.width}×${item.run.height}` : item.run.aspect_ratio;
    return [item.run.output_format.toUpperCase(), dimensions].filter(Boolean).join(" · ");
  }
  const width = item.run.actual_width;
  const height = item.run.actual_height;
  const milliseconds = item.run.actual_duration_milliseconds;
  const duration = milliseconds ? `${(milliseconds / 1000).toFixed(milliseconds % 1000 ? 1 : 0)}s` : item.kind === "ad" ? `${item.run.target_duration_seconds}s` : `${item.run.duration_seconds}s`;
  return ["MP4", width && height ? `${width}×${height}` : item.run.aspect_ratio, duration].filter(Boolean).join(" · ");
}

function recordId(item: LibraryItem): string {
  if (item.source === "creative-production") return item.version.asset_version_id;
  return item.kind === "ad" ? item.run.job_id : item.run.run_id;
}

function kindLabel(kind: LibraryItem["kind"]): string {
  if (kind === "image") return "Image";
  if (kind === "video") return "Short video";
  return "Final Video Ad";
}

function librarySearchText(item: LibraryItem): string {
  if (item.source === "creative-production") {
    return [item.request.sku_id, item.version.variation_key, originalRequest(item)].join(" ");
  }
  if (item.kind === "ad") return [item.run.user_request, item.run.summary, item.run.brand, item.run.sku, item.run.angle].filter(Boolean).join(" ");
  return [item.run.orchestration?.user_request, item.run.orchestration?.summary, item.run.production_prompt].filter(Boolean).join(" ");
}

function formatDate(value: string, locale: string, includeTime = false): string {
  return new Intl.DateTimeFormat(locale, includeTime
    ? { dateStyle: "medium", timeStyle: "short" }
    : { dateStyle: "medium" }).format(new Date(value));
}
