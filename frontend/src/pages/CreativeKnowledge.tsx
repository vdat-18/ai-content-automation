import { useMemo, useRef, useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, BrainCircuit, Check, History, Plus, RefreshCw, X } from "lucide-react";
import { SplitHandle } from "../components/SplitHandle";
import { Badge, PageHeader } from "../components/ui";
import { useI18n } from "../hooks/useI18n";
import { useSplitResize } from "../hooks/useSplitResize";
import { useWorkspace } from "../hooks/useWorkspace";
import { pilotApi } from "../services/pilotApi";
import type {
  CreativeKnowledge,
  CreativeKnowledgeAuthority,
  CreativeKnowledgeProposalRequest,
  CreativeKnowledgeScope,
  CreativeKnowledgeStage,
  CreativeKnowledgeStatus,
  CreativeKnowledgeType,
} from "../types/pilotApi";

const knowledgeTypes: CreativeKnowledgeType[] = [
  "fact",
  "hard_rule",
  "team_default",
  "practice",
  "hypothesis",
  "lesson",
  "qa_check",
  "decision",
  "feedback",
];

const authorities: CreativeKnowledgeAuthority[] = [
  "owner",
  "admin",
  "lead",
  "team",
  "individual",
  "external",
];

const knowledgeStages: CreativeKnowledgeStage[] = [
  "persona",
  "preparation",
  "orchestration",
  "review",
  "revision",
  "learning",
  "performance",
];

const statuses: Array<CreativeKnowledgeStatus | "all"> = [
  "all",
  "proposed",
  "approved",
  "conflict",
  "rejected",
  "superseded",
  "draft",
  "expired",
];

const scopeFields: Array<keyof CreativeKnowledgeScope> = [
  "niche_id",
  "brand_id",
  "product_archetype",
  "product_family_id",
  "variant_id",
  "platform",
  "market",
  "asset_type",
  "task_type",
];

type ProposalForm = {
  knowledgeId: string;
  knowledgeType: CreativeKnowledgeType;
  title: string;
  content: string;
  authority: CreativeKnowledgeAuthority;
  contributor: string;
  sourceRefs: string;
  evidenceRefs: string;
  nonConclusions: string;
  appliesTo: CreativeKnowledgeStage[];
  scope: Record<keyof CreativeKnowledgeScope, string>;
};

const emptyScope = (): ProposalForm["scope"] => ({
  niche_id: "",
  brand_id: "",
  product_archetype: "",
  product_family_id: "",
  variant_id: "",
  platform: "",
  market: "",
  asset_type: "",
  task_type: "sku_to_output",
});

const emptyForm = (): ProposalForm => ({
  knowledgeId: "",
  knowledgeType: "lesson",
  title: "",
  content: "",
  authority: "team",
  contributor: "",
  sourceRefs: "",
  evidenceRefs: "",
  nonConclusions: "",
  appliesTo: ["preparation", "orchestration"],
  scope: emptyScope(),
});

const splitLines = (value: string) => value
  .split("\n")
  .map((line) => line.trim())
  .filter(Boolean);

const formatLabel = (value: string) => value.replaceAll("_", " ");

function formFromKnowledge(item: CreativeKnowledge, asReusableLesson = false): ProposalForm {
  return {
    knowledgeId: asReusableLesson ? "" : item.knowledge_id,
    knowledgeType: asReusableLesson ? "lesson" : item.knowledge_type,
    title: asReusableLesson ? `Reusable lesson: ${item.title}` : item.title,
    content: item.content,
    authority: asReusableLesson ? "team" : item.authority,
    contributor: "",
    sourceRefs: asReusableLesson ? `knowledge:${item.version_ref}` : item.source_refs.join("\n"),
    evidenceRefs: item.evidence_refs.join("\n"),
    nonConclusions: item.non_conclusions.join("\n"),
    appliesTo: asReusableLesson ? ["learning"] : item.applies_to,
    scope: Object.fromEntries(
      Object.entries(item.scope).map(([key, value]) => [key, value ?? ""]),
    ) as ProposalForm["scope"],
  };
}

