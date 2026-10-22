import { useMemo, useState } from "react";
import { Activity, Box, CircleDollarSign, Clock3, Cpu, TriangleAlert } from "lucide-react";
import {
  useAIUsage,
  useAIUsageEvent,
  useAIUsageEvents,
  useAIUsageRuns,
} from "../hooks/usePilotDashboard";
import { useI18n } from "../hooks/useI18n";
import { useWorkspace } from "../hooks/useWorkspace";
import type { AIUsageBreakdown, AIUsageCost, AIUsageEvent, AIUsageRun } from "../types/pilotApi";

const periods = [7, 30, 90] as const;
type UsageView = "overview" | "runs" | "calls";

export function AIUsagePage() {
  const [days, setDays] = useState<(typeof periods)[number]>(30);
  const [view, setView] = useState<UsageView>("overview");
  const [workstream, setWorkstream] = useState("");
  const [model, setModel] = useState("");
  const [operation, setOperation] = useState("");
  const [backend, setBackend] = useState("");
  const [status, setStatus] = useState("");
  const [costState, setCostState] = useState("");
  const [correlationId, setCorrelationId] = useState("");
  const [selectedEventId, setSelectedEventId] = useState<string | null>(null);
  const { t } = useI18n();
  const { brand } = useWorkspace();

  const query = useMemo(() => {
    const to = new Date();
    const from = new Date(to.getTime() - days * 86_400_000);
    const params = new URLSearchParams({ from: from.toISOString(), to: to.toISOString() });
    if (workstream) params.set("workstream", workstream);
    if (model) params.set("model", model);
    if (operation) params.set("operation", operation);
    if (backend) params.set("backend", backend);
    if (status) params.set("status", status);
    if (costState) params.set("cost_state", costState);
    if (correlationId.trim()) params.set("correlation_id", correlationId.trim());
    if (brand !== "all") params.set("brand_id", brand);
    return params.toString();
  }, [backend, brand, correlationId, costState, days, model, operation, status, workstream]);

  const usage = useAIUsage(query);
  const events = useAIUsageEvents(`${query}&limit=50`);
  const runs = useAIUsageRuns(`${query}&limit=50`);
  const selectedEvent = useAIUsageEvent(selectedEventId);
  const data = usage.data;
  const successBase = (data?.succeeded ?? 0) + (data?.failed ?? 0);
  const successRate = successBase ? Math.round(((data?.succeeded ?? 0) / successBase) * 100) : null;
  const models = data?.by_model.map((item) => item.key) ?? [];
  const workstreams = data?.by_workstream.map((item) => item.key) ?? [];
  const operations = data?.by_operation.map((item) => item.key) ?? [];
  const backends = data?.by_backend.map((item) => item.key) ?? [];

  const openEvent = (eventId: string) => {
    setSelectedEventId(eventId);
    setView("calls");
  };
  const openRun = (runId: string) => {
    setCorrelationId(runId);
    setSelectedEventId(null);
    setView("calls");
  };

  return (
    <>
      <header className="page-header page-header--operator ai-usage-header">
        <div>
          <p className="eyebrow">{t("OPERATIONS · AI GOVERNANCE")}</p>
          <h1>{t("AI usage & cost")}</h1>
          <p>{t("Trace provider calls, linked runs, tokens, latency and provider-reported cost. Unknown cost is never treated as zero.")}</p>
        </div>
        <div className="usage-filters">
          <div className="segmented" aria-label="Reporting period">
            {periods.map((period) => <button key={period} className={period === days ? "active" : ""} onClick={() => setDays(period)}>{period} days</button>)}
          </div>
          <select aria-label="Workstream filter" value={workstream} onChange={(event) => setWorkstream(event.target.value)}><option value="">All workstreams</option>{workstreams.map((item) => <option key={item}>{item}</option>)}</select>
          <select aria-label="Model filter" value={model} onChange={(event) => setModel(event.target.value)}><option value="">All models</option>{models.map((item) => <option key={item}>{item}</option>)}</select>
          <select aria-label="Operation filter" value={operation} onChange={(event) => setOperation(event.target.value)}><option value="">All operations</option>{operations.map((item) => <option key={item}>{item}</option>)}</select>
          <select aria-label="Backend filter" value={backend} onChange={(event) => setBackend(event.target.value)}><option value="">All backends</option>{backends.map((item) => <option key={item}>{item}</option>)}</select>
          <select aria-label="Status filter" value={status} onChange={(event) => setStatus(event.target.value)}><option value="">All states</option><option value="succeeded">Succeeded</option><option value="failed">Failed</option><option value="started">Incomplete</option></select>
          <select aria-label="Cost coverage filter" value={costState} onChange={(event) => setCostState(event.target.value)}><option value="">All cost states</option><option value="priced">Provider-reported cost</option><option value="unpriced">Cost unknown</option></select>
          <label className="usage-trace-filter"><span>Trace ID</span><input value={correlationId} onChange={(event) => setCorrelationId(event.target.value)} placeholder="Run, job or workflow ID" /></label>
        </div>
      </header>

      {usage.isLoading && <section className="panel empty-state"><Activity /><h3>Loading the AI usage ledger…</h3></section>}
      {usage.error && <section className="error-panel" role="alert"><h2>Could not load AI usage</h2><p>{usage.error.message}</p><button className="primary-button" onClick={() => void usage.refetch()}>Try again</button></section>}

      {data && <>
        <section className="usage-coverage" aria-label="Usage data coverage">
          <Coverage label="Token coverage" value={percentage(data.token_reported_attempts, data.attempts)} detail={`${formatNumber(data.token_reported_attempts)} of ${formatNumber(data.attempts)} calls`} />
          <Coverage label="Latency coverage" value={percentage(data.duration_reported_attempts, data.attempts)} detail={`${formatNumber(data.duration_reported_attempts)} completed calls`} />
          <Coverage label="Trace coverage" value={percentage(data.linked_attempts, data.attempts)} detail={`${formatNumber(data.linked_attempts)} calls linked to a run or record`} />
          <Coverage label="Cost coverage" value={percentage(data.attempts - data.unpriced_attempts, data.attempts)} detail={`${formatNumber(data.unpriced_attempts)} calls remain unpriced`} alert={data.unpriced_attempts > 0} />
        </section>

        <section className="metric-grid usage-metrics">
          <Metric label="Provider calls" value={formatNumber(data.attempts)} detail={`${formatNumber(data.request_count)} provider requests`} icon={<Cpu size={15} />} />
          <Metric label="Success rate" value={successRate === null ? "N/A" : `${successRate}%`} detail={`${formatNumber(data.failed)} failed · ${formatNumber(data.incomplete)} incomplete`} tone="green" icon={<Activity size={15} />} />
          <Metric label="Tokens" value={formatNumber(data.input_tokens + data.output_tokens)} detail={`${formatNumber(data.input_tokens)} in · ${formatNumber(data.output_tokens)} out`} tone="blue" icon={<Cpu size={15} />} />
          <Metric label="P95 call duration" value={formatDuration(data.p95_duration_ms)} detail={`P50 ${formatDuration(data.p50_duration_ms)}`} tone="blue" icon={<Clock3 size={15} />} />
          <Metric label="Reported outputs" value={formatNumber(data.output_count)} detail={`${formatBytes(data.output_bytes)} persisted output bytes`} icon={<Box size={15} />} />
          <Metric label="Provider-reported cost" value={formatCosts(data.costs)} detail="Kept separate by currency" tone="coral" icon={<CircleDollarSign size={15} />} />
          <Metric label="Cost unknown" value={formatNumber(data.unpriced_attempts)} detail="Unknown is not treated as zero" alert icon={<TriangleAlert size={15} />} />
        </section>

        <nav className="usage-tabs" aria-label="AI usage views">
          <button className={view === "overview" ? "active" : ""} onClick={() => setView("overview")}>Overview</button>
          <button className={view === "runs" ? "active" : ""} onClick={() => setView("runs")}>Runs & jobs <span>{runs.data?.total ?? 0}</span></button>
          <button className={view === "calls" ? "active" : ""} onClick={() => setView("calls")}>Provider calls <span>{events.data?.total ?? 0}</span></button>
        </nav>

        {data.attempts === 0 ? <section className="panel empty-state"><Cpu /><h3>No provider calls in this period</h3><p>Fake adapters and human reviews are intentionally excluded from the ledger.</p></section> : <>
          {view === "overview" && <Overview data={data} onBreakdownSelect={(kind, key) => {
            if (kind === "model") setModel(key);
            if (kind === "operation") setOperation(key);
            if (kind === "backend") setBackend(key);
          }} onEventOpen={openEvent} />}
          {view === "runs" && <RunsPanel runs={runs.data?.items ?? []} total={runs.data?.total ?? 0} loading={runs.isLoading} error={runs.error?.message} onOpen={openRun} />}
          {view === "calls" && <CallsPanel events={events.data?.items ?? []} total={events.data?.total ?? 0} loading={events.isLoading} error={events.error?.message} onOpen={openEvent} />}
          {view === "calls" && selectedEventId && <EventDetail event={selectedEvent.data ?? events.data?.items.find((item) => item.event_id === selectedEventId) ?? null} loading={selectedEvent.isLoading} error={selectedEvent.error?.message} onClose={() => setSelectedEventId(null)} />}
        </>}
      </>}
    </>
  );
}

