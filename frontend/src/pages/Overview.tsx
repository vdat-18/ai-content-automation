import {
  ArrowRight,
  BarChart3,
  CheckCircle2,
  Clapperboard,
  Image as ImageIcon,
  LibraryBig,
  Search,
  Sparkles,
  TriangleAlert,
  Trash2,
  WifiOff,
} from "lucide-react";
import { Link } from "react-router-dom";

import { CreativeMedia } from "../components/CreativeMedia";
import { DecisionCard } from "../components/DecisionCard";
import { Badge, PageHeader, Panel, PanelHeader, SkeletonPage, StatusBadge } from "../components/ui";
import { useDataSources } from "../hooks/useDataSources";
import { useCreativeJobs, usePilotDashboard } from "../hooks/usePilotDashboard";
import { useI18n } from "../hooks/useI18n";
import { useHiddenCreatives } from "../hooks/useHiddenCreatives";
import { businessStage, dashboardStreamLabels } from "../marketing/labels";

export function OverviewPage() {
  const { t } = useI18n();
  const pilot = usePilotDashboard();
  const creativeJobs = useCreativeJobs();
  const sourceQuery = useDataSources();
  const { hiddenIds, hideCreative } = useHiddenCreatives();
  if (pilot.isLoading) return <SkeletonPage />;

  const approvals = pilot.data?.approvals ?? [];
  const exceptions = pilot.data?.exceptions ?? [];
  const active = (pilot.data?.workflows ?? []).filter((item) => item.status === "running" || item.status === "waiting");
  const previews = new Map((creativeJobs.data?.items ?? []).filter((item) => item.thumbnail_web_url).map((item) => [item.job_id, item.thumbnail_web_url as string]));
  const latestCreatives = (creativeJobs.data?.items ?? []).filter((item) => item.thumbnail_web_url && !hiddenIds.includes(item.job_id)).slice(0, 4);
  const sources = sourceQuery.data?.items ?? [];
  const healthySources = sources.filter((source) => source.status === "healthy").length;
  const systemHealthy = exceptions.length === 0 && !sourceQuery.error && !creativeJobs.error && (sources.length === 0 || healthySources === sources.length);
  const quickActions = [
    { to: "/creative-production", icon: Clapperboard, label: "New production request", detail: "Create a brief and visual outputs from a selected product." },
    { to: "/research-crawler", icon: Search, label: "Research a reference", detail: "Capture useful market and competitor examples." },
    { to: "/research-library", icon: LibraryBig, label: "Browse research", detail: "Find approved references for the next creative." },
    { to: "/performance", icon: BarChart3, label: "Review performance", detail: "See opportunities backed by campaign evidence." },
  ];

  return <>
    <PageHeader
      eyebrow="Marketing operations"
      title="Today"
      description="Review the decisions that need you. AI continues the remaining work in the background."
      variant="campaign"
      actions={<Link className="primary-button overview-primary-action" to="/creative-production"><Clapperboard size={16} />{t("Start production")}</Link>}
    />

    <nav className="overview-statusbar" aria-label={t("Workspace status")}>
      <Link to="/approvals">
        <span className="overview-statusbar__dot overview-statusbar__dot--decision" />
        <div><strong>{approvals.length}</strong><span>{t("decisions waiting")}</span></div>
        <ArrowRight size={15} />
      </Link>
      <Link to="/workflows">
        <span className="overview-statusbar__dot overview-statusbar__dot--active" />
        <div><strong>{active.length}</strong><span>{t("active workflows")}</span></div>
        <ArrowRight size={15} />
      </Link>
      <Link to="/exceptions">
        <span className="overview-statusbar__dot overview-statusbar__dot--issue" />
        <div><strong>{exceptions.length}</strong><span>{t("issues to inspect")}</span></div>
        <ArrowRight size={15} />
      </Link>
    </nav>

    {(pilot.error || creativeJobs.error) && <aside className="overview-service-note" role="status">
      <WifiOff size={17} />
      <div><strong>{t("Live data is temporarily unavailable")}</strong><span>{t("The workspace is still available. Refresh after the API reconnects.")}</span></div>
      <details><summary>{t("Technical details")}</summary><p>{pilot.error?.message ?? creativeJobs.error?.message}</p></details>
    </aside>}

    {exceptions.length > 0 && <Panel className="today-alert">
      <span><TriangleAlert size={20} /></span>
      <div><strong>{t("Some work needs attention")}</strong><p>{t("{count} operational or policy issues are blocking progress.", { count: exceptions.length })}</p></div>
      <Link className="secondary-button" to="/exceptions">{t("Inspect issues")} <ArrowRight size={15} /></Link>
    </Panel>}

    <div className="overview-workbench">
      <main className="overview-workbench__main">
        <section className="today-section" aria-labelledby="today-decisions">
          <div className="section-heading">
            <div><p className="eyebrow">{t("Your decisions")}</p><h2 id="today-decisions">{t("Needs your decision")}</h2></div>
            <Link className="text-link" to="/approvals">{t("View all")} <ArrowRight size={15} /></Link>
          </div>
          {approvals.length
            ? <div className="decision-list">{approvals.slice(0, 4).map((item) => <DecisionCard key={item.approval_id} approval={item} previewUrl={previews.get(item.entity_id)} compact />)}</div>
            : <div className="today-clear"><CheckCircle2 /><div><strong>{t("Nothing is waiting for approval")}</strong><p>{t("AI will place the next business decision here.")}</p></div></div>}
        </section>

        <section className="today-work-panel" aria-label={t("AI is working")}>
          <PanelHeader title="AI is working" meta={t("{count} active items", { count: active.length })} action={<Link className="text-link" to="/workflows">{t("Open activity")} <ArrowRight size={15} /></Link>} />
          <div className="workflow-compact-list">
            {active.slice(0, 4).map((flow) => <Link to={flow.action_path} key={flow.workflow_id} className="workflow-compact">
              <span className="flow-icon"><Sparkles size={17} /></span>
              <div className="flow-copy"><div><strong>{flow.title}</strong><StatusBadge status={flow.status} /></div><p>{t(businessStage(flow.business_stage))} · {dashboardStreamLabels[flow.workstream]}</p></div>
              <ArrowRight size={15} />
            </Link>)}
            {!active.length && <div className="today-inline-empty"><span><Sparkles size={18} /></span><div><strong>{t("No active work")}</strong><p>{t("New activity will appear when an automated workflow starts.")}</p></div></div>}
          </div>
        </section>
      </main>

      <Panel className="overview-shortcuts">
        <PanelHeader title="Quick access" meta="Common marketing tasks" />
        <nav aria-label={t("Quick access")}>
          {quickActions.map(({ to, icon: Icon, label, detail }) => <Link key={to} to={to}>
            <span><Icon size={17} /></span>
            <div><strong>{t(label)}</strong><small>{t(detail)}</small></div>
            <ArrowRight size={15} />
          </Link>)}
        </nav>
      </Panel>
    </div>

    <section className="today-results-section" aria-labelledby="today-results">
      <div className="section-heading">
        <div><p className="eyebrow">{t("Latest output")}</p><h2 id="today-results">{t("Recent creative results")}</h2></div>
        <Link className="text-link" to="/creatives">{t("Open library")} <ArrowRight size={15} /></Link>
      </div>
      {latestCreatives.length ? <div className="today-creative-strip">{latestCreatives.map((job) => <article key={job.job_id}>
        <Link to={`/creatives/${job.job_id}`}>
          <CreativeMedia type="static" src={job.thumbnail_web_url!} alt={job.display_title} compact />
          <span>{job.display_title}</span>
        </Link>
        <button type="button" onClick={() => { if (window.confirm(t("Hide this creative from the dashboard?"))) hideCreative(job.job_id); }} aria-label={t("Hide this creative from the dashboard")} title={t("Hide this creative from the dashboard")}><Trash2 size={14} /></button>
      </article>)}</div> : <Link className="today-result-empty" to="/creative-production"><span><ImageIcon size={18} /></span><div><strong>{t("No creative results yet")}</strong><p>{t("Start a production request and completed output will appear here.")}</p></div><ArrowRight size={16} /></Link>}
    </section>

    <details className="system-disclosure" open={!systemHealthy}>
      <summary><span className={systemHealthy ? "system-state system-state--healthy" : "system-state system-state--warning"} />
        <strong>{t(systemHealthy ? "Systems are operating normally" : "System health needs attention")}</strong>
        <Badge tone={systemHealthy ? "success" : "warning"}>{healthySources}/{sources.length || "—"} {t("sources healthy")}</Badge>
      </summary>
      <div><span>{t("Active automation commands")}: {pilot.data?.summary.active_commands ?? 0}</span><span>{t("Failed commands")}: {pilot.data?.summary.failed_commands ?? 0}</span><Link className="text-link" to="/data-sources">{t("View system details")} <ArrowRight size={14} /></Link></div>
    </details>
  </>;
}
