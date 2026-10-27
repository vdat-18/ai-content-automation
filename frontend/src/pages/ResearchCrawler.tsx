import { useMemo, useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Copy, ExternalLink, FileStack, Globe2, Image, Link2, LoaderCircle, RotateCcw, Square, Video } from "lucide-react";
import { Link } from "react-router-dom";
import { ResearchRecordCatalog } from "../components/ResearchRecordCatalog";
import { PageHeader } from "../components/ui";
import { useWorkspace } from "../hooks/useWorkspace";
import { pilotApi } from "../services/pilotApi";
import type { ResearchCrawlCreateRequest, ResearchCrawlJob, ResearchMediaMode } from "../types/pilotApi";

const activeStatuses = new Set(["queued", "pending", "running", "retry_wait"]);

export function ResearchCrawlerPage() {
  const queryClient = useQueryClient();
  const { brand, notify } = useWorkspace();
  const brands = useQuery({
    queryKey: ["source-brands"],
    queryFn: ({ signal }) => pilotApi.sourcePerformanceCandidates({ limit: 1 }, signal),
    select: (data) => data.brands,
  });
  const [pickedBrand, setBrandId] = useState<string | null>(null);
  const brandId = pickedBrand ?? (brands.data?.includes(brand) ? brand : brands.data?.[0] ?? "");
  const [projectId, setProjectId] = useState("");
  const [sourceUrl, setSourceUrl] = useState("");
  const [mediaMode, setMediaMode] = useState<ResearchMediaMode>("images_and_videos");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const crawls = useQuery({
    queryKey: ["research-crawls"],
    queryFn: ({ signal }) => pilotApi.researchCrawls(signal),
    refetchInterval: (query) => query.state.data?.items.some((item) => activeStatuses.has(item.status)) ? 2000 : 15000,
  });
  const create = useMutation({
    mutationFn: (payload: ResearchCrawlCreateRequest) => pilotApi.createResearchCrawl(payload),
    onSuccess: async (job) => {
      setSelectedId(job.job_id);
      setSourceUrl("");
      await queryClient.invalidateQueries({ queryKey: ["research-crawls"] });
      notify(job.status === "failed" ? "Crawl failed. Open the job for details." : "Crawl job created.", job.status === "failed" ? "error" : "success");
    },
    onError: () => notify("The crawl job could not be created.", "error"),
  });
  const selected = useMemo(
    () => crawls.data?.items.find((item) => item.job_id === selectedId) ?? crawls.data?.items[0] ?? null,
    [crawls.data?.items, selectedId],
  );

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const payload: ResearchCrawlCreateRequest = {
      workspace_id: "marketing",
      brand_id: brandId.trim(),
      source_url: sourceUrl.trim(),
      media_mode: mediaMode,
    };
    if (projectId.trim()) payload.project_id = projectId.trim();
    create.mutate(payload);
  };

  return (
    <section className="research-page">
      <PageHeader
        eyebrow="Market research"
        title="Research crawler"
        variant="library"
      />

      <div className="research-layout">
        <div className="panel research-create-panel">
          <div className="panel-heading"><div><h2>Collect new research</h2></div><Globe2 size={22} /></div>
          <form className="research-form" onSubmit={submit}>
            <fieldset className="research-project-picker">
              <legend>Project</legend>
              <div role="group" aria-label="Choose project">
                {brands.data?.map((item) => <button key={item} type="button" aria-pressed={brandId === item} className={brandId === item ? "is-selected" : ""} onClick={() => { setBrandId(item); }}><strong>{item}</strong></button>)}
              </div>
            </fieldset>
            <label><span>Research focus (optional)</span><input maxLength={120} value={projectId} onChange={(event) => setProjectId(event.target.value)} placeholder="Example: competitor desk visuals" /></label>
            <label><span>Media to collect</span><select value={mediaMode} onChange={(event) => setMediaMode(event.target.value as ResearchMediaMode)}><option value="images">Images only</option><option value="videos">Videos only</option><option value="images_and_videos">Images and videos</option></select></label>
            <label className="research-url-field"><span>Public results URL</span><input required type="url" maxLength={4096} value={sourceUrl} onChange={(event) => setSourceUrl(event.target.value)} placeholder="Paste the final public search, category, or listing URL" /></label>
            <button className="primary-button" disabled={create.isPending || !brandId.trim() || !sourceUrl.trim()}>
              {create.isPending && <LoaderCircle className="spin" size={16} />} Start crawl
            </button>
          </form>
        </div>

        <div className="panel research-jobs-panel">
          <div className="panel-heading"><div><h2>Recent crawls</h2><p>{crawls.data?.total ?? 0} crawl jobs</p></div></div>
          {crawls.isLoading && <p className="mkt-muted">Loading crawls…</p>}
          {crawls.isError && <p className="form-error">Could not load crawl jobs.</p>}
          <div className="research-job-list">
            {crawls.data?.items.map((job) => (
              <button key={job.job_id} type="button" className={selected?.job_id === job.job_id ? "is-selected" : ""} onClick={() => setSelectedId(job.job_id)}>
                <span><strong>{job.result?.title || hostname(job.source_url)}</strong><small>{job.brand_id} · {job.project_id || "General research"} · {mediaModeLabel(job.media_mode)}</small></span>
                <span className={`badge status-${job.status}`}>{job.status.replaceAll("_", " ")}</span>
              </button>
            ))}
            {!crawls.isLoading && !crawls.data?.items.length && <p className="mkt-muted">No crawls yet.</p>}
          </div>
        </div>
      </div>

      {selected && <ResearchResult key={selected.job_id} job={selected} onChanged={() => queryClient.invalidateQueries({ queryKey: ["research-crawls"] })} />}
    </section>
  );
}

