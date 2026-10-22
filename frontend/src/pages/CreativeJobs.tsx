import { useEffect, useMemo, useRef, useState } from "react";
import { ArrowLeft, ChevronLeft, ChevronRight, FileText, Image as ImageIcon, Plus, RotateCcw, Trash2 } from "lucide-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";

import { CreativeMedia } from "../components/CreativeMedia";
import { SplitHandle } from "../components/SplitHandle";
import { Badge, EmptyState, PageHeader, Panel, PanelHeader, SkeletonPage, StatusBadge } from "../components/ui";
import { useCreativeJob, useCreativeJobs } from "../hooks/usePilotDashboard";
import { useSplitResize } from "../hooks/useSplitResize";
import { pilotApi } from "../services/pilotApi";
import type { CreativeJobSummary, CreativeJobVersion } from "../types/pilotApi";
import { useI18n } from "../hooks/useI18n";
import { useHiddenCreatives } from "../hooks/useHiddenCreatives";

const creativeTitle = (
  job: Pick<CreativeJobSummary, "job_id" | "source_run_id"> & { display_title?: string; card?: { candidate_summary: string } | null },
) => {
  const title = job.display_title || job.card?.candidate_summary || job.source_run_id || job.job_id;
  const cleaned = title.replace(/:\s*team-provided\s*\(\d+\s+variations?\)/i, " · Team brief");
  return /^(creative-task-|job_|mca-)[a-z0-9_-]+$/i.test(cleaned)
    ? `Creative production · ${job.job_id.replace(/^job_/, "").slice(-8).toUpperCase()}`
    : cleaned;
};

const PAGE_SIZE = 20;
const ATTENTION_STATUSES = new Set(["awaiting_approval", "idea_review", "revise_pending"]);
const ACTIVE_STATUSES = new Set(["pending", "validating", "collecting_context", "idea_generating", "brief_ready", "generating", "qa_checking"]);
const EXCEPTION_STATUSES = new Set(["exception_operational", "exception_policy"]);
const COMPLETED_STATUSES = new Set(["approved", "rejected", "archived"]);

type WorkflowFilter = "attention" | "active" | "exceptions" | "completed" | "all";

const matchesWorkflowFilter = (job: CreativeJobSummary, filter: WorkflowFilter) => {
  if (filter === "attention") return job.pending_approval || ATTENTION_STATUSES.has(job.status);
  if (filter === "active") return ACTIVE_STATUSES.has(job.status);
  if (filter === "exceptions") return EXCEPTION_STATUSES.has(job.status);
  if (filter === "completed") return COMPLETED_STATUSES.has(job.status);
  return true;
};

const shortReference = (value: string | null, fallback: string) => {
  if (!value) return fallback;
  return value.length > 18 ? `${value.slice(0, 8)}…${value.slice(-6)}` : value;
};

const creativeWarning = (warning: string) => warning.startsWith("technical_only:")
  ? "Product fidelity, visible text, claims and brand fit still need human review."
  : warning.replaceAll("_", " ");