function Overview({ data, onBreakdownSelect, onEventOpen }: { data: AIUsageData; onBreakdownSelect: (kind: "model" | "operation" | "backend", key: string) => void; onEventOpen: (eventId: string) => void }) {
  return <>
    <section className="usage-grid usage-grid--three"><Breakdown title="By model" rows={data.by_model} onSelect={(key) => onBreakdownSelect("model", key)} /><Breakdown title="By operation" rows={data.by_operation} onSelect={(key) => onBreakdownSelect("operation", key)} /><Breakdown title="By backend" rows={data.by_backend} onSelect={(key) => onBreakdownSelect("backend", key)} /></section>
    <section className="usage-grid"><Breakdown title="By workstream" rows={data.by_workstream} /><Trend rows={data.by_day} /></section>
    <section className="panel usage-panel"><div className="usage-panel-heading"><div><h2>Recent failures</h2><p>Open a call to inspect its model, trace IDs, duration and reported usage.</p></div></div>{data.recent_failures.length ? <div className="usage-failures"><div><span>Time</span><span>Operation</span><span>Trace</span><span>Duration</span><span>Error</span></div>{data.recent_failures.map((item) => <button key={item.event_id} onClick={() => onEventOpen(item.event_id)}><span>{formatTime(item.started_at)}</span><strong>{item.operation}</strong><code>{shortId(item.run_id ?? item.job_id ?? item.workflow_run_id ?? item.source_run_id)}</code><span>{formatDuration(item.duration_ms)}</span><code>{item.error_code ?? "unknown"}</code></button>)}</div> : <p className="usage-empty-line">No failed provider calls in this period.</p>}</section>
  </>;
}

