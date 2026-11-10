import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Pencil, Power, X } from "lucide-react";
import { useEffect, useMemo, useState, type FormEvent } from "react";
import { ErrorNote, Skeleton, Spinner } from "../../components/ui";
import { useWorkspace } from "../../hooks/useWorkspace";
import { pilotApi } from "../../services/pilotApi";
import type { CreativeKnowledge, CreativeKnowledgeStage } from "../../types/pilotApi";

const REVIEWER = "user";
const MANIFEST = "product_ad";
type Asset = "brief" | "keyframe";

const GROUPS = [
  { asset: "brief", title: "Script and voice-over" },
  { asset: "keyframe", title: "Images" },
  { asset: "", title: "Other" },
];
const STAGES: Record<Asset, CreativeKnowledgeStage[]> = {
  brief: ["preparation", "review"],
  keyframe: ["orchestration", "review"],
};

function plain(content: string) {
  const match = /^WHEN:\s*(.*?)\s*DO:\s*(.*?)(?:\s*DO NOT:\s*(.*))?$/s.exec(content);
  return match ? { when: match[1], doText: match[2], dont: match[3] } : null;
}

export function RulesTab() {
  const { notify } = useWorkspace();
  const client = useQueryClient();
  const [text, setText] = useState("");
  const [asset, setAsset] = useState<Asset>("keyframe");
  const [editing, setEditing] = useState<{ id: string; text: string } | null>(null);
  const knowledge = useQuery({ queryKey: ["creative-knowledge"], queryFn: ({ signal }) => pilotApi.creativeKnowledge(undefined, signal) });
  const refresh = () => client.invalidateQueries({ queryKey: ["creative-knowledge"] });

  useEffect(() => {
    // Loads the standard rules once; it does nothing when they are already there.
    pilotApi
      .bootstrapCreativeKnowledge("system", MANIFEST)
      .then(() => client.invalidateQueries({ queryKey: ["creative-knowledge"] }))
      .catch(() => undefined);
  }, [client]);

  const { pending, active } = useMemo(() => {
    const items = knowledge.data?.items ?? [];
    return {
      pending: items.filter((item) => item.status === "proposed" || item.status === "draft"),
      active: items.filter((item) => item.status === "approved"),
    };
  }, [knowledge.data?.items]);

  const decide = useMutation({
    mutationFn: async ({ ids, value }: { ids: string[]; value: "approved" | "rejected" }) => {
      for (const id of ids) await pilotApi.decideCreativeKnowledge(id, value, REVIEWER);
    },
    onSuccess: refresh,
  });
  const turnOff = useMutation({ mutationFn: (id: string) => pilotApi.retireCreativeKnowledge(id), onSuccess: refresh });
  const save = useMutation({
    mutationFn: async (body: { item?: CreativeKnowledge; content: string; asset: Asset }) => {
      const saved = await pilotApi.proposeCreativeKnowledge({
        knowledge_id: body.item?.knowledge_id,
        knowledge_type: body.item?.knowledge_type ?? "lesson",
        title: body.item?.title ?? body.content.slice(0, 80),
        content: body.content,
        scope: body.item?.scope ?? { task_type: "product_ad", asset_type: body.asset },
        authority: body.item?.authority ?? "individual",
        source_refs: body.item?.source_refs ?? ["feedback:manual"],
        evidence_refs: [],
        applies_to: body.item?.applies_to ?? STAGES[body.asset],
        contributor: REVIEWER,
        non_conclusions: [],
      });
      await pilotApi.decideCreativeKnowledge(saved.knowledge_id, "approved", REVIEWER);
    },
    onSuccess: () => {
      setText("");
      setEditing(null);
      notify("Saved. The AI will follow it from the next video.", "success");
      return refresh();
    },
  });

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (text.trim()) save.mutate({ content: text.trim(), asset });
  };

  const card = (item: CreativeKnowledge, waiting: boolean) => {
    const parts = plain(item.content);
    const isEditing = editing?.id === item.knowledge_id;
    return (
      <article className="card rule" key={item.knowledge_id}>
        <h3>{item.title}</h3>
        {isEditing ? (
          <>
            <textarea aria-label="Rule text" value={editing.text} rows={5} onChange={(event) => setEditing({ id: editing.id, text: event.target.value })} />
            <div className="row">
              <button className="btn btn-primary btn-sm" disabled={!editing.text.trim() || save.isPending} onClick={() => save.mutate({ item, content: editing.text.trim(), asset: "keyframe" })}>Save</button>
              <button className="btn btn-sm" onClick={() => setEditing(null)}>Cancel</button>
            </div>
          </>
        ) : (
          <>
            {parts ? (
              <ul>
                <li><span className="muted">When</span> {parts.when}</li>
                <li className="do"><Check size={14} aria-hidden="true" /> {parts.doText}</li>
                {parts.dont && <li className="dont"><X size={14} aria-hidden="true" /> {parts.dont}</li>}
              </ul>
            ) : <p className="small">{item.content}</p>}
            <div className="row">
              {waiting ? (
                <>
                  <button className="btn btn-ok btn-sm" disabled={decide.isPending} onClick={() => decide.mutate({ ids: [item.knowledge_id], value: "approved" })}><Check size={14} aria-hidden="true" />Approve</button>
                  <button className="btn btn-sm" disabled={decide.isPending} onClick={() => decide.mutate({ ids: [item.knowledge_id], value: "rejected" })}><X size={14} aria-hidden="true" />Reject</button>
                </>
              ) : (
                <>
                  <button className="btn btn-sm" onClick={() => setEditing({ id: item.knowledge_id, text: item.content })}><Pencil size={14} aria-hidden="true" />Edit</button>
                  <button className="btn btn-sm" disabled={turnOff.isPending} onClick={() => turnOff.mutate(item.knowledge_id)}><Power size={14} aria-hidden="true" />Turn off</button>
                </>
              )}
            </div>
          </>
        )}
      </article>
    );
  };

  return (
    <div className="stack-lg">
      <form className="card pad stack" onSubmit={submit}>
        <label className="field">
          Add a rule
          <textarea value={text} rows={3} onChange={(event) => setText(event.target.value)} placeholder="For example: the person's skin must have no acne" />
        </label>
        <div className="row">
          <select className="input" style={{ width: "auto" }} value={asset} onChange={(event) => setAsset(event.target.value as Asset)} aria-label="What the rule is for">
            <option value="keyframe">For images</option>
            <option value="brief">For the script and voice-over</option>
          </select>
          <button className="btn btn-primary" type="submit" disabled={!text.trim() || save.isPending}>{save.isPending ? <><Spinner size={14} />Saving…</> : "Add rule"}</button>
        </div>
      </form>
      <ErrorNote error={decide.error ?? turnOff.error ?? save.error} />

      {pending.length > 0 && (
        <section className="card pad stack" style={{ borderColor: "var(--brand)" }}>
          <div className="row" style={{ justifyContent: "space-between" }}>
            <h2>{pending.length === 1 ? "1 rule is waiting for your OK" : `${pending.length} rules are waiting for your OK`}</h2>
            <button className="btn btn-primary" disabled={decide.isPending} onClick={() => decide.mutate({ ids: pending.map((item) => item.knowledge_id), value: "approved" })}>
              <Check size={15} aria-hidden="true" />{decide.isPending ? "Approving…" : "Approve all"}
            </button>
          </div>
          <div className="rule-grid">{pending.map((item) => card(item, true))}</div>
        </section>
      )}

      {knowledge.isLoading && <Skeleton />}
      {knowledge.isError && <ErrorNote error={knowledge.error} />}
      {GROUPS.map(({ asset: key, title }) => {
        const rows = active.filter((item) => (item.scope.asset_type ?? "") === key);
        if (!rows.length) return null;
        return (
          <section key={key || "other"} className="stack">
            <h2>{title}</h2>
            <div className="rule-grid">{rows.map((item) => card(item, false))}</div>
          </section>
        );
      })}
      {!knowledge.isLoading && pending.length === 0 && active.length === 0 && <p className="muted">No rules yet. Add the first one above.</p>}
    </div>
  );
}