export function CreativesPage() {
  const { t } = useI18n();
  const { data, isLoading, error } = useCreativeJobs();
  const [query, setQuery] = useState("");
  const [workflowFilter, setWorkflowFilter] = useState<WorkflowFilter>("attention");
  const [page, setPage] = useState(1);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const { hiddenIds, hideCreative, hideCreatives, restoreAll } = useHiddenCreatives();
  const searchableJobs = useMemo(
    () => (data?.items ?? []).filter((job) =>
      !hiddenIds.includes(job.job_id)
      && `${job.display_title} ${job.job_id} ${job.source_run_id ?? ""} ${job.idea_id ?? ""}`.toLowerCase().includes(query.toLowerCase())
    ),
    [data, hiddenIds, query],
  );
  const workflowCounts = useMemo(() => ({
    attention: searchableJobs.filter((job) => matchesWorkflowFilter(job, "attention")).length,
    active: searchableJobs.filter((job) => matchesWorkflowFilter(job, "active")).length,
    exceptions: searchableJobs.filter((job) => matchesWorkflowFilter(job, "exceptions")).length,
    completed: searchableJobs.filter((job) => matchesWorkflowFilter(job, "completed")).length,
    all: searchableJobs.length,
  }), [searchableJobs]);
  const jobs = useMemo(
    () => searchableJobs.filter((job) => matchesWorkflowFilter(job, workflowFilter)),
    [searchableJobs, workflowFilter],
  );
  const pageCount = Math.max(1, Math.ceil(jobs.length / PAGE_SIZE));
  const pageJobs = jobs.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);
  const visibleIds = pageJobs.map((job) => job.job_id);
  const selectedVisibleIds = visibleIds.filter((jobId) => selectedIds.includes(jobId));
  const allVisibleSelected = visibleIds.length > 0 && selectedVisibleIds.length === visibleIds.length;
  useEffect(() => setPage(1), [query, workflowFilter]);
  useEffect(() => {
    if (page > pageCount) setPage(pageCount);
  }, [page, pageCount]);
  const toggleCreative = (creativeId: string) => setSelectedIds((current) => current.includes(creativeId)
    ? current.filter((jobId) => jobId !== creativeId)
    : [...current, creativeId]);
  const toggleAllVisible = () => setSelectedIds((current) => allVisibleSelected
    ? current.filter((jobId) => !visibleIds.includes(jobId))
    : [...new Set([...current, ...visibleIds])]);
  const hideSelected = () => {
    if (!window.confirm(t("Remove selected creatives from this dashboard? Audit records will be kept and can be restored."))) return;
    hideCreatives(selectedVisibleIds);
    setSelectedIds((current) => current.filter((jobId) => !selectedVisibleIds.includes(jobId)));
  };

  if (isLoading) return <SkeletonPage />;
  if (error) return <EmptyState icon={<ImageIcon />} title="Creative API unavailable" text={error.message} />;

  return <>
    <PageHeader
      eyebrow="Generated assets"
      title="Creative library"
      description="Review visual output, compare versions and open the creatives that need a decision."
      variant="library"
      actions={<div className="creative-header-actions"><Badge tone="neutral">{jobs.length} visible</Badge>{hiddenIds.length > 0 && <button className="secondary-button" type="button" onClick={() => { restoreAll(); setSelectedIds([]); }}><RotateCcw size={15} />{t("Restore hidden")} ({hiddenIds.length})</button>}<Link className="primary-button" to="/creative-production"><Plus size={15} />New production</Link></div>}
    />
    <div className="filterbar creative-toolbar">
      <label className="search-field"><input aria-label="Search creatives" value={query} onChange={(event) => setQuery(event.target.value)} placeholder={t("Search title, run, job or idea")} /></label>
      <select aria-label={t("Workflow view")} value={workflowFilter} onChange={(event) => setWorkflowFilter(event.target.value as WorkflowFilter)}>
        <option value="attention">{t("Needs action")} ({workflowCounts.attention})</option>
        <option value="active">{t("In progress")} ({workflowCounts.active})</option>
        <option value="exceptions">{t("Exceptions")} ({workflowCounts.exceptions})</option>
        <option value="completed">{t("Completed")} ({workflowCounts.completed})</option>
        <option value="all">{t("All jobs")} ({workflowCounts.all})</option>
      </select>
      <div className="creative-bulk-actions">
        <button className="secondary-button" type="button" disabled={!pageJobs.length} onClick={toggleAllVisible}>{allVisibleSelected ? t("Clear selection") : `${t("Select page")} (${pageJobs.length})`}</button>
        {selectedVisibleIds.length > 0 && <button className="reject-button" type="button" onClick={hideSelected}><Trash2 size={15} />{t("Remove selected")} ({selectedVisibleIds.length})</button>}
      </div>
    </div>
    <div className="results-heading"><span>{jobs.length} {t(jobs.length === 1 ? "job" : "jobs")}</span><span>{t("Newest activity first")}</span></div>
    {pageJobs.length > 0 && <section className="creative-pipeline-list" aria-label={t("Creative jobs and briefs")}>
      <header className="creative-pipeline-list__header" aria-hidden="true"><span /> <span>{t("Creative job")}</span><span>{t("Output")}</span><span>{t("Status")}</span><span /></header>
      {pageJobs.map((job) => <CreativePipelineRow
        key={job.job_id}
        job={job}
        t={t}
        selected={selectedIds.includes(job.job_id)}
        onSelect={() => toggleCreative(job.job_id)}
        onHide={() => {
          if (window.confirm(t("Hide this creative from the dashboard?"))) {
            hideCreative(job.job_id);
            setSelectedIds((current) => current.filter((jobId) => jobId !== job.job_id));
          }
        }}
      />)}
    </section>}
    {jobs.length > PAGE_SIZE && <nav className="creative-pagination" aria-label={t("Creative job pages")}>
      <button className="secondary-button" type="button" disabled={page === 1} onClick={() => setPage((value) => Math.max(1, value - 1))}><ChevronLeft size={16} />{t("Previous")}</button>
      <span>{t("Page")} <strong>{page}</strong> {t("of")} {pageCount}</span>
      <button className="secondary-button" type="button" disabled={page === pageCount} onClick={() => setPage((value) => Math.min(pageCount, value + 1))}>{t("Next")}<ChevronRight size={16} /></button>
    </nav>}
    {!jobs.length && <EmptyState icon={<ImageIcon />} title="No persisted creatives" text="A Creative will appear here after a real workflow creates a job or output version." />}
  </>;
}

