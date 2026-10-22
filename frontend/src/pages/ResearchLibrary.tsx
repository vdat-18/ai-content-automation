import { useEffect, useMemo, useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, Download, Filter, LibraryBig, Search, Trash2 } from "lucide-react";
import { Link } from "react-router-dom";
import { ResearchRecordCatalog } from "../components/ResearchRecordCatalog";
import { Badge, PageHeader } from "../components/ui";
import { useWorkspace } from "../hooks/useWorkspace";
import { pilotApi } from "../services/pilotApi";
import type { ResearchCrawlRecord, ResearchReviewDecision } from "../types/pilotApi";

type Filters = {
  brand: string;
  project: string;
  platform: string;
  status: string;
  review: string;
  media: string;
  mediaStatus: string;
  analysis: string;
  query: string;
  sort: string;
};

type ReviewTab = Pick<Filters, "review"> & { label: string };

const reviewTabs: ReviewTab[] = [
  { review: "pending_review", label: "Needs review" },
  { review: "approved", label: "Approved" },
  { review: "rejected", label: "Not useful" },
  { review: "", label: "All" },
];

export function ResearchLibraryPage() {
  const queryClient = useQueryClient();
  const { brand, notify } = useWorkspace();
  const initial = useMemo<Filters>(() => ({
    brand: brand === "all" ? "" : brand,
    project: "",
    platform: "",
    status: "",
    review: "pending_review",
    media: "all",
    mediaStatus: "all",
    analysis: "visible",
    query: "",
    sort: "last_seen_desc",
  }), [brand]);
  const [draft, setDraft] = useState(initial);
  const [filters, setFilters] = useState(initial);
  const [page, setPage] = useState(1);
  const [pageInput, setPageInput] = useState("1");
  const [selectedRecordKeys, setSelectedRecordKeys] = useState<string[]>([]);
  const [bulkReviewer, setBulkReviewer] = useState("");
  const [bulkReason, setBulkReason] = useState("");
  const params = useMemo(() => {
    const value = new URLSearchParams({
      workspace_id: "marketing",
      page: String(page),
      page_size: "48",
      sort: filters.sort,
      media_type: filters.media,
      media_status: filters.mediaStatus,
      screening_status: filters.analysis,
    });
    if (filters.brand) value.set("brand_id", filters.brand);
    if (filters.project) value.set("project_id", filters.project);
    if (filters.platform) value.set("platform", filters.platform);
    if (filters.status) value.set("status", filters.status);
    if (filters.review) value.set("review_status", filters.review);
    if (filters.query) value.set("q", filters.query);
    return value.toString();
  }, [filters, page]);
  const records = useQuery({
    queryKey: ["research-records", params],
    queryFn: ({ signal }) => pilotApi.researchRecords(params, signal),
  });
  const review = useMutation({
    mutationFn: ({ recordKeys, decision, reviewerAlias, reason }: {
      recordKeys: string[];
      decision: ResearchReviewDecision;
      reviewerAlias: string;
      reason: string;
    }) => pilotApi.reviewResearchRecords(recordKeys, {
      decision,
      reviewer_alias: reviewerAlias || undefined,
      reason: reason || undefined,
    }),
    onSuccess: async (_, variables) => {
      setSelectedRecordKeys((keys) => keys.filter((key) => !variables.recordKeys.includes(key)));
      await invalidateResearch(queryClient);
      notify(
        variables.decision === "approve"
          ? "Research is now available in Creative Production."
          : variables.decision === "reject"
            ? "Research was marked as not useful."
            : "Research was returned to the review queue.",
        "success",
      );
    },
    onError: (error) => notify(
      error instanceof Error ? error.message : "Research review could not be saved.",
      "error",
    ),
  });
  const reanalyze = useMutation({
    mutationFn: (recordKey: string) => pilotApi.reanalyzeResearchRecord(recordKey),
    onSuccess: async (record) => {
      await invalidateResearch(queryClient);
      notify(
        record.screening_status === "kept"
          ? "Automatic analysis completed. The reference is ready for Marketing review."
          : "The reference is still waiting for automatic analysis.",
        record.screening_status === "kept" ? "success" : "error",
      );
    },
    onError: (error) => notify(
      error instanceof Error ? error.message : "Automatic analysis could not be retried.",
      "error",
    ),
  });
  const remove = useMutation({
    mutationFn: (recordKeys: string[]) => pilotApi.deleteResearchRecords(recordKeys),
    onSuccess: async (result) => {
      setSelectedRecordKeys([]);
      await invalidateResearch(queryClient);
      notify(`${result.deleted} research reference${result.deleted === 1 ? "" : "s"} deleted.`, "success");
    },
    onError: (error) => notify(
      error instanceof Error ? error.message : "Research references could not be deleted.",
      "error",
    ),
  });
  const pages = Math.max(1, Math.ceil((records.data?.total ?? 0) / (records.data?.page_size ?? 48)));
  useEffect(() => setPageInput(String(page)), [page]);
  useEffect(() => {
    if (page > pages) setPage(pages);
  }, [page, pages]);
  const activeFilterCount = Object.entries(filters).filter(([key, value]) => {
    if (["sort", "review"].includes(key)) return false;
    return value !== "" && value !== "all";
  }).length;
  const catalogRecords = (records.data?.items ?? []).map<ResearchCrawlRecord>((record) => ({
    record_id: record.external_id,
    record_type: record.record_type,
    title: record.title,
    text: record.text,
    source_url: record.source_url,
    links: record.links,
    image_urls: record.image_urls,
    video_urls: record.video_urls,
    metadata: {
      ...record.metadata,
      record_key: record.record_key,
      platform: record.platform,
      advertiser: record.advertiser,
      destination_domain: record.destination_domain,
      first_seen_at: record.first_seen_at,
      last_seen_at: record.last_seen_at,
      version_count: record.version_count,
      latest_run_id: record.latest_run_id,
      media_assets: record.media_assets,
      screening_status: record.screening_status,
      screening: record.screening,
      review_status: record.review_status,
      reviewer_alias: record.reviewer_alias,
      reviewed_at: record.reviewed_at,
      review_reason: record.review_reason,
    },
  }));

  const apply = (event: FormEvent) => {
    event.preventDefault();
    setFilters(draft);
    setPage(1);
    setSelectedRecordKeys([]);
  };

  const reset = () => {
    setDraft(initial);
    setFilters(initial);
    setPage(1);
    setSelectedRecordKeys([]);
  };

  const setReviewFilter = (tab: ReviewTab) => {
    const next = { ...filters, review: tab.review };
    setDraft(next);
    setFilters(next);
    setPage(1);
    setSelectedRecordKeys([]);
  };

  const changeSelection = (recordKey: string, selected: boolean) => {
    setSelectedRecordKeys((keys) => selected
      ? [...keys, recordKey]
      : keys.filter((key) => key !== recordKey));
  };

  const saveReview = async (
    recordKeys: string[],
    decision: ResearchReviewDecision,
    reviewerAlias: string,
    reason: string,
  ) => {
    try {
      await review.mutateAsync({ recordKeys, decision, reviewerAlias, reason });
      return true;
    } catch {
      return false;
    }
  };

  const deleteRecords = async (recordKeys: string[]) => {
    const label = recordKeys.length === 1 ? "this research reference" : `${recordKeys.length} research references`;
    if (!window.confirm(`Delete ${label} from Research Library? This cannot be undone.`)) return false;
    try {
      await remove.mutateAsync(recordKeys);
      return true;
    } catch {
      return false;
    }
  };

  const jumpToPage = () => {
    const requestedPage = Number.parseInt(pageInput, 10);
    const nextPage = Number.isFinite(requestedPage)
      ? Math.min(pages, Math.max(1, requestedPage))
      : page;
    setPage(nextPage);
    setPageInput(String(nextPage));
  };


  return <section className="research-page research-library-page">
    <PageHeader
      eyebrow="Market research"
      title="Research Library"
      description="Only references accepted by automatic analysis reach Marketing review. Approved images can be used in Creative Production; videos are stored for future use."
      variant="library"
      actions={<div className="research-library-actions"><Badge tone="neutral">{records.data?.total ?? 0} shown</Badge><a className="secondary-button research-export-button" href={`/api/v1/marketing/research-records/export?${params}&format=csv`}><Download size={15} /> Export CSV</a><Link className="primary-button" to="/research-crawler">Collect research</Link></div>}
    />

    <div className="research-review-tabs" role="tablist" aria-label="Research review status">
      {reviewTabs.map((tab) => <button
        key={tab.review || "all"}
        type="button"
        role="tab"
        aria-selected={filters.review === tab.review}
        className={filters.review === tab.review ? "is-active" : ""}
        onClick={() => setReviewFilter(tab)}
      >{tab.label}</button>)}
    </div>

    <form className="panel research-library-filters" onSubmit={apply}>
      <div className="research-library-primary-filters">
        <label className="research-library-search"><span>Search</span><div><Search size={16} /><input value={draft.query} onChange={(event) => setDraft({ ...draft, query: event.target.value })} placeholder="Product, advertiser, or idea…" /></div></label>
        <label><span>Platform</span><select value={draft.platform} onChange={(event) => setDraft({ ...draft, platform: event.target.value })}><option value="">All platforms</option><option value="meta_ad_library">Meta Ad Library</option><option value="google_ads_transparency">Google Ads Transparency</option><option value="etsy">Etsy</option><option value="pinterest">Pinterest</option><option value="tiktok">TikTok</option><option value="amazon">Amazon</option><option value="wayfair">Wayfair</option><option value="houzz">Houzz</option><option value="generic">Other websites</option></select></label>
        <label><span>Media</span><select value={draft.media} onChange={(event) => setDraft({ ...draft, media: event.target.value })}><option value="all">All media</option><option value="image">Images only</option><option value="video">Videos only</option><option value="mixed">Images + videos</option><option value="none">No media</option></select></label>
        <div className="research-library-primary-actions">
          <button className="primary-button"><Filter size={15} /> Apply filters</button>
          {activeFilterCount > 0 && <button className="text-button" type="button" onClick={reset}>Clear filters</button>}
        </div>
      </div>
      <details className="research-library-advanced">
        <summary>More filters {activeFilterCount > 0 && <span>{activeFilterCount}</span>}</summary>
        <div>
          <label><span>Project</span><input value={draft.brand} onChange={(event) => setDraft({ ...draft, brand: event.target.value })} placeholder="All brands" /></label>
          <label><span>Research focus</span><input value={draft.project} onChange={(event) => setDraft({ ...draft, project: event.target.value })} placeholder="All objectives" /></label>
          <label><span>Source status</span><select value={draft.status} onChange={(event) => setDraft({ ...draft, status: event.target.value })}><option value="">All source statuses</option><option value="active">Active</option><option value="inactive">Inactive</option></select></label>
          <label><span>Media storage</span><select value={draft.mediaStatus} onChange={(event) => setDraft({ ...draft, mediaStatus: event.target.value })}><option value="all">Any storage state</option><option value="available">Saved locally</option><option value="failed">Capture failed</option><option value="source_only">Source URLs only</option></select></label>
          <label><span>Automatic analysis</span><select value={draft.analysis} onChange={(event) => setDraft({ ...draft, analysis: event.target.value })}><option value="visible">Accepted for review</option><option value="unavailable">Waiting or failed</option><option value="auto_filtered">Filtered out</option><option value="all">All analysis states</option></select></label>
          <label><span>Sort</span><select value={draft.sort} onChange={(event) => setDraft({ ...draft, sort: event.target.value })}><option value="last_seen_desc">Recently seen</option><option value="first_seen_desc">Recently discovered</option><option value="title_asc">Name A–Z</option></select></label>
        </div>
      </details>
    </form>

    {selectedRecordKeys.length > 0 && <section className="research-bulk-review" aria-label="Review selected research">
      <div><strong>{selectedRecordKeys.length} selected</strong><p>Apply one Marketing review decision to these references.</p></div>
      <label><span>Your name</span><input value={bulkReviewer} maxLength={120} onChange={(event) => setBulkReviewer(event.target.value)} placeholder="Required to approve or reject" /></label>
      <label><span>Note (optional)</span><input value={bulkReason} maxLength={1000} onChange={(event) => setBulkReason(event.target.value)} placeholder="Why is this useful or not useful?" /></label>
      <div className="research-review-actions">
        <button className="approve-button" type="button" disabled={review.isPending || !bulkReviewer.trim()} onClick={() => void saveReview(selectedRecordKeys, "approve", bulkReviewer.trim(), bulkReason.trim())}>Approve for Creative</button>
        <button className="reject-button" type="button" disabled={review.isPending || !bulkReviewer.trim()} onClick={() => void saveReview(selectedRecordKeys, "reject", bulkReviewer.trim(), bulkReason.trim())}>Not useful</button>
        <button className="secondary-button" type="button" disabled={review.isPending} onClick={() => void saveReview(selectedRecordKeys, "review_later", "", "")}>Review later</button>
        <button className="reject-button" type="button" disabled={remove.isPending} onClick={() => void deleteRecords(selectedRecordKeys)}><Trash2 size={15} /> Delete selected</button>
      </div>
    </section>}

    <div className="results-heading"><span>{records.data?.total ?? 0} records{records.isFetching && !records.isLoading ? " · Updating…" : ""}</span><span>Page {page} of {pages}</span></div>

    {records.isLoading && <div className="panel research-library-state">Loading saved research…</div>}
    {records.isError && <div className="panel research-library-state form-error">Could not load saved research.</div>}
    {!records.isLoading && !records.isError && catalogRecords.length === 0 && <div className="panel research-library-empty"><LibraryBig size={34} /><h2>No matching records</h2><p>Run a crawl or change the filters.</p></div>}
    {catalogRecords.length > 0 && <ResearchRecordCatalog
      records={catalogRecords}
      selectedRecordKeys={selectedRecordKeys}
      onSelectionChange={changeSelection}
      onReview={(recordKey, decision, reviewerAlias, reason) => saveReview([recordKey], decision, reviewerAlias, reason)}
      reviewPending={review.isPending}
      onReanalyze={(recordKey) => reanalyze.mutateAsync(recordKey).then(() => true).catch(() => false)}
      reanalysisPending={reanalyze.isPending}
      onDelete={(recordKey) => deleteRecords([recordKey])}
      deletePending={remove.isPending}
    />}

    {records.data && records.data.total > 0 && <nav className="research-pagination" aria-label="Research records pages">
      <button className="secondary-button" type="button" disabled={page <= 1} onClick={() => setPage((value) => Math.max(1, value - 1))}><ChevronLeft size={16} /> Previous</button>
      <label>Page <input type="number" min={1} max={pages} inputMode="numeric" aria-label="Page number" value={pageInput} onChange={(event) => setPageInput(event.target.value)} onBlur={jumpToPage} onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); jumpToPage(); } }} /> of <strong>{pages}</strong></label>
      <button className="secondary-button" type="button" disabled={page >= pages} onClick={() => setPage((value) => Math.min(pages, value + 1))}>Next <ChevronRight size={16} /></button>
    </nav>}
  </section>;
}

async function invalidateResearch(queryClient: ReturnType<typeof useQueryClient>) {
  await Promise.all([
    queryClient.invalidateQueries({ queryKey: ["research-records"] }),
    queryClient.invalidateQueries({ queryKey: ["research-record"] }),
  ]);
}
