import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { ArrowRight, Filter, FlaskConical, GitBranch, ShieldCheck } from "lucide-react";
import { useGmcRuns } from "../hooks/usePilotDashboard";
import { Badge, EmptyState, Panel, PanelHeader, StatusBadge } from "../components/ui";
import { useI18n } from "../hooks/useI18n";
import { pilotApi } from "../services/pilotApi";

type PerformancePilotCriterion = { criterion_id: string; metric: string; window_id: string; outcome: string; observed_value: string | null; operator: string; threshold: string; detail: string };
type PerformancePilotAssessment = { rule_id: string; classification: string; outcome: string; passed_criteria: number; required_passes: number; criteria: PerformancePilotCriterion[] };
type PerformancePilotPreview = { state: string; action: string; classification: string; evidence_refs: string[]; missing_context: string[] };
type PerformancePilotRun = {
  run_id: string; subject_type: string; subject_id: string; brand_id: string; sku_id: string; platform: string; objective: string; timezone: string; attribution: string; currency: string;
  evaluation_id: string; evaluation_state: string; classification: string; recommendation: string; rule_set_id: string; rule_version: string; rule_mode: string; rule_status: string;
  assessments: PerformancePilotAssessment[]; evidence_refs: string[]; decision: string | null; decision_reason: string | null; creative_demand_preview: PerformancePilotPreview | null;
};

const performanceRecommendationLabel = (value: string) => value === "request_new_creative" ? "Create a new Creative" : value.replaceAll("_", " ");
const performanceClassificationLabel = (value: string) => value === "product_strong_candidate" ? "Strong product opportunity" : value.replaceAll("_", " ");

type FeedbackPilotCriterion = { criterion_id: string; metric: string; window_id: string; outcome: string; observed_value: string | null; operator: string; threshold: string; detail: string; source_ref: string | null };
type FeedbackPilotLesson = { lesson_id: string; outcome: string; summary: string; supported_facts: string[]; non_conclusions: string[]; evidence_refs: string[]; rule_set_id: string; rule_version: string };
type FeedbackPilotPreview = { state: string; action: string; source_creative_version_id: string; reusable_context_refs: string[]; missing_context: string[] };
type FeedbackPilotRun = {
  run_id: string; state: string; warnings: string[]; decision: string | null; decision_reason: string | null;
  release: { creative_id: string; creative_version_id: string; current_version_id: string; brand_id: string; sku_id: string; idea_id: string; variation_id: string | null };
  ad_mapping: { status: string; platform: string; campaign_id: string | null; adset_id: string | null; ad_id: string | null; mapped_version_id: string | null; candidate_version_ids: string[] };
  performance: { evaluation_id: string; classification: string; recommendation: string; window_id: string; attribution: string; timezone: string; rule_set_id: string; rule_version: string; rule_mode: string; rule_status: string; criteria: FeedbackPilotCriterion[] };
  lesson: FeedbackPilotLesson | null; next_task_preview: FeedbackPilotPreview | null;
};

