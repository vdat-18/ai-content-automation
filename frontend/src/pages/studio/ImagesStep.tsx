import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, RefreshCw } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { ErrorNote, Spinner } from "../../components/ui";
import { useLightbox } from "../../hooks/useLightbox";
import { API, useStartPipeline, useVoice } from "../../hooks/useStudio";
import { checkNote, imagesApproved, isUnchecked, runStopped } from "../../lib/studio";
import { pilotApi } from "../../services/pilotApi";
import { postJson, putJson } from "../../services/http";
import type { BriefRecord, Keyframe, PipelineRun } from "../../types/studio";
import { VoiceChoice } from "./VoiceChoice";

const ROLE_LABEL: Record<string, string> = {
  hook: "Opening",
  problem: "The problem",
  demo: "Show the product",
  benefit: "The benefit",
  call_to_action: "Call to buy",
};

export function ImagesStep({ productId, record, frames, run, making = false }: { productId: string; record: BriefRecord; frames: Keyframe[]; run: PipelineRun | undefined; making?: boolean }) {
  const client = useQueryClient();
  const lightbox = useLightbox();
  const [noteFor, setNoteFor] = useState<number | null>(null);
  const [note, setNote] = useState("");
  const [learned, setLearned] = useState<number[]>([]);
  const [voice, setVoice] = useVoice();
  const shots = record.brief.shots ?? [];
  const byShot = new Map(frames.map((frame) => [frame.shot_index, frame]));
  const approved = shots.filter((_, index) => byShot.get(index)?.status === "approved").length;
  const masterApproved = byShot.get(0)?.status === "approved";
  const refresh = () => client.invalidateQueries({ queryKey: ["keyframes", productId] });

  const review = useMutation({
    mutationFn: ({ index, status }: { index: number; status: "approved" | "ready" }) => putJson(`${API}/${productId}/keyframes/${index}`, { status }),
    onSuccess: refresh,
  });
  const redo = useMutation({
    mutationFn: async ({ index, text }: { index: number; text: string }) => {
      if (text) await postJson(`${API}/${productId}/feedback`, { text, asset_type: "keyframe" });
      return postJson<Keyframe[]>(`${API}/${productId}/keyframes`, { shot_index: index, note: text });
    },
    onSuccess: (_data, { index, text }) => {
      if (text) setLearned((list) => [...list, index]);
      void refresh();
    },
  });
  const recheck = useMutation({ mutationFn: (index: number) => postJson(`${API}/${productId}/keyframes/${index}/check`), onSuccess: refresh });
  const start = useStartPipeline(productId);
  const rules = useQuery({ queryKey: ["creative-knowledge"], queryFn: ({ signal }) => pilotApi.creativeKnowledge(undefined, signal) });
  const imageRules = (rules.data?.items ?? []).filter((item) => item.status === "approved" && item.scope.asset_type === "keyframe");
  const all = imagesApproved(record, frames);

  if (frames.length === 0) {
    return (
      <div className="card pad stack" style={{ maxWidth: 640 }}>
        <h1 style={{ fontSize: 24 }}>No images yet</h1>
        <ol className="stack" style={{ margin: 0, paddingLeft: 18, gap: 6 }}>{shots.map((shot, index) => <li key={index} className="small">{shot.voiceover}</li>)}</ol>
        <p className="muted">The AI creates one picture for every scene of your script. It takes about 8 minutes and you can leave the page.</p>
        {run && runStopped(run) && <div className="notice notice-warn" role="alert"><div>The last run stopped. {run.message}</div></div>}
        <button className="btn btn-primary btn-lg" style={{ alignSelf: "flex-start" }} disabled={start.isPending} onClick={() => start.mutate({ until: "images" })}>{start.isPending ? "Starting…" : "Create the images"}</button>
        <ErrorNote error={start.error} />
      </div>
    );
  }

  const lightboxImages = shots.flatMap((shot, index) => {
    const frame = byShot.get(index);
    return frame && frame.status !== "failed" ? [{ index, src: `${API}/${productId}/keyframes/${index}/image?v=${frame.attempts}`, label: `Scene ${index + 1}` }] : [];
  });

  return (
    <>
      <header className="page-head"><div><h1>Look at each scene and approve</h1><p>Approve the scenes you like. If one is not right, tell the AI what is wrong. It fixes the scene and avoids that mistake next time.</p></div></header>
      <div className="studio-cols">
        <div className="studio-main">
          {!masterApproved && byShot.has(0) && <div className="notice"><div>Approve scene 1 first. The other scenes are made to match it.</div></div>}
          <ErrorNote error={review.error ?? redo.error ?? recheck.error} />
          <div className="shot-grid">
            {shots.map((shot, index) => {
              const frame = byShot.get(index);
              const waiting = making && index > 0 && !frame; // being made right now
              const busy = (redo.isPending && redo.variables?.index === index) || waiting;
              const isApproved = frame?.status === "approved";
              const open = noteFor === index && !busy;
              const src = frame && frame.status !== "failed" ? `${API}/${productId}/keyframes/${index}/image?v=${frame.attempts}` : null;
              return (
                <article key={index} className={`card shot-card${isApproved ? " approved" : ""}`}>
                  <div className="media">
                    {src ? <img src={src} alt={`Scene ${index + 1}`} {...lightbox.zoom(lightboxImages, lightboxImages.findIndex((item) => item.index === index))} /> : <div className="empty">{frame?.error ? "This image could not be created." : "No image yet"}</div>}
                    {busy && <div className="over"><Spinner size={28} />{waiting ? "Creating this scene, about 2 minutes" : "The AI is fixing this scene, about 2 minutes"}</div>}
                    {isApproved && !busy && <span className="tag"><Check size={13} aria-hidden="true" />Approved</span>}
                  </div>
                  <div className="body">
                    <strong>{`Scene ${index + 1} · ${ROLE_LABEL[shot.role] ?? shot.role.replaceAll("_", " ")}`}</strong>
                    <p className="line">{`"${shot.voiceover}"`}</p>
                    {frame && <p className={frame.qa_problem ? "check-warn" : "check-ok"}>{checkNote(frame.qa_problem)}</p>}
                    {frame && isUnchecked(frame.qa_problem) && !busy && <button className="btn btn-sm" disabled={recheck.isPending} onClick={() => recheck.mutate(index)}>{recheck.isPending && recheck.variables === index ? <><Spinner size={14} />Checking…</> : "Check again"}</button>}
                    {open ? (
                      <div className="stack" style={{ gap: 8 }}>
                        <label className="field" htmlFor={`note-${index}`}>What is not right?</label>
                        <textarea id={`note-${index}`} className="input" rows={3} value={note} onChange={(event) => setNote(event.target.value)} placeholder="For example: faint marks on the cheek, the arm looks too long" />
                        <div className="row">
                          <button className="btn btn-primary btn-sm" disabled={!note.trim() || redo.isPending} onClick={() => { redo.mutate({ index, text: note.trim() }); setNoteFor(null); setNote(""); }}>Fix this scene</button>
                          <button className="btn btn-sm" onClick={() => setNoteFor(null)}>Cancel</button>
                        </div>
                        <span className="muted small">The AI remembers this. You approve it in AI memory and it applies to every next video.</span>
                      </div>
                    ) : frame && frame.status !== "failed" && !busy ? (
                      <div className="row">
                        <button className={isApproved ? "btn btn-sm" : "btn btn-ok btn-sm"} style={{ flex: 1 }} disabled={making || review.isPending || (index > 0 && !masterApproved && !isApproved)} onClick={() => review.mutate({ index, status: isApproved ? "ready" : "approved" })}>{isApproved ? "Undo approval" : "Approve"}</button>
                        <button className="btn btn-sm" style={{ flex: 1 }} disabled={making || (index > 0 && !masterApproved)} onClick={() => { setNoteFor(index); setNote(""); }}>Not right</button>
                      </div>
                    ) : !busy && (
                      <button className="btn btn-sm" disabled={redo.isPending || (index > 0 && !masterApproved)} onClick={() => redo.mutate({ index, text: "" })}><RefreshCw size={14} aria-hidden="true" />Try again</button>
                    )}
                    {learned.includes(index) && !busy && <span className="check-ok">Noted. The AI will avoid this next time once you approve it in AI memory.</span>}
                  </div>
                </article>
              );
            })}
          </div>
        </div>

        <aside className="studio-side" aria-label="Progress">
          <div className="card pad stack">
            <h2>{record.brief.title}</h2>
            <p><strong>{`${approved} of ${shots.length}`}</strong> scenes approved</p>
            <div className="progress ok" role="progressbar" aria-valuenow={approved} aria-valuemin={0} aria-valuemax={shots.length} aria-label="Scenes approved"><div style={{ width: `${shots.length ? (approved / shots.length) * 100 : 0}%` }} /></div>
            {making ? (
              <div className="row" role="status" aria-live="polite" style={{ gap: 10 }}><Spinner size={18} /><strong>Creating the other scenes…</strong></div>
            ) : masterApproved && frames.length < shots.length && (
              <button className="btn btn-primary btn-lg btn-block" disabled={start.isPending} onClick={() => start.mutate({ until: "images" })}>{start.isPending ? "Starting…" : "Create the other scenes"}</button>
            )}
            {making ? (
              <span className="muted small">This takes about 8 minutes. You can leave this page. We tell you when it is done.</span>
            ) : all ? (
              <>
                <VoiceChoice voice={voice} onChoose={setVoice} />
                <button className="btn btn-primary btn-lg btn-block" disabled={start.isPending || !voice} onClick={() => start.mutate({ until: "video" })}>{start.isPending ? "Starting…" : voice ? "Make the video from these scenes" : "Pick a voice to continue"}</button>
              </>
            ) : (
              <button className="btn btn-lg btn-block" disabled>Approve every scene to continue</button>
            )}
            <span className="muted small">Making the video takes about 10 minutes. You can leave the page.</span>
            <ErrorNote error={start.error} />
            {run && runStopped(run) && <div className="notice notice-warn" role="alert"><div>The last run stopped. {run.message}</div></div>}
          </div>
          {imageRules.length > 0 && (
            <div className="card pad stack">
              <h3>The AI is following these rules for images</h3>
              <ul className="stack" style={{ margin: 0, paddingLeft: 18, gap: 6 }}>{imageRules.map((rule) => <li key={rule.knowledge_id} className="small">{rule.title}</li>)}</ul>
              <Link className="link" to="/memory">See and edit in AI memory</Link>
            </div>
          )}
        </aside>
      </div>
      {lightbox.node}
    </>
  );
}