type AIUsageData = NonNullable<ReturnType<typeof useAIUsage>["data"]>;

function Coverage({ label, value, detail, alert = false }: { label: string; value: string; detail: string; alert?: boolean }) { return <div className={alert ? "usage-coverage__item usage-coverage__item--alert" : "usage-coverage__item"}><strong>{value}</strong><span>{label}</span><small>{detail}</small></div>; }
function Metric({ label, value, detail, icon, tone = "", alert = false }: { label: string; value: string; detail: string; icon: React.ReactNode; tone?: "green" | "blue" | "coral" | ""; alert?: boolean }) { return <article className={`metric-card ${tone ? `metric-card--${tone}` : ""} ${alert ? "metric-card--alert" : ""}`}><p>{label}</p><strong>{value}</strong><div>{icon}<small>{detail}</small></div></article>; }

function Breakdown({ title, rows, onSelect }: { title: string; rows: AIUsageBreakdown[]; onSelect?: (key: string) => void }) {
  return <section className="panel usage-panel"><div className="usage-panel-heading"><h2>{title}</h2></div>{rows.length ? <div className="usage-table"><div><span>Name</span><span>Calls</span><span>Success</span><span>Tokens</span><span>Avg. call</span><span>Cost</span></div>{rows.map((item) => { const decided = item.succeeded + item.failed; return <button key={item.key} disabled={!onSelect} onClick={() => onSelect?.(item.key)}><strong>{item.key}</strong><span>{item.attempts}</span><span>{decided ? `${Math.round(item.succeeded / decided * 100)}%` : "N/A"}</span><span>{formatNumber(item.input_tokens + item.output_tokens)}</span><span>{formatDuration(averageDuration(item))}</span><span>{formatCosts(item.costs)}</span></button>; })}</div> : <p className="usage-empty-line">No matching records.</p>}</section>;
}

