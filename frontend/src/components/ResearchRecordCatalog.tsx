import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ExternalLink, ImageOff, Play, Trash2 } from "lucide-react";
import type { ResearchCrawlRecord, ResearchReviewDecision } from "../types/pilotApi";
import { pilotApi } from "../services/pilotApi";
import { Modal } from "./Modal";

type ResearchRecordCatalogProps = {
  records: ResearchCrawlRecord[];
  selectedRecordKeys?: string[];
  onSelectionChange?: (recordKey: string, selected: boolean) => void;
  onReview?: (
    recordKey: string,
    decision: ResearchReviewDecision,
    reviewerAlias: string,
    reason: string,
  ) => Promise<boolean> | boolean;
  reviewPending?: boolean;
  onReanalyze?: (recordKey: string) => Promise<boolean> | boolean;
  reanalysisPending?: boolean;
  onDelete?: (recordKey: string) => Promise<boolean> | boolean;
  deletePending?: boolean;
};

type ReferenceProfile = {
  summary?: string;
  relevance_to_project?: string;
  primary_subject?: string;
  content_goal?: string;
  reference_types?: string[];
  product_categories?: string[];
  visual_style?: string[];
  composition?: string[];
  setting?: string[];
  colors?: string[];
  camera_motion?: string[];
  text_treatment?: string[];
  temporal_structure?: string[];
  audio?: string[];
  hook?: string;
  message?: string;
  creative_takeaways?: string[];
  do_not_copy?: string[];
  observed_facts?: string[];
  inferences?: string[];
  media_notes?: string[];
  applicability_constraints?: string[];
};

type ScreeningMetadata = {
  status?: "completed" | "failed";
  prompt_version?: string;
  model?: string;
  usable?: boolean;
  reason_code?: string;
  reason?: string;
  confidence?: number;
  profile?: ReferenceProfile | null;
  error_code?: string | null;
};

export function ResearchRecordCatalog({
  records,
  selectedRecordKeys = [],
  onSelectionChange,
  onReview,
  reviewPending = false,
  onReanalyze,
  reanalysisPending = false,
  onDelete,
  deletePending = false,
}: ResearchRecordCatalogProps) {
  const [selected, setSelected] = useState<ResearchCrawlRecord | null>(null);
  const recordKey = typeof selected?.metadata.record_key === "string" ? selected.metadata.record_key : null;
  const detail = useQuery({
    queryKey: ["research-record", recordKey],
    queryFn: ({ signal }) => pilotApi.researchRecord(recordKey!, signal),
    enabled: recordKey !== null,
  });
  const selectedKeys = new Set(selectedRecordKeys);
  return <>
    <div className="research-record-grid">
      {records.map((record) => {
        const itemKey = typeof record.metadata.record_key === "string" ? record.metadata.record_key : null;
        const selectionEnabled = itemKey !== null
          && onSelectionChange !== undefined
          && metadataText(record, "screening_status") === "kept";
        const profile = screeningMetadata(record)?.profile;
        const title = referenceTitle(record, profile);
        return <article className="research-record-card-wrap" key={itemKey ?? record.record_id}>
          {selectionEnabled && <label className="research-record-select">
            <input
              type="checkbox"
              checked={selectedKeys.has(itemKey)}
              onChange={(event) => onSelectionChange(itemKey, event.target.checked)}
              aria-label={`Select ${title}`}
            />
            <span>Select</span>
          </label>}
          <button className="research-record-card" type="button" onClick={() => setSelected(record)}>
            <ResearchCardMedia record={record} profile={profile} />
            <span className="research-record-card__body">
              <span className="research-record-card__heading">
                <strong>{title}</strong>
                <small>{recordLabel(record) || metadataText(record, "status") || record.record_type.replaceAll("_", " ")}</small>
              </span>
              {profile?.summary && <span className="research-record-card__summary">{profile.summary}</span>}
              <span className="research-record-card__footer">
                <small>{record.image_urls.length} images · {record.video_urls.length} videos</small>
                <span>{itemKey ? "Review" : "Details"}</span>
              </span>
            </span>
          </button>
        </article>;
      })}
    </div>
    {selected && <ResearchRecordDialog
      record={selected}
      versions={detail.data?.versions ?? []}
      onClose={() => setSelected(null)}
      onReview={onReview}
      reviewPending={reviewPending}
      onReanalyze={onReanalyze}
      reanalysisPending={reanalysisPending}
      onDelete={onDelete}
      deletePending={deletePending}
    />}
  </>;
}