function PerformanceBackendPilot({ subject }: { subject: string }) {
  const [runs, setRuns] = useState<PerformancePilotRun[]>([]);
  const [selected, setSelected] = useState<PerformancePilotRun | null>(null);
  const [reason, setReason] = useState("");
  const [reviewer, setReviewer] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    pilotApi.performanceDecisions<PerformancePilotRun>(controller.signal)
      .then((payload) => { setRuns(payload.items); setSelected((current) => current ? payload.items.find((item) => item.run_id === current.run_id) ?? null : payload.items[0] ?? null); setError(""); })
      .catch((caught: unknown) => { if ((caught as { name?: string }).name !== "AbortError") setError(caught instanceof Error ? caught.message : "Performance API unavailable"); });
    return () => controller.abort();
  }, []);
  const visibleRuns = runs.filter((run) => subject === "all" || run.subject_type === subject);
  useEffect(() => {
    const matching = runs.filter((run) => subject === "all" || run.subject_type === subject);
    setSelected((current) => current && matching.some((run) => run.run_id === current.run_id) ? current : matching[0] ?? null);
  }, [runs, subject]);
  const decide = async (decision: "approve" | "reject" | "defer") => {
    if (!selected || !reason.trim() || !reviewer.trim()) return;
    setSaving(true); setError("");
    try {
      const updated = await pilotApi.decidePerformance<PerformancePilotRun>(selected.run_id, { evaluation_id: selected.evaluation_id, decision, reviewer_alias: reviewer.trim(), reason: reason.trim() });
      setRuns((items) => items.map((item) => item.run_id === updated.run_id ? updated : item)); setSelected(updated); setReason("");
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Decision failed"); }
    finally { setSaving(false); }
  };
  if (error && !runs.length) return <Panel className="mkt-issue-panel"><PanelHeader title="Performance API not connected" meta="Check the API and worker services." /><p>{error}</p></Panel>;
  if (!runs.length) return <Panel><EmptyState icon={<FlaskConical />} title="No Performance decision runs" text="A decision will appear after a real Performance source event is evaluated." /></Panel>;
  const selectedCriteria = selected?.assessments.flatMap((assessment) => assessment.criteria) ?? [];
  const passedCriteria = selectedCriteria.filter((criterion) => criterion.outcome === "pass").length;
  return <div className="mkt-pilot-layout">
    <Panel className="performance-queue-panel"><PanelHeader title="Recommended actions" />{visibleRuns.length ? <div className="performance-decision-list">{visibleRuns.map((run) => <button className={selected?.run_id === run.run_id ? "is-selected" : ""} onClick={() => { setSelected(run); setReason(""); }} key={run.run_id}><span className="workflow-symbol"><ShieldCheck size={18} /></span><span><strong>{run.subject_id}</strong><small>{run.brand_id} · {run.platform} · {performanceRecommendationLabel(run.recommendation)}</small></span><StatusBadge status={run.decision ?? run.evaluation_state} /><ArrowRight size={17} /></button>)}</div> : <EmptyState icon={<Filter />} title="No matching decisions" text="Choose another analysis grain." />}</Panel>
    {selected && <Panel className="performance-decision-card"><section className="performance-decision-hero"><div><p className="eyebrow">Recommended action</p><h2>{selected.subject_id}</h2><p>{performanceRecommendationLabel(selected.recommendation)} for {selected.brand_id} on {selected.platform}.</p></div><Badge tone="info">{performanceClassificationLabel(selected.classification)}</Badge></section><div className="performance-decision-summary"><div><span className="performance-decision-value"><strong>{passedCriteria}/{selectedCriteria.length}</strong></span><span>Evidence checks passed</span></div><div><span className="performance-decision-value"><strong>{selected.evidence_refs.length}</strong></span><span>Source references</span></div><div><span className="performance-decision-value"><StatusBadge status={selected.evaluation_state} /></span><span>Review readiness</span></div></div>{selected.creative_demand_preview ? <section className="performance-next-step"><p className="eyebrow">Next step</p><h3>Prepare a Creative experiment</h3><p>The opportunity is ready to become a bounded Creative brief after approval.</p>{selected.creative_demand_preview.missing_context.length > 0 && <p className="muted-copy">The Creative workflow will still need: {selected.creative_demand_preview.missing_context.map((item) => item.replaceAll("_", " ")).join(", ")}.</p>}</section> : <p className="mkt-muted">No Creative request applies to this recommendation.</p>}<details className="workflow-technical"><summary>Evidence and evaluation details</summary><dl className="compact-dl"><div><dt>Classification</dt><dd><code>{selected.classification}</code></dd></div><div><dt>Rule version</dt><dd><code>{selected.rule_set_id}@{selected.rule_version}</code></dd></div><div><dt>Measurement</dt><dd>{selected.attribution} · {selected.timezone}</dd></div></dl><div className="mkt-check-list">{selected.assessments.flatMap((assessment) => assessment.criteria.map((criterion) => <article key={assessment.rule_id + criterion.criterion_id}><span className={`mkt-check-icon mkt-check-icon--${criterion.outcome === "pass" ? "pass" : criterion.outcome === "unknown" ? "warning" : "fail"}`}><ShieldCheck size={15} /></span><div><strong>{criterion.criterion_id.replaceAll("-", " ")}</strong><p>{criterion.metric} · {criterion.window_id} · observed {criterion.observed_value ?? "UNKNOWN"} · {criterion.operator} {criterion.threshold}</p><small>{assessment.rule_id}: {assessment.outcome} ({assessment.passed_criteria}/{assessment.required_passes})</small></div><Badge tone={criterion.outcome === "pass" ? "success" : criterion.outcome === "unknown" ? "warning" : "danger"}>{criterion.outcome}</Badge></article>))}</div></details>{selected.decision ? <div className="mkt-filter-note"><span>Decision recorded: <strong>{selected.decision}</strong>. {selected.decision_reason}</span></div> : <div className="mkt-pilot-decision performance-decision-form"><div className="workflow-gate-copy"><strong>Your decision</strong></div><div className="workflow-gate-fields"><label>Reviewer name<input value={reviewer} onChange={(event) => setReviewer(event.target.value)} placeholder="Enter your name" /></label><label>Decision reason<textarea rows={3} value={reason} onChange={(event) => setReason(event.target.value)} placeholder="What led to this decision?" /></label></div>{error && <p className="form-error" role="alert">{error}</p>}<div><button className="primary-button" disabled={saving || !reason.trim() || !reviewer.trim() || selected.evaluation_state !== "ready_for_review"} onClick={() => void decide("approve")}>Approve plan</button><button className="secondary-button" disabled={saving || !reason.trim() || !reviewer.trim()} onClick={() => void decide("defer")}>Decide later</button><button className="reject-button" disabled={saving || !reason.trim() || !reviewer.trim()} onClick={() => void decide("reject")}>Decline</button></div><small>Approval prepares an internal Creative request. It does not change Ads or publish content.</small></div>}</Panel>}
  </div>;
}

