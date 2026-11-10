import { useEffect, useMemo, useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Pencil, Power, X } from "lucide-react";
import { PageHeader } from "../components/ui";
import { useI18n } from "../hooks/useI18n";
import { useWorkspace } from "../hooks/useWorkspace";
import { pilotApi } from "../services/pilotApi";
import type { CreativeKnowledge, CreativeKnowledgeStage } from "../types/pilotApi";

const REVIEWER = "user";
const MANIFEST = "product_ad";
type Asset = "brief" | "keyframe";

const groups: Array<{ asset: string; title: string }> = [
  { asset: "brief", title: "Script and voice-over" },
  { asset: "keyframe", title: "Images" },
  { asset: "", title: "Other" },
];

const stagesFor: Record<Asset, CreativeKnowledgeStage[]> = {
  brief: ["preparation", "review"],
  keyframe: ["orchestration", "review"],
};

function plain(content: string) {
  const match = /^WHEN:\s*(.*?)\s*DO:\s*(.*?)(?:\s*DO NOT:\s*(.*))?$/s.exec(content);
  return match ? { when: match[1], doText: match[2], dont: match[3] } : null;
}

export function CreativeKnowledgePage() {
  const { t } = useI18n();
  const { notify } = useWorkspace();
  const queryClient = useQueryClient();
  const [text, setText] = useState("");
  const [asset, setAsset] = useState<Asset>("keyframe");
  const [editing, setEditing] = useState<{ id: string; text: string } | null>(null);

  const knowledge = useQuery({
    queryKey: ["creative-knowledge"],
    queryFn: ({ signal }) => pilotApi.creativeKnowledge(undefined, signal),
  });
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["creative-knowledge"] });
  const onError = (error: unknown) => notify(error instanceof Error ? error.message : t("Something went wrong."), "error");

  useEffect(() => {
    // Loads the standard rules once; it does nothing when they are already there.
    pilotApi
      .bootstrapCreativeKnowledge("system", MANIFEST)
      .then(() => queryClient.invalidateQueries({ queryKey: ["creative-knowledge"] }))
      .catch(() => undefined);
  }, [queryClient]);

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
    onError,
  });
  const turnOff = useMutation({
    mutationFn: (id: string) => pilotApi.retireCreativeKnowledge(id),
    onSuccess: refresh,
    onError,
  });
  const save = useMutation({
    mutationFn: async (body: { id?: string; item?: CreativeKnowledge; content: string; asset: Asset }) => {
      const saved = await pilotApi.proposeCreativeKnowledge({
        knowledge_id: body.id,
        knowledge_type: body.item?.knowledge_type ?? "lesson",
        title: body.item?.title ?? body.content.slice(0, 80),
        content: body.content,
        scope: body.item?.scope ?? { task_type: "product_ad", asset_type: body.asset },
        authority: body.item?.authority ?? "individual",
        source_refs: body.item?.source_refs ?? ["feedback:manual"],
        evidence_refs: [],
        applies_to: body.item?.applies_to ?? stagesFor[body.asset],
        contributor: REVIEWER,
        non_conclusions: [],
      });
      await pilotApi.decideCreativeKnowledge(saved.knowledge_id, "approved", REVIEWER);
    },
    onSuccess: () => {
      setText("");
      setEditing(null);
      notify(t("Saved. The AI will follow it from the next video."), "success");
      return refresh();
    },
    onError,
  });

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (text.trim()) save.mutate({ content: text.trim(), asset });
  };

  const card = (item: CreativeKnowledge, waiting: boolean) => {
    const parts = plain(item.content);
    const isEditing = editing?.id === item.knowledge_id;
    return (
      <article className="brain-card" key={item.knowledge_id}>
        <h3>{item.title}</h3>
        {isEditing ? (
          <>
            <textarea value={editing.text} rows={5} onChange={(event) => setEditing({ id: editing.id, text: event.target.value })} />
            <div className="brain-actions">
              <button className="primary-button" disabled={!editing.text.trim() || save.isPending} onClick={() => save.mutate({ id: item.knowledge_id, item, content: editing.text.trim(), asset: "keyframe" })}>{t("Save")}</button>
              <button className="secondary-button" onClick={() => setEditing(null)}>{t("Cancel")}</button>
            </div>
          </>
        ) : (
          <>
            {parts ? (
              <ul>
                <li><small>{t("When")}</small> {parts.when}</li>
                <li className="brain-do"><Check size={14} /> {parts.doText}</li>
                {parts.dont && <li className="brain-dont"><X size={14} /> {parts.dont}</li>}
              </ul>
            ) : <p>{item.content}</p>}
            <div className="brain-actions">
              {waiting ? (
                <>
                  <button className="approve-button" disabled={decide.isPending} onClick={() => decide.mutate({ ids: [item.knowledge_id], value: "approved" })}><Check size={14} /> {t("Approve")}</button>
                  <button className="reject-button" disabled={decide.isPending} onClick={() => decide.mutate({ ids: [item.knowledge_id], value: "rejected" })}><X size={14} /> {t("Reject")}</button>
                </>
              ) : (
                <>
                  <button className="secondary-button" onClick={() => setEditing({ id: item.knowledge_id, text: item.content })}><Pencil size={14} /> {t("Edit")}</button>
                  <button className="secondary-button" disabled={turnOff.isPending} onClick={() => turnOff.mutate(item.knowledge_id)}><Power size={14} /> {t("Turn off")}</button>
                </>
              )}
            </div>
          </>
        )}
      </article>
    );
  };

  return (
    <section className="brain-page">
      <PageHeader
        eyebrow="Creative intelligence"
        title="SecondBrain"
        description="The rules the AI follows when it makes your videos. Change a rule and every next video follows it."
        variant="library"
      />

      <form className="panel brain-add" onSubmit={submit}>
        <label>
          <span>{t("Add a rule")}</span>
          <textarea value={text} rows={3} onChange={(event) => setText(event.target.value)} placeholder={t("For example: the person's skin must have no acne")} />
        </label>
        <div className="brain-actions">
          <select value={asset} onChange={(event) => setAsset(event.target.value as Asset)} aria-label={t("What it is for")}>
            <option value="keyframe">{t("Images")}</option>
            <option value="brief">{t("Script and voice-over")}</option>
          </select>
          <button className="primary-button" type="submit" disabled={!text.trim() || save.isPending}>{save.isPending ? t("Saving…") : t("Add rule")}</button>
        </div>
      </form>

      {pending.length > 0 && (
        <section className="panel brain-pending">
          <div className="brain-pending__head">
            <h2>{t("{count} rules are waiting for your OK", { count: pending.length })}</h2>
            <button className="primary-button" disabled={decide.isPending} onClick={() => decide.mutate({ ids: pending.map((item) => item.knowledge_id), value: "approved" })}>
              <Check size={15} /> {decide.isPending ? t("Approving…") : t("Approve all")}
            </button>
          </div>
          <div className="brain-grid">{pending.map((item) => card(item, true))}</div>
        </section>
      )}

      {knowledge.isLoading && <p>{t("Loading…")}</p>}
      {knowledge.isError && <p role="alert">{t("Rules could not be loaded.")}</p>}
      {groups.map(({ asset: key, title }) => {
        const rows = active.filter((item) => (item.scope.asset_type ?? "") === key);
        if (!rows.length) return null;
        return (
          <section key={key || "other"}>
            <h2 className="brain-group">{t(title)}</h2>
            <div className="brain-grid">{rows.map((item) => card(item, false))}</div>
          </section>
        );
      })}
      {!knowledge.isLoading && pending.length === 0 && active.length === 0 && <p>{t("No rules yet. Add the first one above.")}</p>}
    </section>
  );
}