export function CreativeKnowledgePage() {
  const { language, t } = useI18n();
  const { notify } = useWorkspace();
  const queryClient = useQueryClient();
  const [statusFilter, setStatusFilter] = useState<CreativeKnowledgeStatus | "all">("all");
  const [typeFilter, setTypeFilter] = useState<CreativeKnowledgeType | "all">("all");
  const [query, setQuery] = useState("");
  const [selectedRef, setSelectedRef] = useState<string | null>(null);
  const [reviewer, setReviewer] = useState("");
  const [bootstrapContributor, setBootstrapContributor] = useState("");
  const [proposalOpen, setProposalOpen] = useState(false);
  const [proposal, setProposal] = useState<ProposalForm>(emptyForm);
  const detailPanelRef = useRef<HTMLElement>(null);
  const split = useSplitResize("aic-second-brain-split", 420, 900, detailPanelRef);

  const knowledge = useQuery({
    queryKey: ["creative-knowledge"],
    queryFn: ({ signal }) => pilotApi.creativeKnowledge(undefined, signal),
  });
  const items = useMemo(() => knowledge.data?.items ?? [], [knowledge.data?.items]);
  const histories = useMemo(() => {
    const grouped = new Map<string, CreativeKnowledge[]>();
    for (const item of items) {
      const versions = grouped.get(item.knowledge_id) ?? [];
      versions.push(item);
      grouped.set(item.knowledge_id, versions);
    }
    for (const versions of grouped.values()) versions.sort((a, b) => b.version - a.version);
    return grouped;
  }, [items]);
  const latestItems = useMemo(() => [...histories.values()]
    .map((versions) => versions[0])
    .filter((item) => statusFilter === "all" || item.status === statusFilter)
    .filter((item) => typeFilter === "all" || item.knowledge_type === typeFilter)
    .filter((item) => {
      const needle = query.trim().toLocaleLowerCase();
      return !needle || [item.title, item.content, item.knowledge_id, ...item.source_refs]
        .some((value) => value.toLocaleLowerCase().includes(needle));
    })
    .sort((a, b) => b.created_at.localeCompare(a.created_at)), [histories, query, statusFilter, typeFilter]);
  const selectedByRef = items.find((item) => item.version_ref === selectedRef);
  const selected = selectedByRef && latestItems.some((item) => item.knowledge_id === selectedByRef.knowledge_id)
    ? selectedByRef
    : latestItems[0] ?? null;
  const selectedHistory = selected ? histories.get(selected.knowledge_id) ?? [] : [];
  const summary = useMemo(() => ({
    total: histories.size,
    approved: [...histories.values()].filter((versions) => versions[0].status === "approved").length,
    proposed: [...histories.values()].filter((versions) => versions[0].status === "proposed").length,
    conflict: [...histories.values()].filter((versions) => versions[0].status === "conflict").length,
  }), [histories]);

  const refresh = async () => queryClient.invalidateQueries({ queryKey: ["creative-knowledge"] });
  const bootstrap = useMutation({
    mutationFn: () => pilotApi.bootstrapCreativeKnowledge(bootstrapContributor.trim()),
    onSuccess: async (result) => {
      await refresh();
      notify(t(result.applied ? "Latest Creative knowledge was loaded for review." : "Latest Creative knowledge is already loaded."), "success");
    },
    onError: (error) => notify(error instanceof Error ? error.message : t("Initial knowledge could not be loaded."), "error"),
  });
  const decision = useMutation({
    mutationFn: ({ item, value }: { item: CreativeKnowledge; value: "approved" | "rejected" }) =>
      pilotApi.decideCreativeKnowledge(item.knowledge_id, item.version, value, reviewer.trim()),
    onSuccess: async (item) => {
      setSelectedRef(item.version_ref);
      await refresh();
      notify(t(item.status === "approved" ? "Knowledge approved for Creative Agent use." : "Knowledge proposal rejected."), "success");
    },
    onError: (error) => notify(error instanceof Error ? error.message : t("Review decision could not be saved."), "error"),
  });
  const conflict = useMutation({
    mutationFn: (item: CreativeKnowledge) => pilotApi.markCreativeKnowledgeConflict(item.knowledge_id, item.version),
    onSuccess: async (item) => {
      setSelectedRef(item.version_ref);
      await refresh();
      notify(t("Knowledge was marked as a conflict for human resolution."), "success");
    },
    onError: (error) => notify(error instanceof Error ? error.message : t("Conflict status could not be saved."), "error"),
  });
  const propose = useMutation({
    mutationFn: (body: CreativeKnowledgeProposalRequest) => pilotApi.proposeCreativeKnowledge(body),
    onSuccess: async (item) => {
      setSelectedRef(item.version_ref);
      setProposalOpen(false);
      await refresh();
      notify(t("Knowledge proposal saved for human review."), "success");
    },
    onError: (error) => notify(error instanceof Error ? error.message : t("Knowledge proposal could not be saved."), "error"),
  });

  const openNewProposal = () => {
    setProposal(emptyForm());
    setProposalOpen(true);
  };
  const openUpdatedVersion = (item: CreativeKnowledge) => {
    setProposal(formFromKnowledge(item));
    setProposalOpen(true);
  };
  const openReusableLesson = (item: CreativeKnowledge) => {
    setProposal(formFromKnowledge(item, true));
    setProposalOpen(true);
  };
  const submitProposal = (event: FormEvent) => {
    event.preventDefault();
    const scope = Object.fromEntries(
      Object.entries(proposal.scope).filter(([, value]) => value.trim()).map(([key, value]) => [key, value.trim()]),
    );
    propose.mutate({
      knowledge_id: proposal.knowledgeId.trim() || undefined,
      knowledge_type: proposal.knowledgeType,
      title: proposal.title.trim(),
      content: proposal.content.trim(),
      authority: proposal.authority,
      contributor: proposal.contributor.trim() || undefined,
      source_refs: splitLines(proposal.sourceRefs),
      evidence_refs: splitLines(proposal.evidenceRefs),
      applies_to: proposal.appliesTo,
      non_conclusions: splitLines(proposal.nonConclusions),
      scope,
    });
  };
  const dateTime = (value: string | null) => value
    ? new Intl.DateTimeFormat(language === "vi" ? "vi-VN" : "en-US", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value))
    : t("Not available");

  return <section className="second-brain-page">
    <PageHeader
      eyebrow="Creative intelligence"
      title="SecondBrain"
      variant="library"
      actions={<button className="primary-button" type="button" onClick={openNewProposal}><Plus size={16} /> {t("New proposal")}</button>}
    />

    <div className="second-brain-summary" aria-label={t("Knowledge summary")}>
      <article><BrainCircuit size={20} /><span>{t("Knowledge topics")}</span><strong>{summary.total}</strong></article>
      <article><Check size={20} /><span>{t("Approved")}</span><strong>{summary.approved}</strong></article>
      <article><History size={20} /><span>{t("Needs review")}</span><strong>{summary.proposed}</strong></article>
      <article><AlertTriangle size={20} /><span>{t("Conflicts")}</span><strong>{summary.conflict}</strong></article>
    </div>

    <section className="panel second-brain-bootstrap">
      <div><h2>{t("Curated Creative knowledge")}</h2></div>
      <label><span>{t("Contributor name")}</span><input value={bootstrapContributor} onChange={(event) => setBootstrapContributor(event.target.value)} /></label>
      <button className="secondary-button" type="button" disabled={!bootstrapContributor.trim() || bootstrap.isPending} onClick={() => bootstrap.mutate()}><RefreshCw size={15} /> {t("Load latest proposals")}</button>
    </section>

    <div className="second-brain-toolbar">
      <label><span>{t("Search knowledge")}</span><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder={t("Title, content, ID, or source")} /></label>
      <label><span>{t("Status")}</span><select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value as CreativeKnowledgeStatus | "all")}>
        {statuses.map((status) => <option key={status} value={status}>{t(formatLabel(status))}</option>)}
      </select></label>
      <label><span>{t("Knowledge type")}</span><select value={typeFilter} onChange={(event) => setTypeFilter(event.target.value as CreativeKnowledgeType | "all")}>
        <option value="all">{t("all")}</option>
        {knowledgeTypes.map((type) => <option key={type} value={type}>{t(formatLabel(type))}</option>)}
      </select></label>
    </div>

    {knowledge.isLoading && <div className="panel second-brain-state">{t("Loading Creative knowledge…")}</div>}
    {knowledge.isError && <div className="panel second-brain-state form-error">{t("Creative knowledge could not be loaded.")}</div>}
    {!knowledge.isLoading && !knowledge.isError && latestItems.length === 0 && <div className="panel second-brain-state"><BrainCircuit size={30} /><h2>{t("No matching knowledge")}</h2></div>}

    {latestItems.length > 0 && <div className={`second-brain-layout${split.active ? " split-active" : ""}`} style={split.style}>
      <div className="second-brain-list" aria-label={t("Knowledge topics")}>
        {latestItems.map((item) => <button
          type="button"
          key={item.version_ref}
          className={selected?.knowledge_id === item.knowledge_id ? "is-active" : ""}
          onClick={() => setSelectedRef(item.version_ref)}
        >
          <span><Badge tone={statusTone(item.status)}>{formatLabel(item.status)}</Badge><small>{t(formatLabel(item.knowledge_type))} · v{item.version}</small></span>
          <strong>{item.title}</strong>
          <p>{item.content}</p>
        </button>)}
      </div>

      {selected && <article ref={detailPanelRef} className="panel second-brain-detail">
        <SplitHandle label="Resize knowledge panels" {...split.handleProps} />
        <header>
          <div><p className="eyebrow">{t(formatLabel(selected.knowledge_type))}</p><h2>{selected.title}</h2></div>
          <Badge tone={statusTone(selected.status)}>{formatLabel(selected.status)}</Badge>
        </header>
        <p className="second-brain-content">{selected.content}</p>

        <dl className="second-brain-meta">
          <div><dt>{t("Version")}</dt><dd>{selected.version_ref}</dd></div>
          <div><dt>{t("Authority")}</dt><dd>{t(formatLabel(selected.authority))}</dd></div>
          <div><dt>{t("Contributor")}</dt><dd>{selected.contributor || t("Not available")}</dd></div>
          <div><dt>{t("Created")}</dt><dd>{dateTime(selected.created_at)}</dd></div>
          <div><dt>{t("Approved by")}</dt><dd>{selected.approved_by || t("Not available")}</dd></div>
          <div><dt>{t("Approved at")}</dt><dd>{dateTime(selected.approved_at)}</dd></div>
        </dl>

        <DetailList title={t("Applies to")} values={Object.entries(selected.scope).filter(([, value]) => value).map(([key, value]) => `${t(formatLabel(key))}: ${value}`)} empty={t("All matching Creative work")} />
        <DetailList title={t("Used by stages")} values={selected.applies_to.map((stage) => t(formatLabel(stage)))} />
        <DetailList title={t("Sources")} values={selected.source_refs} />
        <DetailList title={t("Evidence")} values={selected.evidence_refs} />
        <DetailList title={t("Does not conclude")} values={selected.non_conclusions} />

        <section className="second-brain-history">
          <h3>{t("Version history")}</h3>
          <div>{selectedHistory.map((version) => <button key={version.version_ref} type="button" className={selected.version_ref === version.version_ref ? "is-active" : ""} onClick={() => setSelectedRef(version.version_ref)}>v{version.version} · {t(formatLabel(version.status))}</button>)}</div>
        </section>

        <div className="second-brain-actions">
          <button className="secondary-button" type="button" onClick={() => openUpdatedVersion(selected)}><Plus size={15} /> {t("Propose updated version")}</button>
          {selected.knowledge_type === "feedback" && <button className="secondary-button" type="button" onClick={() => openReusableLesson(selected)}><BrainCircuit size={15} /> {t("Propose reusable lesson")}</button>}
        </div>

        {["draft", "proposed", "conflict"].includes(selected.status) && <section className="second-brain-review">
          <div><h3>{t("Human review")}</h3></div>
          <label><span>{t("Reviewer name")}</span><input value={reviewer} onChange={(event) => setReviewer(event.target.value)} /></label>
          <div>
            <button className="approve-button" type="button" disabled={!reviewer.trim() || decision.isPending} onClick={() => decision.mutate({ item: selected, value: "approved" })}><Check size={15} /> {t("Approve")}</button>
            <button className="reject-button" type="button" disabled={!reviewer.trim() || decision.isPending} onClick={() => decision.mutate({ item: selected, value: "rejected" })}><X size={15} /> {t("Reject")}</button>
            {selected.status !== "conflict" && <button className="secondary-button" type="button" disabled={conflict.isPending} onClick={() => conflict.mutate(selected)}><AlertTriangle size={15} /> {t("Mark conflict")}</button>}
          </div>
        </section>}
      </article>}
    </div>}

    {proposalOpen && <div className="second-brain-modal" role="dialog" aria-modal="true" aria-labelledby="knowledge-proposal-title">
      <form className="panel second-brain-proposal" onSubmit={submitProposal}>
        <header><div><p className="eyebrow">{t("Human-authored knowledge")}</p><h2 id="knowledge-proposal-title">{t(proposal.knowledgeId ? "Propose updated version" : "New knowledge proposal")}</h2></div><button type="button" className="icon-button" aria-label={t("Close")} onClick={() => setProposalOpen(false)}><X size={18} /></button></header>
        <div className="second-brain-form-grid">
          <label className="wide"><span>{t("Title")}</span><input required value={proposal.title} onChange={(event) => setProposal({ ...proposal, title: event.target.value })} /></label>
          <label><span>{t("Knowledge type")}</span><select value={proposal.knowledgeType} onChange={(event) => setProposal({ ...proposal, knowledgeType: event.target.value as CreativeKnowledgeType })}>{knowledgeTypes.map((type) => <option key={type} value={type}>{t(formatLabel(type))}</option>)}</select></label>
          <label><span>{t("Authority")}</span><select value={proposal.authority} onChange={(event) => setProposal({ ...proposal, authority: event.target.value as CreativeKnowledgeAuthority })}>{authorities.map((authority) => <option key={authority} value={authority}>{t(formatLabel(authority))}</option>)}</select></label>
          <label className="wide"><span>{t("Knowledge content")}</span><textarea required rows={6} value={proposal.content} onChange={(event) => setProposal({ ...proposal, content: event.target.value })} /></label>
          <label className="wide"><span>{t("Contributor name")}</span><input value={proposal.contributor} onChange={(event) => setProposal({ ...proposal, contributor: event.target.value })} /></label>
          <label><span>{t("Source references")}</span><textarea required rows={4} value={proposal.sourceRefs} onChange={(event) => setProposal({ ...proposal, sourceRefs: event.target.value })} /></label>
          <label><span>{t("Evidence references")}</span><textarea rows={4} value={proposal.evidenceRefs} onChange={(event) => setProposal({ ...proposal, evidenceRefs: event.target.value })} /></label>
          <label className="wide"><span>{t("Limits and non-conclusions")}</span><textarea rows={3} value={proposal.nonConclusions} onChange={(event) => setProposal({ ...proposal, nonConclusions: event.target.value })} /></label>
        </div>
        <fieldset><legend>{t("Used by stages")}</legend><div className="second-brain-stage-grid">
          {knowledgeStages.map((stage) => <label key={stage}><input type="checkbox" checked={proposal.appliesTo.includes(stage)} onChange={(event) => setProposal({ ...proposal, appliesTo: event.target.checked ? [...proposal.appliesTo, stage] : proposal.appliesTo.filter((item) => item !== stage) })} /> <span>{t(formatLabel(stage))}</span></label>)}
        </div></fieldset>
        <fieldset><legend>{t("Application scope")}</legend><div className="second-brain-scope-grid">
          {scopeFields.map((field) => <label key={field}><span>{t(formatLabel(field))}</span><input value={proposal.scope[field]} onChange={(event) => setProposal({ ...proposal, scope: { ...proposal.scope, [field]: event.target.value } })} /></label>)}
        </div></fieldset>
        <footer><button className="text-button" type="button" onClick={() => setProposalOpen(false)}>{t("Cancel")}</button><button className="primary-button" disabled={propose.isPending || !proposal.title.trim() || !proposal.content.trim() || splitLines(proposal.sourceRefs).length === 0 || proposal.appliesTo.length === 0}>{t("Save proposal")}</button></footer>
      </form>
    </div>}
  </section>;
}

function DetailList({ title, values, empty }: { title: string; values: string[]; empty?: string }) {
  if (values.length === 0 && !empty) return null;
  return <section className="second-brain-detail-list"><h3>{title}</h3>{values.length > 0 ? <ul>{values.map((value) => <li key={value}>{value}</li>)}</ul> : <p>{empty}</p>}</section>;
}

function statusTone(status: CreativeKnowledgeStatus): "success" | "warning" | "danger" | "info" | "neutral" {
  if (status === "approved") return "success";
  if (status === "rejected" || status === "expired") return "danger";
  if (status === "conflict") return "warning";
  if (status === "proposed" || status === "draft") return "info";
  return "neutral";
}