function ResearchCardMedia({ record, profile }: { record: ResearchCrawlRecord; profile?: ReferenceProfile | null }) {
  const [videoFailed, setVideoFailed] = useState(false);
  const [imageFailed, setImageFailed] = useState(false);
  const assets = Array.isArray(record.metadata.media_assets) ? record.metadata.media_assets as { media_kind: string; status: string; artifact_ref?: string }[] : [];
  const storedImage = assets.find((asset) => asset.media_kind === "image" && asset.status === "available" && asset.artifact_ref);
  const storedVideo = assets.find((asset) => asset.media_kind === "video" && asset.status === "available" && asset.artifact_ref);
  const imageUrl = storedImage ? artifactUrl(storedImage.artifact_ref!) : record.image_urls.find((url) => !url.includes("s60x60")) ?? record.image_urls.at(-1);
  const videoUrl = storedVideo ? artifactUrl(storedVideo.artifact_ref!) : record.video_urls[0];
  const title = referenceTitle(record, profile);
  return <span className="research-record-card__media">
    {imageUrl && !imageFailed
      ? <img src={imageUrl} alt={title} loading="lazy" referrerPolicy="no-referrer" onError={() => setImageFailed(true)} />
      : videoUrl && !videoFailed
        ? <video src={videoUrl} aria-label={title} muted playsInline preload="metadata" onLoadedMetadata={(event) => { event.currentTarget.currentTime = 0.1; }} onError={() => setVideoFailed(true)} />
        : <span className="research-media-empty"><ImageOff size={30} /><small>No preview</small></span>}
    {record.video_urls.length > 0 && <span className="research-media-badge"><Play size={12} fill="currentColor" /> Video</span>}
    {record.image_urls.length + record.video_urls.length > 1 && <span className="research-media-count">+{record.image_urls.length + record.video_urls.length - 1}</span>}
    <span className="research-record-card__quick-view" aria-hidden="true">
      <strong>{title}</strong>
      {profile?.summary && <span>{profile.summary}</span>}
      <small>{metadataText(record, "platform") || record.record_type.replaceAll("_", " ")}</small>
    </span>
  </span>;
}