function CreativePipelineRow({ job, t, selected, onSelect, onHide }: { job: CreativeJobSummary; t: (value: string) => string; selected: boolean; onSelect: () => void; onHide: () => void }) {
  return <article className={`creative-pipeline-row ${selected ? "is-selected" : ""}`}>
    <label className="creative-pipeline-row__select" title={t("Select creative")}><input type="checkbox" checked={selected} onChange={onSelect} aria-label={`${t("Select creative")}: ${creativeTitle(job)}`} /></label>
    <Link className="creative-pipeline-row__main" to={`/creatives/${job.job_id}`}>
      <span className="creative-pipeline-row__icon">{job.thumbnail_web_url ? <img src={job.thumbnail_web_url} alt="" /> : <FileText size={18} />}</span>
      <span><strong>{creativeTitle(job)}</strong><small>{t("Job")} {shortReference(job.job_id, t("Unknown"))} · {t("Run")} {shortReference(job.source_run_id, t("Not available"))}</small></span>
    </Link>
    <div className="creative-pipeline-row__output"><strong>{job.version_count}</strong><span>{t(job.version_count === 1 ? "version" : "versions")}</span>{job.total_cost && <small>{job.total_cost}</small>}</div>
    <div className="creative-pipeline-row__status"><StatusBadge status={job.status} />{job.pending_approval && <small>{t("Ready for review")} · {t("Decision required")}</small>}</div>
    <div className="creative-pipeline-row__actions"><Link className="text-link" to={`/creatives/${job.job_id}`}>{t("Open")}</Link><button type="button" onClick={onHide} aria-label={t("Hide this creative from the dashboard")} title={t("Hide this creative from the dashboard")}><Trash2 size={15} /></button></div>
  </article>;
}

