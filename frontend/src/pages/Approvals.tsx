import { useState } from "react";
import { CheckCircle2, XCircle } from "lucide-react";
import { useCreativeJobs, usePilotDashboard } from "../hooks/usePilotDashboard";
import { DecisionCard } from "../components/DecisionCard";
import { Badge, EmptyState, PageHeader, SkeletonPage } from "../components/ui";
import { dashboardStreamLabels } from "../marketing/labels";
import { useI18n } from "../hooks/useI18n";

export function ApprovalsPage() {
  const { t } = useI18n();
  const { data, isLoading, error } = usePilotDashboard();
  const creatives = useCreativeJobs();
  const previewByEntity = new Map(
    (creatives.data?.items ?? [])
      .filter((item) => item.thumbnail_web_url)
      .map((item) => [item.job_id, item.thumbnail_web_url as string]),
  );
  const [tab, setTab] = useState("pending");
  const [stream, setStream] = useState("all");
  if (isLoading) return <SkeletonPage />;
  if (error || !data) return <EmptyState icon={<XCircle />} title="Could not load approvals" text={error?.message ?? "The backend dashboard returned no data."} />;
  const items = data.approvals.filter((item) => (stream === "all" || stream === item.workstream) && (tab === "all" || item.status === tab));
  const pendingCount = data.approvals.filter((item) => item.status === "pending" && (stream === "all" || stream === item.workstream)).length;

  return (
    <section className="approvals-page">
      <PageHeader eyebrow="Your decision queue" title="Needs approval" description="Each item contains the output and context needed for a business decision. Technical identifiers remain available inside its audit details." variant="decision" actions={<Badge tone="warning">{pendingCount} {t("decisions waiting")}</Badge>} />
      <div className="approval-toolbar" aria-label={t("Approval filters")}>
        <div className="segmented">{["pending", "all"].map((item) => <button key={item} className={tab === item ? "active" : ""} onClick={() => setTab(item)}>{t(item)}{item === "pending" && <span>{pendingCount}</span>}</button>)}</div>
        <label className="approval-stream-filter"><span>{t("Workstream")}</span><select aria-label={t("Approval workstream")} value={stream} onChange={(event) => setStream(event.target.value)}><option value="all">{t("All Marketing")}</option>{Object.entries(dashboardStreamLabels).map(([key, label]) => <option key={key} value={key}>{t(label)}</option>)}</select></label>
      </div>
      <div className="results-heading"><span>{items.length} {t(items.length === 1 ? "decision" : "decisions")}</span><span>{t("Sorted by waiting time")}</span></div>
      <div className="decision-list">
        {items.map((item) => <DecisionCard approval={item} previewUrl={previewByEntity.get(item.entity_id)} key={item.approval_id} />)}
      </div>
      {!items.length && <EmptyState icon={<CheckCircle2 />} title="All decisions are clear" text="The backend pilot will add an item when an exact business decision is required." />}
    </section>
  );
}