function Trend({ rows }: { rows: AIUsageBreakdown[] }) {
  const maximum = Math.max(...rows.map((item) => item.attempts), 1);
  return <section className="panel usage-panel"><div className="usage-panel-heading"><h2>Daily provider calls</h2></div><div className="usage-bars">{rows.map((item) => <div key={item.key}><span>{item.key}</span><div className="usage-bar-track"><i style={{ width: `${Math.max((item.succeeded / maximum) * 100, 0)}%` }} /><b style={{ width: `${Math.max((item.failed / maximum) * 100, 0)}%` }} /></div><strong>{item.attempts}</strong></div>)}</div></section>;
}

function RunsPanel({ runs, total, loading, error, onOpen }: { runs: AIUsageRun[]; total: number; loading: boolean; error?: string; onOpen: (runId: string) => void }) {
  return <section className="panel usage-panel"><div className="usage-panel-heading"><h2>Runs & jobs</h2><span className="usage-total">{formatNumber(total)} traced runs</span></div>{loading ? <p className="usage-empty-line">Loading runs…</p> : error ? <p className="usage-error">{error}</p> : runs.length ? <div className="usage-run-table"><div><span>Run</span><span>Status</span><span>Models & operations</span><span>Calls</span><span>Tokens</span><span>Duration</span><span>Cost</span></div>{runs.map((run) => <button key={run.run_id} onClick={() => onOpen(run.run_id)}><code>{shortId(run.run_id)}</code><Status value={run.status} /><span><strong>{run.models.join(", ")}</strong><small>{run.operations.join(" · ")}</small></span><span>{run.attempts}<small>{run.failed ? `${run.failed} failed` : ""}</small></span><span>{formatNumber(run.input_tokens + run.output_tokens)}</span><span>{formatDuration(run.total_duration_ms)}</span><span>{formatCosts(run.costs)}</span></button>)}</div> : <p className="usage-empty-line">No traced runs match these filters.</p>}</section>;
}

function CallsPanel({ events, total, loading, error, onOpen }: { events: AIUsageEvent[]; total: number; loading: boolean; error?: string; onOpen: (eventId: string) => void }) {
  return <section className="panel usage-panel"><div className="usage-panel-heading"><h2>Provider calls</h2><span className="usage-total">{formatNumber(total)} calls</span></div>{loading ? <p className="usage-empty-line">Loading provider calls…</p> : error ? <p className="usage-error">{error}</p> : events.length ? <div className="usage-event-table"><div><span>Time</span><span>Status</span><span>Trace</span><span>Operation</span><span>Model</span><span>Tokens</span><span>Duration</span><span>Cost</span></div>{events.map((event) => <button key={event.event_id} onClick={() => onOpen(event.event_id)}><span>{formatTime(event.started_at)}</span><Status value={event.status} /><code>{shortId(event.run_id ?? event.job_id ?? event.workflow_run_id ?? event.source_run_id)}</code><strong>{event.operation}</strong><span>{event.model}</span><span>{formatNumber((event.input_tokens ?? 0) + (event.output_tokens ?? 0))}</span><span>{formatDuration(event.duration_ms)}</span><span>{formatEventCost(event)}</span></button>)}</div> : <p className="usage-empty-line">No provider calls match these filters.</p>}</section>;
}