export function CreativeDetailPage() {
  const { creativeId } = useParams();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const loopRunId = params.get("loop");
  const { data: job, isLoading, error } = useCreativeJob(creativeId);
  const [reason, setReason] = useState("");
  const [reviewer, setReviewer] = useState("");
  const detailStackRef = useRef<HTMLDivElement>(null);
  const split = useSplitResize("aic-creative-split", 360, 720, detailStackRef);
  const client = useQueryClient();
  const decision = useMutation({
    mutationFn: async (value: "approve" | "reject") => {
      const payload = { decision: value, reviewer: reviewer.trim(), reason: reason.trim() || null };
      if (loopRunId) {
        return pilotApi.postCreativeLoop(loopRunId, "creative-decision", {
          decision: value,
          reviewer_alias: payload.reviewer,
          reason: payload.reason,
        });
      }
      return pilotApi.decideCreative(creativeId!, payload);
    },
    onSuccess: async () => {
      await Promise.all([
        client.invalidateQueries({ queryKey: ["creative-jobs"] }),
        client.invalidateQueries({ queryKey: ["creative-job", creativeId] }),
        client.invalidateQueries({ queryKey: ["pilot-dashboard"] }),
      ]);
    },
  });

  if (isLoading) return <SkeletonPage />;
  if (error || !job) return <EmptyState icon={<ImageIcon />} title="Creative not found" text={error?.message ?? "The backend returned no matching Creative job."} />;

  const finalRefs = job.card?.final_version_refs.length
    ? job.card.final_version_refs
    : job.card?.final_version_ref ? [job.card.final_version_ref] : [];
  const finalVersions = finalRefs.map((ref) => job.versions.find((version) => version.version_id === ref)).filter((version): version is CreativeJobVersion => version !== undefined);
  const pendingApproval = job.card !== null && job.card.decision === null;
  const syntheticSet = finalVersions.length > 0 && finalVersions.every((version) => version.artifact_url?.startsWith("fake://"));
  const canDecide = pendingApproval && !decision.isPending && finalRefs.length > 0 && finalVersions.length === finalRefs.length && (syntheticSet || finalVersions.every((version) => version.artifact_web_url));
  return <>
    <button className="back-link" onClick={() => navigate(-1)}><ArrowLeft size={16} />Back to library</button>
    <PageHeader
      eyebrow="Creative review"
      title={creativeTitle(job)}
      description="Review the complete output, business context and quality warnings before making one decision for the exact saved set."
      actions={<div className="header-badges"><StatusBadge status={job.status} /></div>}
    />
    <div className={"creative-detail-grid" + (split.active ? " split-active" : "")} style={split.style}>
      <div className="creative-set-list">
        {finalVersions.length
          ? finalVersions.map((version, index) => <CreativeVersionReview key={version.version_id} version={version} number={index + 1} total={finalVersions.length} />)
          : <Panel><EmptyState icon={<ImageIcon />} title="No reviewable set" text="This job has not produced a viewable final Creative set." /></Panel>}
      </div>
      <div className="detail-stack" ref={detailStackRef}>
        <SplitHandle label="Resize detail panel" {...split.handleProps} />
        {pendingApproval && <Panel id="decision" className="decision-callout decision-callout--form decision-callout--sticky">
          <div><Badge tone="warning">Decision required</Badge><h2>Approve this Creative set?</h2><p>One decision applies to all {finalRefs.length} saved output{finalRefs.length === 1 ? "" : "s"}. Exact version references are preserved in the audit record.</p>{syntheticSet && <p>Synthetic run: no real images were generated.</p>}</div>
          <label>Reviewer name<input value={reviewer} onChange={(event) => setReviewer(event.target.value)} placeholder="Enter your name" /></label>
          <label>Decision reason<textarea rows={3} value={reason} onChange={(event) => setReason(event.target.value)} placeholder="Record why the full set is approved or rejected." /></label>
          {decision.error && <p className="form-error">{decision.error.message}</p>}
          <div className="dialog-actions"><button className="approve-button" disabled={!canDecide || !reason.trim() || !reviewer.trim()} onClick={() => decision.mutate("approve")}>Approve and continue</button><button className="reject-button" disabled={!canDecide || !reason.trim() || !reviewer.trim()} onClick={() => decision.mutate("reject")}>Reject</button></div>
        </Panel>}
        <Panel>
          <PanelHeader title="Context and evidence" meta={`${job.versions.length} saved version${job.versions.length === 1 ? "" : "s"}`} />
          <dl className="detail-list">
            <div><dt>Idea</dt><dd>{job.idea_id?.replaceAll("-", " ") ?? "Unknown"}</dd></div>
            <div><dt>Brief</dt><dd>{job.brief_web_url ? <a href={job.brief_web_url} target="_blank" rel="noreferrer">Open saved brief</a> : job.brief_ref ?? (finalVersions.some((version) => version.review_context_web_url) ? "Saved with each final image" : "Unavailable")}</dd></div>
            <div><dt>Total cost</dt><dd>{job.total_cost ?? "Unknown"}</dd></div>
          </dl>
          {(job.card?.warnings?.length ?? 0) > 0 && <div className="policy-warning"><strong>Needs human attention</strong><ul>{job.card?.warnings.map((warning) => <li key={warning}>{creativeWarning(warning)}</li>)}</ul></div>}
          <details className="audit-details">
            <summary>Audit details</summary>
            <dl className="detail-list">
              <div><dt>Job ID</dt><dd><code>{job.job_id}</code></dd></div>
              <div><dt>Source run</dt><dd><code>{job.source_run_id ?? "Unknown"}</code></dd></div>
              <div><dt>Context</dt><dd><code>{job.context_ref ?? "Unknown"}</code></dd></div>
              <div><dt>Creative set</dt><dd><code>{job.creative_set_id ?? "Not created yet"}</code></dd></div>
              <div><dt>Preparation</dt><dd><code>{job.preparation_hash ?? "Unknown"}</code></dd></div>
              {job.card && <div><dt>Evidence refs</dt><dd>{job.card.evidence_refs.length}</dd></div>}
              <div><dt>Lineage entries</dt><dd>{job.lineage.length}</dd></div>
            </dl>
          </details>
        </Panel>
      </div>
    </div>
  </>;
}