function ResearchResult({ job, onChanged }: { job: ResearchCrawlJob; onChanged: () => Promise<unknown> }) {
  const result = job.result;
  const isActive = activeStatuses.has(job.status);
  const isComplete = job.status === "completed";
  const action = useMutation({
    mutationFn: (kind: "retry" | "cancel") => {
      if (!job.command_id) throw new Error("This job has no durable command.");
      return kind === "retry" ? pilotApi.retryExecutionCommand(job.command_id) : pilotApi.cancelExecutionCommand(job.command_id);
    },
    onSuccess: onChanged,
  });
  return (
    <div className="panel research-result-panel">
      <div className="panel-heading"><div><p className="eyebrow">{job.brand_id} · {job.project_id || "General research"}</p><h2>{result?.title || hostname(job.source_url)}</h2></div>
        <div className="research-result-actions"><a className="secondary-button" href={job.source_url} target="_blank" rel="noreferrer">Open source <ExternalLink size={15} /></a>
          {isComplete && result && result.records.length > 0 && <Link className="secondary-button" to="/research-library">Open review queue</Link>}
          {job.command_id && job.status === "failed" && <button className="secondary-button" type="button" disabled={action.isPending} onClick={() => action.mutate("retry")}><RotateCcw size={15} /> Retry</button>}
          {job.command_id && isActive && <button className="secondary-button" type="button" disabled={action.isPending} onClick={() => action.mutate("cancel")}><Square size={14} /> Cancel</button>}
        </div>
      </div>
      {job.error_message && <p className="research-error">{job.error_message}</p>}
      {isActive && <CrawlProgress job={job} />}
      {isComplete && result && <>
        <p className={`research-discovery-state ${result.records_complete === false ? "research-discovery-state--warning" : ""}`}>{discoverySummary(result.records_complete, job.progress.stop_reason, result.records.length, job.progress.expected_records)}</p>
        <div className="research-stats">
          <div><FileStack size={17} /><strong>{job.progress.saved_records}</strong><span>Saved to review</span></div>
          <div><Copy size={17} /><strong>{job.progress.duplicate_records}</strong><span>Duplicates removed</span></div>
          <div><FileStack size={17} /><strong>{job.progress.unchanged_records}</strong><span>Already existed</span></div>
          <div><FileStack size={17} /><strong>{job.progress.auto_filtered_records}</strong><span>Filtered by analysis</span></div>
          <div><FileStack size={17} /><strong>{job.progress.analysis_unavailable_records}</strong><span>Waiting for analysis</span></div>
          <div><Image size={17} /><strong>{result.image_urls.length}</strong><span>Accepted images</span></div>
          <div><Video size={17} /><strong>{result.video_urls.length}</strong><span>Accepted videos</span></div>
          <div><Link2 size={17} /><strong>{job.progress.failed_records}</strong><span>Media issues</span></div>
          <div><Globe2 size={17} /><strong>{result.platform.replaceAll("_", " ")}</strong><span>Source</span></div>
        </div>
        {job.progress.analysis_unavailable_records > 0 && <p className="research-discovery-state research-discovery-state--warning">{job.progress.analysis_unavailable_records} reference{job.progress.analysis_unavailable_records === 1 ? " is" : "s are"} quarantined until analysis succeeds. <Link to="/research-library">Retry them in Research Library</Link> or inspect <Link to="/ai-usage">AI usage and traces</Link> with run ID <code>{job.job_id}</code>.</p>}
        {result.description && <p className="research-description">{result.description}</p>}
        {result.records.length > 0 && <details open><summary>Ready for Marketing review ({result.records.length})</summary>
          <ResearchRecordCatalog records={result.records} />
        </details>}
        <details><summary>Technical details</summary>
          <details><summary>Extracted text</summary><pre>{result.text || "No visible text found."}</pre></details>
          <details><summary>Structured data ({result.json_ld.length})</summary><pre>{JSON.stringify(result.json_ld, null, 2)}</pre></details>
          <details><summary>Media URLs ({result.image_urls.length + result.video_urls.length})</summary><pre>{[...result.image_urls, ...result.video_urls].join("\n") || "No media URLs found."}</pre></details>
          <details><summary>Run and raw artifact</summary><code>{job.job_id}</code><br /><code>{result.raw_artifact_ref}</code></details>
        </details>
      </>}
    </div>
  );
}