function EventDetail({ event, loading, error, onClose }: { event: AIUsageEvent | null; loading: boolean; error?: string; onClose: () => void }) {
  return <section className="panel usage-event-detail" aria-live="polite"><div className="usage-panel-heading"><div><h2>Provider call detail</h2><p>This ledger intentionally stores metadata and references, not raw prompts or model output.</p></div><button className="secondary-button" onClick={onClose}>Close</button></div>{loading && !event ? <p className="usage-empty-line">Loading event detail…</p> : error ? <p className="usage-error">{error}</p> : event ? <><div className="usage-detail-status"><Status value={event.status} /><code>{event.event_id}</code></div><dl className="usage-detail-grid"><Detail label="Operation" value={event.operation} /><Detail label="Backend" value={event.backend} /><Detail label="Model" value={event.model_revision ? `${event.model} · ${event.model_revision}` : event.model} /><Detail label="Started" value={formatTime(event.started_at)} /><Detail label="Completed" value={event.completed_at ? formatTime(event.completed_at) : "In progress"} /><Detail label="Provider-call duration" value={formatDuration(event.duration_ms)} /><Detail label="Input tokens" value={event.input_tokens === null ? "Not reported" : formatNumber(event.input_tokens)} /><Detail label="Output tokens" value={event.output_tokens === null ? "Not reported" : formatNumber(event.output_tokens)} /><Detail label="Outputs" value={`${formatNumber(event.output_count ?? 0)} · ${formatBytes(event.output_bytes ?? 0)}`} /><Detail label="Provider-reported cost" value={formatEventCost(event)} /><Detail label="Attempt" value={event.attempt_number ? String(event.attempt_number) : "Not recorded"} /><Detail label="Error" value={event.error_code ?? "None"} /></dl><div className="usage-lineage"><h3>Traceability</h3><Detail label="Batch ID" value={event.batch_id ?? "Not recorded"} /><Detail label="Run ID" value={event.run_id ?? "Not recorded"} /><Detail label="Job ID" value={event.job_id ?? "Not recorded"} /><Detail label="Workflow run" value={event.workflow_run_id ?? "Not recorded"} /><Detail label="Source run" value={event.source_run_id ?? "Not recorded"} /><Detail label="Version" value={event.version_id ?? "Not recorded"} /><Detail label="Parent event" value={event.parent_event_id ?? "Not recorded"} /><Detail label="Provider request" value={event.provider_request_id ?? "Not reported"} /></div></> : null}</section>;
}

function Detail({ label, value }: { label: string; value: string }) { return <div><dt>{label}</dt><dd>{value}</dd></div>; }
function Status({ value }: { value: string }) { return <span className={`usage-status usage-status--${value}`}>{value === "started" ? "incomplete" : value}</span>; }
function averageDuration(item: AIUsageBreakdown) { return item.duration_reported_attempts ? Math.round(item.total_duration_ms / item.duration_reported_attempts) : null; }
function percentage(value: number, total: number) { return total ? `${Math.round((value / total) * 100)}%` : "N/A"; }
function formatNumber(value: number) { return new Intl.NumberFormat().format(value); }
function formatTime(value: string) { return new Date(value).toLocaleString(); }
function formatDuration(value: number | null) { if (value === null) return "Not reported"; if (value < 1_000) return `${value} ms`; if (value < 60_000) return `${(value / 1_000).toFixed(value < 10_000 ? 1 : 0)} s`; return `${Math.floor(value / 60_000)}m ${Math.round((value % 60_000) / 1_000)}s`; }
function formatBytes(value: number) { if (!value) return "Not reported"; if (value < 1_024) return `${value} B`; if (value < 1_048_576) return `${(value / 1_024).toFixed(1)} KB`; return `${(value / 1_048_576).toFixed(1)} MB`; }
function formatCosts(costs: AIUsageCost[]) { if (!costs.length) return "Unknown"; return costs.map((item) => `${item.currency} ${Number(item.amount).toLocaleString(undefined, { maximumFractionDigits: 4 })}`).join(" · "); }
function formatEventCost(event: AIUsageEvent) { return event.cost_amount !== null && event.cost_currency ? `${event.cost_currency} ${Number(event.cost_amount).toLocaleString(undefined, { maximumFractionDigits: 4 })}` : "Unknown"; }
function shortId(value: string | null) { return value ? (value.length > 20 ? `${value.slice(0, 10)}…${value.slice(-7)}` : value) : "Unlinked"; }