function CreativeFeedbackBackendPilot() {
  const [runs, setRuns] = useState<FeedbackPilotRun[]>([]);
  const [selected, setSelected] = useState<FeedbackPilotRun | null>(null);
  const [reason, setReason] = useState("");
  const [reviewer, setReviewer] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    pilotApi.creativeFeedback<FeedbackPilotRun>(controller.signal)
      .then((payload) => { setRuns(payload.items); setSelected((current) => current ? payload.items.find((item) => item.run_id === current.run_id) ?? null : payload.items[0] ?? null); setError(""); })
      .catch((caught: unknown) => { if ((caught as { name?: string }).name !== "AbortError") setError(caught instanceof Error ? caught.message : "Creative feedback API unavailable"); });
    return () => controller.abort();
  }, []);
  const decide = async (decision: "approve" | "reject" | "defer") => {
    if (!selected?.lesson || !reason.trim() || !reviewer.trim()) return;
    setSaving(true); setError("");
    try {
      const updated = await pilotApi.decideCreativeFeedback<FeedbackPilotRun>(selected.run_id, { lesson_id: selected.lesson.lesson_id, decision, reviewer_alias: reviewer.trim(), reason: reason.trim() });
      setRuns((items) => items.map((item) => item.run_id === updated.run_id ? updated : item)); setSelected(updated); setReason("");
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Decision failed"); }
    finally { setSaving(false); }
  };
  if (error && !runs.length) return <Panel className="mkt-issue-panel"><PanelHeader title="Creative feedback API not connected" meta="Check the API and worker services." /><p>{error}</p></Panel>;
  if (!runs.length) return <Panel><EmptyState icon={<GitBranch />} title="No Creative feedback runs" text="Feedback will appear after a real Ads outcome is linked to an exact Creative version." /></Panel>;
  return <div className="mkt-pilot-layout">
    <Panel><PanelHeader title="API-backed Feedback lineage pilot" meta="Exact Creative version → Ad mapping → Performance evidence → lesson → next-task preview." /><div className="mkt-table-scroll"><table className="mkt-table"><thead><tr><th>Creative version</th><th>Performance</th><th>Lineage state</th><th>Decision</th></tr></thead><tbody>{runs.map((run) => <tr key={run.run_id}><td><button className="text-link mkt-record-title" onClick={() => { setSelected(run); setReason(""); }}>{run.release.creative_version_id}</button><small>{run.release.brand_id} · {run.release.sku_id}</small>{run.release.current_version_id !== run.release.creative_version_id && <small>Historical; current is {run.release.current_version_id}</small>}</td><td><StatusBadge status={run.performance.classification} /><small>{run.performance.recommendation}</small></td><td><StatusBadge status={run.state} /><small>mapping: {run.ad_mapping.status}</small></td><td><StatusBadge status={run.decision ?? "pending"} /></td></tr>)}</tbody></table></div></Panel>
    {selected && <Panel><PanelHeader title={selected.release.creative_version_id + " · feedback lineage"} meta={`${selected.performance.rule_set_id}@${selected.performance.rule_version} · ${selected.performance.attribution} · ${selected.performance.timezone}`} /><dl className="compact-dl"><div><dt>Idea → version</dt><dd>{selected.release.idea_id} → {selected.release.creative_version_id}</dd></div><div><dt>Ad placement</dt><dd>{selected.ad_mapping.platform} · {selected.ad_mapping.campaign_id ?? "UNKNOWN campaign"} · {selected.ad_mapping.ad_id ?? "UNKNOWN ad"}</dd></div><div><dt>Measured window</dt><dd>{selected.performance.window_id}</dd></div><div><dt>Mapping result</dt><dd>{selected.ad_mapping.mapped_version_id ?? (selected.ad_mapping.candidate_version_ids.join(", ") || "UNKNOWN")}</dd></div></dl>{selected.warnings.map((warning) => <p className="mkt-filter-note" key={warning}>{warning}</p>)}<div className="mkt-check-list">{selected.performance.criteria.map((criterion) => <article key={criterion.criterion_id}><span className={`mkt-check-icon mkt-check-icon--${criterion.outcome === "pass" ? "pass" : criterion.outcome === "unknown" ? "warning" : "fail"}`}><ShieldCheck size={15} /></span><div><strong>{criterion.criterion_id.replaceAll("-", " ")}</strong><p>{criterion.metric} · {criterion.window_id} · observed {criterion.observed_value ?? "UNKNOWN"} · {criterion.operator} {criterion.threshold}</p><small>{criterion.detail}</small></div><Badge tone={criterion.outcome === "pass" ? "success" : criterion.outcome === "unknown" ? "warning" : "danger"}>{criterion.outcome}</Badge></article>)}</div><h3>Evidence-backed lesson</h3>{selected.lesson ? <><p>{selected.lesson.summary}</p><ul>{selected.lesson.supported_facts.map((fact) => <li key={fact}>{fact}</li>)}</ul><p className="muted-copy">Limits: {selected.lesson.non_conclusions.join(" ")}</p></> : <p className="mkt-muted">No lesson is created until the exact version and evidence agree.</p>}<h3>Next Creative Task Preview</h3>{selected.next_task_preview ? <><p className="mkt-muted">{selected.next_task_preview.action} · {selected.next_task_preview.state}. Approval releases an internal preview only.</p><dl className="compact-dl"><div><dt>Reusable context</dt><dd>{selected.next_task_preview.reusable_context_refs.join(", ")}</dd></div><div><dt>Missing M1 context</dt><dd>{selected.next_task_preview.missing_context.join(", ")}</dd></div></dl></> : <p className="mkt-muted">No actionable task is released for this evidence state or recommendation.</p>}{selected.decision ? <div className="mkt-filter-note"><span>Decision recorded: <strong>{selected.decision}</strong>. {selected.decision_reason}</span></div> : selected.state === "ready_for_review" && selected.lesson ? <div className="mkt-pilot-decision"><label>Decision reason<textarea rows={3} value={reason} onChange={(event) => setReason(event.target.value)} placeholder="Record the reason for this exact lesson and Creative version." /></label>{error && <p className="form-error" role="alert">{error}</p>}<label>Reviewer name<input value={reviewer} onChange={(event) => setReviewer(event.target.value)} placeholder="Enter your name" /></label><div><button className="primary-button" disabled={saving || !reason.trim() || !reviewer.trim()} onClick={() => void decide("approve")}>Approve next-task preview</button><button className="secondary-button" disabled={saving || !reason.trim() || !reviewer.trim()} onClick={() => void decide("defer")}>Defer</button><button className="reject-button" disabled={saving || !reason.trim() || !reviewer.trim()} onClick={() => void decide("reject")}>Reject</button></div><small>No Ads action, publishing or Creative generation occurs here.</small></div> : null}</Panel>}
  </div>;
}