function mediaModeLabel(mode: ResearchMediaMode) {
  if (mode === "images") return "Images";
  if (mode === "videos") return "Videos";
  return "Images + videos";
}

function CrawlProgress({ job }: { job: ResearchCrawlJob }) {
  const progress = job.progress;
  const maximum = progress.expected_records ?? Math.max(progress.discovered_records, 1);
  const percent = Math.min(100, Math.round((progress.discovered_records / maximum) * 100));
  return <div className="research-progress" aria-live="polite">
    <div><strong>{phaseLabel(progress.phase)}</strong><span>{progress.expected_records ? `${progress.discovered_records} of ${progress.expected_records} expected` : `${progress.discovered_records} source items found`} · {progress.media_candidates} unique media candidates · {progress.duplicate_records} duplicates removed · {progress.media_captured} captured · {progress.media_analysis_completed} analyzed · {progress.scroll_count} discovery steps{progress.phase === "classifying" ? ` · ${progress.auto_filtered_records} filtered · ${progress.analysis_unavailable_records} waiting for analysis` : ""}{progress.navigation_action ? ` · Jev chose ${progress.navigation_action.replaceAll("_", " ")}` : ""}</span></div>
    <progress max={100} value={percent} />
  </div>;
}

function phaseLabel(phase: ResearchCrawlJob["progress"]["phase"]) {
  return {
    queued: "Waiting to start",
    opening_browser: "Opening the public page",
    navigating: "Finding more results",
    loading_results: "Loading results",
    scrolling: "Finding more results",
    extracting: "Reading result details",
    saving: "Saving research",
    capturing_media: "Saving images and videos",
    classifying: "Analyzing references",
    completed: "Crawl complete",
    failed: "Crawl failed",
  }[phase];
}

function discoverySummary(recordsComplete: boolean | null, stopReason: string | null, records: number, expectedRecords: number | null) {
  if (recordsComplete === true) {
    return `Discovery complete. Jev finished this source and ${records} reference${records === 1 ? " was" : "s were"} saved for Marketing review${expectedRecords ? ` (${expectedRecords} expected)` : ""}.`;
  }
  if (recordsComplete === false) {
    return `This source may contain more results. ${records} references were saved before discovery stopped${stopReason ? ` (${stopReason.replaceAll("_", " ")})` : ""}.`;
  }
  return `Discovery finished with ${records} saved reference${records === 1 ? "" : "s"}.`;
}

function hostname(value: string) {
  try { return new URL(value).hostname; } catch { return value; }
}
