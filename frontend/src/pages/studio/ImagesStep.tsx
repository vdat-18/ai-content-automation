import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, RefreshCw } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { ErrorNote, Spinner } from "../../components/ui";
import { useLightbox } from "../../hooks/useLightbox";
import { API, useClips, useStartPipeline } from "../../hooks/useStudio";
import { checkNote, friendlyStep, imagesApproved, isUnchecked, runStopped } from "../../lib/studio";
import { pilotApi } from "../../services/pilotApi";
import { postJson, putJson } from "../../services/http";
import type { BriefRecord, Keyframe, PipelineRun } from "../../types/studio";

const ROLE_LABEL: Record<string, string> = {
  hook: "Opening",
  problem: "The problem",
  demo: "Show the product",
  benefit: "The benefit",
  call_to_action: "Call to buy",
};

export function ImagesStep({ productId, record, frames, run, hasVideo = false, making = false, makingVideo = false }: { productId: string; record: BriefRecord; frames: Keyframe[]; run: PipelineRun | undefined; hasVideo?: boolean; making?: boolean; makingVideo?: boolean }) {
  const client = useQueryClient();
  const lightbox = useLightbox();
  const [noteFor, setNoteFor] = useState<number | null>(null);
  const [note, setNote] = useState("");
  const [learned, setLearned] = useState<number[]>([]);
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
      const rule = text ? await postJson<{ status: string }>(`${API}/${productId}/feedback`, { text, asset_type: "keyframe" }) : null;
      await postJson<Keyframe[]>(`${API}/${productId}/keyframes`, { shot_index: index, note: text });
      return rule?.status === "approved";
    },
    onSuccess: (saved, { index }) => {
      if (saved) setLearned((list) => [...list, index]);
      void refresh();
    },
  });
  const recheck = useMutation({ mutationFn: (index: number) => postJson(`${API}/${productId}/keyframes/${index}/check`), onSuccess: refresh });
  const clips = useClips(productId);
  const clipOf = new Map((clips.data ?? []).map((clip) => [clip.shot_index, clip]));
  const refreshClips = () => client.invalidateQueries({ queryKey: ["clips", productId] });
  const remakeClip = useMutation({ mutationFn: (index: number) => postJson(`${API}/${productId}/clips`, { shot_index: index }), onSuccess: refreshClips });
  const acceptClip = useMutation({ mutationFn: (index: number) => putJson(`${API}/${productId}/clips/${index}/review`, {}), onSuccess: refreshClips });
  const recheckClip = useMutation({ mutationFn: (index: number) => postJson(`${API}/${productId}/clips/${index}/check`), onSuccess: refreshClips });
  const clipNeedsLook = (index: number) => {
    const clip = clipOf.get(index);
    return !!clip && (clip.status === "failed" || (clip.status === "ready" && !!clip.qa_problem));
  };
  const needsLook = shots.map((_, index) => index).filter(clipNeedsLook);
  const start = useStartPipeline(productId);
  const rules = useQuery({ queryKey: ["creative-knowledge"], queryFn: ({ signal }) => pilotApi.creativeKnowledge(undefined, signal) });
  const imageRules = (rules.data?.items ?? []).filter((item) => item.status === "approved" && item.scope.asset_type === "keyframe");
  const all = imagesApproved(record, frames);
  const locked = making || makingVideo;

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
          <ErrorNote error={review.error ?? redo.error ?? recheck.error ?? remakeClip.error ?? acceptClip.error ?? recheckClip.error} />
          <div className="shot-grid">
            {shots.map((shot, index) => {
              const frame = byShot.get(index);
              const clip = clipOf.get(index);
              const filming = clip?.status === "processing";
              const clipBusy = (remakeClip.isPending && remakeClip.variables === index) || (acceptClip.isPending && acceptClip.variables === index);
              const waiting = making && index > 0 && !frame; // being made right now
              const busy = (redo.isPending && redo.variables?.index === index) || waiting;
              const isApproved = frame?.status === "approved";
              const open = noteFor === index && !busy;
              const src = frame && frame.status !== "failed" ? `${API}/${productId}/keyframes/${index}/image?v=${frame.attempts}` : null;
              return (
                <article key={index} className={`card shot-card${isApproved ? " approved" : ""}`}>
                  <div className="media">
                    {clip?.status === "ready" ? <video src={`${API}/${productId}/clips/${index}/video?v=${clip.attempts}`} poster={src ?? undefined} controls playsInline preload="metadata" aria-label={`Clip of scene ${index + 1}`} /> : src ? <img src={src} alt={`Scene ${index + 1}`} {...lightbox.zoom(lightboxImages, lightboxImages.findIndex((item) => item.index === index))} /> : <div className="empty">{frame?.error ? "This image could not be created." : "No image yet"}</div>}
                    {filming && !busy && <div className="over"><Spinner size={28} />Filming this scene, about 4 minutes</div>}
                    {busy && <div className="over"><Spinner size={28} />{waiting ? "Creating this scene, about 2 minutes" : "The AI is fixing this scene, about 2 minutes"}</div>}
                    {isApproved && !busy && !clip && <span className="tag"><Check size={13} aria-hidden="true" />Approved</span>}
                  </div>
                  <div className="body">
                    <strong>{`Scene ${index + 1} · ${ROLE_LABEL[shot.role] ?? shot.role.replaceAll("_", " ")}`}</strong>
                    <p className="line">{`"${shot.voiceover}"`}</p>
                    {frame && !clip && <p className={frame.qa_problem ? "check-warn" : "check-ok"}>{checkNote(frame.qa_problem)}</p>}
                    {clip?.status === "ready" && !clip.qa_problem && <p className="check-ok">The clip is ready.</p>}
                    {clip?.status === "failed" && <p className="check-warn">{`This scene could not be filmed: ${clip.error ?? "the video job failed"}`}</p>}
                    {clip?.status === "ready" && clip.qa_problem && <p className="check-warn">{isUnchecked(clip.qa_problem) ? clip.qa_problem : `The AI suggests a second look: ${clip.qa_problem}`}</p>}
                    {clipNeedsLook(index) && (
                      <div className="stack" style={{ gap: 8 }}>
                        <span className="muted small">Filming a scene again costs one more clip.</span>
                        <div className="row">
                          <button className="btn btn-sm" style={{ flex: 1 }} disabled={clipBusy} onClick={() => remakeClip.mutate(index)}>{remakeClip.isPending && remakeClip.variables === index ? <><Spinner size={14} />Starting…</> : "Film again"}</button>
                          {clip?.status === "ready" && <button className="btn btn-ok btn-sm" style={{ flex: 1 }} disabled={clipBusy} onClick={() => acceptClip.mutate(index)}>Use it as it is</button>}
                        </div>
                        {clip?.status === "ready" && isUnchecked(clip.qa_problem) && <button className="btn btn-sm" disabled={recheckClip.isPending} onClick={() => recheckClip.mutate(index)}>Check again</button>}
                      </div>
                    )}
                    {frame && isUnchecked(frame.qa_problem) && !busy && <button className="btn btn-sm" disabled={recheck.isPending} onClick={() => recheck.mutate(index)}>{recheck.isPending && recheck.variables === index ? <><Spinner size={14} />Checking…</> : "Check again"}</button>}
                    {open ? (
                      <div className="stack" style={{ gap: 8 }}>
                        <label className="field" htmlFor={`note-${index}`}>What is not right?</label>
                        <textarea id={`note-${index}`} className="input" rows={3} value={note} onChange={(event) => setNote(event.target.value)} placeholder="For example: faint marks on the cheek, the arm looks too long" />
                        <div className="row">
                          <button className="btn btn-primary btn-sm" disabled={!note.trim() || redo.isPending} onClick={() => { redo.mutate({ index, text: note.trim() }); setNoteFor(null); setNote(""); }}>Fix this scene</button>
                          <button className="btn btn-sm" onClick={() => setNoteFor(null)}>Cancel</button>
                        </div>
                        <span className="muted small">The AI turns this into a rule that applies to every next video.</span>
                      </div>
                    ) : clip ? null : frame && frame.status !== "failed" && !busy ? (
                      <div className="row">
                        <button className={isApproved ? "btn btn-sm" : "btn btn-ok btn-sm"} style={{ flex: 1 }} disabled={locked || review.isPending || (index > 0 && !masterApproved && !isApproved)} onClick={() => review.mutate({ index, status: isApproved ? "ready" : "approved" })}>{isApproved ? "Undo approval" : "Approve"}</button>
                        <button className="btn btn-sm" style={{ flex: 1 }} disabled={locked || (index > 0 && !masterApproved)} onClick={() => { setNoteFor(index); setNote(""); }}>Not right</button>
                      </div>
                    ) : !busy && (
                      <button className="btn btn-sm" disabled={redo.isPending || (index > 0 && !masterApproved)} onClick={() => redo.mutate({ index, text: "" })}><RefreshCw size={14} aria-hidden="true" />Try again</button>
                    )}
                    {learned.includes(index) && !busy && <span className="check-ok">Saved as a rule. The AI will avoid this in the next videos.</span>}
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
            ) : makingVideo ? (
              <div className="row" role="status" aria-live="polite" style={{ gap: 10 }}><Spinner size={18} /><strong>{`${friendlyStep(run?.step ?? "")}…`}</strong></div>
            ) : masterApproved && frames.length < shots.length && (
              <button className="btn btn-primary btn-lg btn-block" disabled={start.isPending} onClick={() => start.mutate({ until: "images" })}>{start.isPending ? "Starting…" : "Create the other scenes"}</button>
            )}
            {making ? (
              <span className="muted small">This takes about 8 minutes. You can leave this page. We tell you when it is done.</span>
            ) : makingVideo ? (
              <span className="muted small">This takes about 10 minutes. You can leave this page. We tell you when it is done.</span>
            ) : hasVideo ? (
              <span className="muted small">Your video is ready below.</span>
            ) : all && needsLook.length > 0 ? (
              <button className="btn btn-lg btn-block" disabled>{`Look at scene ${needsLook[0] + 1} first`}</button>
            ) : all ? (
              <>
                <button className="btn btn-primary btn-lg btn-block" disabled={start.isPending} onClick={() => start.mutate({ until: "video" })}>{start.isPending ? "Starting…" : "Make the video from these scenes"}</button>
                <span className="muted small">Making the video takes about 10 minutes. You can leave the page.</span>
              </>
            ) : (
              <button className="btn btn-lg btn-block" disabled>Approve every scene to continue</button>
            )}
            <ErrorNote error={start.error} />
            {run && runStopped(run) && needsLook.length === 0 && <div className="notice notice-warn" role="alert"><div>The last run stopped. {run.message}</div></div>}
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