export function PerformanceDecisions() {
  const { t } = useI18n();
  const [params, setParams] = useSearchParams();
  const subject = params.get("subject") ?? "all";
  return <><div className="filterbar performance-decision-toolbar"><strong>{t("Decision queue")}</strong><label><Filter size={14} /> {t("Analysis grain")} <select aria-label={t("Analysis grain")} value={subject} onChange={(event) => setParams((old) => { const next = new URLSearchParams(old); next.set("subject", event.target.value); return next; }, { replace: true })}>{["all", "product", "angle", "concept", "creative"].map((value) => <option key={value}>{t(value)}</option>)}</select></label></div><PerformanceBackendPilot subject={subject} /><CreativeFeedbackBackendPilot /></>;
}

export function GmcBackendPilot() {
  const { data, isLoading, error } = useGmcRuns();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  if (isLoading) return <Panel><PanelHeader title="GMC data pipeline" meta="Loading the local API…" /></Panel>;
  if (error) return <Panel className="mkt-issue-panel"><PanelHeader title="GMC pilot API not connected" meta="Seed H1 and serve the Dashboard through FastAPI." /><p>{error.message}</p><code>run-gmc-ingestion --fixture config/fixtures/gmc_ingestion_synthetic.json</code></Panel>;
  const runs = data?.items ?? [];
  const selected = runs.find((run) => run.run_id === selectedId) ?? runs[0];
  if (!selected) return <Panel><EmptyState icon={<FlaskConical />} title="No GMC ingestion runs" text="A run will appear after a real GMC source file or snapshot is ingested." /></Panel>;
  return <div className="mkt-pilot-layout"><Panel><PanelHeader title="H1 GMC ingestion" meta="Read-only source inspection, schema validation and Shopify identity reconciliation." /><div className="mkt-table-scroll"><table className="mkt-table"><thead><tr><th>Run / store</th><th>Status</th><th>Rows</th><th>Identity issues</th></tr></thead><tbody>{runs.map((run) => <tr key={run.run_id}><td><button className="text-link mkt-record-title" onClick={() => setSelectedId(run.run_id)}>{run.brand_id}</button><small>{run.store_id}</small><code>{run.run_id}</code></td><td><StatusBadge status={run.status} /></td><td>{run.accepted_rows}/{run.total_rows}<small>{run.rejected_rows} rejected</small></td><td>{run.gmc_only_rows + run.conflicting_rows + run.duplicate_rows}</td></tr>)}</tbody></table></div></Panel><Panel><PanelHeader title={`${selected.brand_id} · ingestion evidence`} meta={`${selected.schema_version} · ${selected.mapping_version}`} /><dl className="mkt-facts"><div><dt>Source</dt><dd><code>{selected.source_ref}</code></dd></div><div><dt>Source checksum</dt><dd><code>{selected.source_checksum_sha256}</code></dd></div><div><dt>Matched</dt><dd>{selected.matched_rows}</dd></div><div><dt>GMC only</dt><dd>{selected.gmc_only_rows}</dd></div><div><dt>Conflicts</dt><dd>{selected.conflicting_rows}</dd></div><div><dt>Duplicates</dt><dd>{selected.duplicate_rows}</dd></div></dl>{selected.issues.map((issue) => <p className="mkt-filter-note" key={issue.code}><strong>{issue.code}</strong> · {issue.detail}</p>)}<p className="muted-copy">Read-only evidence. This view does not upload or mutate a GMC feed.</p></Panel></div>;
}