function ResearchRecordDialog({
  record,
  versions,
  onClose,
  onReview,
  reviewPending,
  onReanalyze,
  reanalysisPending,
  onDelete,
  deletePending,
}: {
  record: ResearchCrawlRecord;
  versions: { version_id: string; job_id: string; observed_at: string }[];
  onClose: () => void;
  onReview?: ResearchRecordCatalogProps["onReview"];
  reviewPending: boolean;
  onReanalyze?: ResearchRecordCatalogProps["onReanalyze"];
  reanalysisPending: boolean;
  onDelete?: ResearchRecordCatalogProps["onDelete"];
  deletePending: boolean;
}) {
  const [reviewer, setReviewer] = useState("");
  const [reason, setReason] = useState("");
  const recordKey = typeof record.metadata.record_key === "string" ? record.metadata.record_key : null;
  const started = metadataText(record, "started_running_on");
  const status = metadataText(record, "status");
  const reviewStatus = reviewLabel(record);
  const reviewerAlias = metadataText(record, "reviewer_alias");
  const reviewedAt = metadataText(record, "reviewed_at");
  const reviewReason = metadataText(record, "review_reason");
  const screening = screeningMetadata(record);
  const screeningUnavailable = screening?.status === "failed";
  const screeningStatus = metadataText(record, "screening_status");
  const profile = screening?.profile;
  const title = referenceTitle(record, profile);
  const metadata = Object.entries(record.metadata).filter(([key, value]) => (
    ![
      "record_key",
      "media_assets",
      "screening_status",
      "screening",
      "review_status",
      "reviewer_alias",
      "reviewed_at",
      "review_reason",
    ].includes(key)
    && value !== null
    && value !== ""
    && (!Array.isArray(value) || value.length > 0)
  ));
  const assets = persistedMedia(record);
  const videos = assets.some((asset) => asset.media_kind === "video") ? assets.filter((asset) => asset.media_kind === "video").map((asset) => artifactUrl(asset.artifact_ref)) : record.video_urls;
  const images = assets.some((asset) => asset.media_kind === "image") ? assets.filter((asset) => asset.media_kind === "image").map((asset) => artifactUrl(asset.artifact_ref)) : record.image_urls;
  const submitReview = async (decision: ResearchReviewDecision) => {
    if (!recordKey || !onReview) return;
    const saved = await onReview(recordKey, decision, reviewer.trim(), reason.trim());
    if (saved) onClose();
  };
  const retryAnalysis = async () => {
    if (!recordKey || !onReanalyze) return;
    const saved = await onReanalyze(recordKey);
    if (saved) onClose();
  };
  const deleteRecord = async () => {
    if (!recordKey || !onDelete) return;
    const deleted = await onDelete(recordKey);
    if (deleted) onClose();
  };
  return <Modal title={title} onClose={onClose} className="research-record-dialog">
    <div className="research-record-detail">
      <div className="research-record-detail__meta">
        <span>Record ID: {record.record_id}</span>
        {reviewStatus && <span className={`badge research-review-status research-review-status--${metadataText(record, "review_status")}`}>{reviewStatus}</span>}
        {status && <span className="badge">{status}</span>}
        {started && <span>Started {started}</span>}
      </div>
      {(images.length > 0 || videos.length > 0) && <div className="research-media-gallery">
        {videos.map((url) => <video key={url} src={url} controls playsInline preload="metadata" />)}
        {images.map((url, index) => <ResearchDetailImage key={url} url={url} alt={`${title} ${index + 1}`} />)}
      </div>}
      {record.text && <section><h3>What was collected</h3><p>{record.text}</p></section>}
      <ReferenceBrief profile={profile} unavailable={screeningUnavailable} reason={screening?.reason} confidence={screening?.confidence} />
      {recordKey && screeningStatus === "unavailable" && onReanalyze && <section className="research-review-panel">
        <div><h3>Waiting for automatic analysis</h3><p>This reference is safely stored but cannot reach Marketing review or Creative until analysis succeeds.</p></div>
        <button className="primary-button" type="button" disabled={reanalysisPending} onClick={() => void retryAnalysis()}>Retry automatic analysis</button>
      </section>}
      {recordKey && screeningStatus === "kept" && onReview && <section className="research-review-panel">
        <div><h3>Marketing review</h3><p>Only Marketing-approved references can be selected in Creative Production.</p></div>
        {reviewStatus && <p className="research-review-current"><strong>{reviewStatus}</strong>{reviewerAlias ? ` by ${reviewerAlias}` : ""}{reviewedAt ? ` · ${new Date(reviewedAt).toLocaleString()}` : ""}{reviewReason ? ` · ${reviewReason}` : ""}</p>}
        <div className="research-review-fields">
          <label><span>Your name</span><input value={reviewer} maxLength={120} onChange={(event) => setReviewer(event.target.value)} placeholder="Required to approve or reject" /></label>
          <label><span>Note (optional)</span><input value={reason} maxLength={1000} onChange={(event) => setReason(event.target.value)} placeholder="Why is this useful or not useful?" /></label>
        </div>
        <div className="research-review-actions">
          <button className="approve-button" type="button" disabled={reviewPending || !reviewer.trim()} onClick={() => void submitReview("approve")}>Approve for Creative</button>
          <button className="reject-button" type="button" disabled={reviewPending || !reviewer.trim()} onClick={() => void submitReview("reject")}>Not useful</button>
          <button className="secondary-button" type="button" disabled={reviewPending} onClick={() => void submitReview("review_later")}>Review later</button>
        </div>
      </section>}
      {record.links.length > 0 && <section><h3>Original links</h3><div className="research-record-links">{record.links.map((link) => <a key={`${link.url}-${link.text}`} href={link.url} target="_blank" rel="noreferrer"><span>{link.text || hostname(link.url)}</span><ExternalLink size={14} /></a>)}</div></section>}
      {metadata.length > 0 && <details className="research-record-metadata"><summary>Technical details ({metadata.length})</summary><dl>{metadata.map(([key, value]) => <div key={key}><dt>{key.replaceAll("_", " ")}</dt><dd>{formatMetadata(value)}</dd></div>)}</dl></details>}
      {versions.length > 0 && <section><h3>Change history ({versions.length})</h3><div className="research-version-list">{versions.map((version, index) => <div key={version.version_id}><strong>Version {versions.length - index}</strong><span>{new Date(version.observed_at).toLocaleString()}</span><small>Run {version.job_id}</small></div>)}</div></section>}
      {record.source_url && <a className="primary-button research-record-source" href={record.source_url} target="_blank" rel="noreferrer">Open original <ExternalLink size={15} /></a>}
      {recordKey && onDelete && <section className="research-delete-panel">
        <div><h3>Delete reference</h3><p>Remove this reference from Research Library. References already used by Creative are protected.</p></div>
        <button className="reject-button" type="button" disabled={deletePending} onClick={() => void deleteRecord()}><Trash2 size={15} /> Delete reference</button>
      </section>}
    </div>
  </Modal>;
}