function CreativeVersionReview({ version, number, total }: { version: CreativeJobVersion; number: number; total: number }) {
  const technicalOnly = version.qa_warnings.some((warning) => warning.startsWith("technical_only:"));
  const qaLabel = technicalOnly ? "Technical file check" : version.generator_version?.startsWith("fake-") ? "Synthetic QA" : "Automated QA";
  const { data: context, isError } = useQuery({
    queryKey: ["creative-review-context", version.review_context_web_url],
    queryFn: ({ signal }) => pilotApi.creativeReviewContext(version.review_context_web_url!, signal),
    enabled: Boolean(version.review_context_web_url),
    retry: false,
  });
  return <Panel className="asset-preview">
    <PanelHeader title={`Final image ${number} of ${total}`} meta="Exact saved output" />
    {version.artifact_web_url
      ? <CreativeMedia type="static" src={version.artifact_web_url} alt={`Final Creative ${number}`} />
      : version.artifact_url?.startsWith("fake://")
        ? <EmptyState icon={<ImageIcon />} title="Synthetic output — no viewable image" text="This test version records workflow evidence without a generated media file." />
        : <EmptyState icon={<ImageIcon />} title="No generated artifact" text="This final version has no viewable image." />}
    <dl className="detail-list">
      <div><dt>{qaLabel}</dt><dd>{version.qa_passed === null ? "Unknown" : version.qa_passed ? "Passed" : "Failed"} · {version.qa_score ?? "—"}/100</dd></div>
      <div><dt>Creative review</dt><dd>{version.qa_reviewer_version ? `AI reviewer: ${version.qa_reviewer_version}; human decision required` : "Human review required"}</dd></div>
      <div><dt>Feedback</dt><dd>{version.qa_feedback ?? "No saved feedback"}</dd></div>
    </dl>
    {version.qa_warnings.map((warning) => <p className="creative-review-warning" key={warning}>{creativeWarning(warning)}</p>)}
    <details className="audit-details">
      <summary>Version technical details</summary>
      <dl className="detail-list">
        <div><dt>Variation</dt><dd><code>{version.variation_id ?? "Single image"}</code></dd></div>
        <div><dt>Variation attempt</dt><dd>{version.variation_attempt_number ?? version.attempt_number}</dd></div>
        <div><dt>Version ID</dt><dd><code>{version.version_id}</code></dd></div>
        <div><dt>Input hash</dt><dd><code>{version.input_hash ?? "Unknown"}</code></dd></div>
        <div><dt>Prompt</dt><dd>{version.prompt_version ?? "Unknown"}</dd></div>
        <div><dt>Rubric</dt><dd>{version.rubric_version ?? "Unknown"}</dd></div>
        <div><dt>Policy</dt><dd>{version.policy_version ?? "Unknown"}</dd></div>
        <div><dt>Workflow</dt><dd>{version.workflow_version ?? "Unknown"}</dd></div>
        <div><dt>Generator</dt><dd>{version.generator_version ?? "Unknown"}</dd></div>
      </dl>
    </details>
    {context ? <>
      <h3>Brief and source assets</h3>
      <dl className="detail-list">
        <div><dt>Product</dt><dd>{context.brand} · {context.sku}</dd></div>
        <div><dt>Objective</dt><dd>{context.objective}</dd></div>
        <div><dt>Planned heading</dt><dd>{context.heading}{context.subtext ? ` · ${context.subtext}` : ""}</dd></div>
        <div><dt>Visual direction</dt><dd>{context.visual_direction}</dd></div>
        {context.variation_key && <div><dt>Variation plan</dt><dd><code>{context.variation_key}</code></dd></div>}
        {context.awareness_stage && <div><dt>Awareness stage</dt><dd>{context.awareness_stage}</dd></div>}
        {context.angle && <div><dt>Angle</dt><dd>{context.angle}</dd></div>}
        {context.offer && <div><dt>Offer</dt><dd>{context.offer}</dd></div>}
        {context.production_level && <div><dt>Production level</dt><dd>{context.production_level}</dd></div>}
        <div><dt>Output</dt><dd>{context.output_spec.width} × {context.output_spec.height} {context.output_spec.file_format.toUpperCase()}</dd></div>
        <div><dt>Stage</dt><dd>{context.output_stage === "visual_only" ? "Visual only — planned text is not rendered" : "Rendered static composition"}</dd></div>
      </dl>
      <div className="creative-source-grid">{context.assets.map((asset) => <a key={`${asset.role}-${asset.index}`} href={asset.web_url} target="_blank" rel="noreferrer"><img src={asset.web_url} alt={`${asset.role} ${asset.index + 1}`} /><span>{asset.role.replaceAll("_", " ")} {asset.index + 1}</span></a>)}</div>
      {(context.product_preservation || context.raw_background) && <>
        <h3>Product preservation trace</h3>
        <div className="creative-source-grid">
          {context.product_preservation && <a href={context.product_preservation.cutout_web_url} target="_blank" rel="noreferrer"><img src={context.product_preservation.cutout_web_url} alt="Preserved product cutout" /><span>product cutout</span></a>}
          {context.product_preservation && <a href={context.product_preservation.mask_web_url} target="_blank" rel="noreferrer"><img src={context.product_preservation.mask_web_url} alt="Product segmentation mask" /><span>segmentation mask</span></a>}
          {context.raw_background && <a href={context.raw_background.web_url} target="_blank" rel="noreferrer"><img src={context.raw_background.web_url} alt="Generated background before product placement" /><span>raw background</span></a>}
        </div>
        {context.product_preservation && <p className="muted-copy">{context.product_preservation.model} / {context.product_preservation.model_version}</p>}
      </>}
    </> : <p className="muted-copy">{isError ? "Saved brief and source images are unavailable for this version." : "Loading saved brief and source images…"}</p>}
  </Panel>;
}