function referenceTitle(record: ResearchCrawlRecord, profile?: ReferenceProfile | null) {
  return record.title || profile?.primary_subject || profile?.summary || "Creative reference";
}


function ReferenceBrief({ profile, unavailable, reason, confidence }: { profile?: ReferenceProfile | null; unavailable: boolean; reason?: string; confidence?: number }) {
  if (!profile) return <section className="research-screening-panel research-screening-panel--notice"><div><h3>AI reference brief</h3><p>{unavailable ? "AI analysis was unavailable." : "No AI reference brief is available for this older record."}</p></div>{reason && <p className="research-screening-reason">{reason}</p>}</section>;
  const tags = [...(profile.reference_types ?? []), ...(profile.product_categories ?? []), ...(profile.visual_style ?? [])];
  return <section className="research-reference-brief">
    <div className="research-reference-brief__header"><div><h3>AI reference brief</h3><p>{profile.summary}</p></div>{confidence !== undefined && <span>{Math.round(confidence * 100)}% confidence</span>}</div>
    <p><strong>Why it may help this project:</strong> {profile.relevance_to_project || "Review the visual and content details below."}</p>
    {profile.primary_subject && <p><strong>Primary subject:</strong> {profile.primary_subject}</p>}
    {profile.content_goal && <p><strong>Communication goal:</strong> {profile.content_goal}</p>}
    {tags.length > 0 && <div className="research-reference-tags">{tags.map((tag) => <span key={tag}>{tag}</span>)}</div>}
    <BriefList title="Creative takeaways" items={profile.creative_takeaways} />
    <BriefList title="Composition" items={profile.composition} />
    <BriefList title="Text treatment" items={profile.text_treatment} />
    <BriefList title="Video timeline" items={profile.temporal_structure} />
    <BriefList title="Audio" items={profile.audio} />
    <BriefList title="Applicability limits" items={profile.applicability_constraints} />
    <BriefList title="Do not copy literally" items={profile.do_not_copy} />
    <BriefList title="Observed facts" items={profile.observed_facts} />
    <BriefList title="AI inferences" items={profile.inferences} />
    <BriefList title="Media notes" items={profile.media_notes} />
  </section>;
}

function BriefList({ title, items }: { title: string; items?: string[] }) {
  if (!items?.length) return null;
  return <div className="research-reference-list"><strong>{title}</strong><ul>{items.map((item) => <li key={item}>{item}</li>)}</ul></div>;
}

function ResearchDetailImage({ url, alt }: { url: string; alt: string }) {
  const [failed, setFailed] = useState(false);
  return failed
    ? <div className="research-media-empty"><ImageOff size={30} /><small>Image unavailable</small></div>
    : <img src={url} alt={alt} loading="lazy" referrerPolicy="no-referrer" onError={() => setFailed(true)} />;
}

function recordLabel(record: ResearchCrawlRecord) {
  return reviewLabel(record);
}

function reviewLabel(record: ResearchCrawlRecord) {
  switch (metadataText(record, "review_status")) {
    case "pending_review": return "Needs review";
    case "approved": return "Marketing-approved";
    case "rejected": return "Not useful";
    default: return "";
  }
}

function screeningMetadata(record: ResearchCrawlRecord): ScreeningMetadata | null {
  const value = record.metadata.screening;
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? value as ScreeningMetadata
    : null;
}

function metadataText(record: ResearchCrawlRecord, key: string) {
  const value = record.metadata[key];
  return typeof value === "string" ? value : "";
}

function formatMetadata(value: unknown) {
  if (Array.isArray(value)) return value.map(String).join(", ");
  if (typeof value === "object" && value !== null) return JSON.stringify(value);
  return String(value);
}

function hostname(value: string) {
  try { return new URL(value).hostname; } catch { return value; }
}

function artifactUrl(reference: string) {
  return reference.startsWith("art_")
    ? `/api/v1/artifacts/${encodeURIComponent(reference)}/content`
    : `/artifacts/${reference.split("/").map(encodeURIComponent).join("/")}`;
}

function persistedMedia(record: ResearchCrawlRecord) {
  if (!Array.isArray(record.metadata.media_assets)) return [];
  return (record.metadata.media_assets as { media_kind: string; status: string; artifact_ref?: string | null }[])
    .filter((asset): asset is { media_kind: string; status: string; artifact_ref: string } => asset.status === "available" && typeof asset.artifact_ref === "string");
}
