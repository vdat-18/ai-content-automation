import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { ErrorNote } from "../../components/ui";
import { useLightbox } from "../../hooks/useLightbox";
import { API } from "../../hooks/useStudio";
import { getJson, putJson } from "../../services/http";
import type { Brief, BriefRecord, Keyframe, Shot } from "../../types/studio";

const wordCount = (text: string) => text.split(/\s+/).filter(Boolean).length;
type SceneImage = { image_id: string; image_url: string; title: string };

export function ScriptStep({ productId, record, frames }: { productId: string; record: BriefRecord; frames: Keyframe[] }) {
  const [, setParams] = useSearchParams();
  const client = useQueryClient();
  const lightbox = useLightbox();
  const brief = record.brief;
  const shots = brief.shots ?? [];
  const problems = brief.quality_problems ?? [];
  const warnings = brief.warnings ?? [];
  const [references, setReferences] = useState<(string | null)[]>(() => shots.map((_, index) => brief.shot_references?.[index] ?? null));
  const scenes = useQuery({ queryKey: ["reference-images", "live"], queryFn: ({ signal }) => getJson<SceneImage[]>(`${API}/reference-images?status=live`, signal) });
  const sceneById = new Map((scenes.data ?? []).map((scene) => [scene.image_id, scene]));
  const chooseReference = (index: number, imageId: string | null) => setReferences((current) => current.map((item, at) => (at === index ? imageId : item)));
  const save = useMutation({
    mutationFn: (next: Partial<Brief>) => putJson<BriefRecord>(`${API}/${productId}/brief`, { brief: next, status: "approved" }),
    onSuccess: (saved) => {
      client.setQueryData(["brief", productId], saved);
      void client.invalidateQueries({ queryKey: ["briefs"] });
      setParams({ step: "images" });
    },
  });
  const frameFor = (index: number) => frames.find((frame) => frame.shot_index === index && frame.status !== "failed");

  return (
    <>
      <header className="page-head"><div><h1>Your script</h1><p>Read it like a script. Change any line, the voice-over follows what you write here.</p></div></header>
      {problems.length > 0 && (
        <div className="notice notice-warn" role="status">
          <div>
            {problems.length === 1 ? "The AI reviewer found 1 thing worth a second look:" : `The AI reviewer found ${problems.length} things worth a second look:`}
            <ul>{problems.map((problem) => <li key={problem}>{problem}</li>)}</ul>
          </div>
        </div>
      )}
      {warnings.length > 0 && (
        <div className="notice notice-warn" role="status"><div>TikTok may flag these words. Rewrite them before posting:<ul>{warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul></div></div>
      )}
      <form
        className="stack-lg"
        onSubmit={(event) => {
          event.preventDefault();
          const data = new FormData(event.currentTarget);
          const edited: Shot[] = shots.map((shot, index) => ({
            ...shot,
            voiceover: String(data.get(`voiceover_${index}`)),
            on_screen_text: String(data.get(`text_${index}`)),
            description: String(data.get(`description_${index}`)),
            keyframe_prompt: String(data.get(`keyframe_${index}`)),
            motion_prompt: String(data.get(`motion_${index}`)),
          }));
          save.mutate({ title: String(data.get("title")), shots: edited, shot_references: references, script: edited.map((shot) => shot.voiceover.trim()).filter(Boolean).join(" ") });
        }}
      >
        <label className="field" style={{ maxWidth: 560 }}>Video title<input type="text" name="title" defaultValue={brief.title} /></label>
        {shots.map((shot, index) => {
          const frame = frameFor(index);
          const src = frame ? `${API}/${productId}/keyframes/${index}/image?v=${frame.attempts}` : null;
          return (
            <section className="card shot-edit" key={`${index}-${shot.keyframe_prompt.slice(0, 20)}`} aria-label={`Scene ${index + 1}`}>
              {src ? <img src={src} alt={`Scene ${index + 1}`} {...lightbox.zoom([{ src }], 0)} /> : <div className="muted small">No image yet</div>}
              <div className="stack">
                <div className="row">
                  <h2>{`Scene ${index + 1}`}</h2>
                  <span className="pill pill-quiet">{shot.delivery === "talking" ? "The person talks to the camera" : "Voice-over"}</span>
                </div>
                <label className="field">What is said<textarea name={`voiceover_${index}`} rows={3} defaultValue={shot.voiceover} /><span className="muted small" style={{ fontWeight: 400 }}>{`${wordCount(shot.voiceover)} words`}</span></label>
                <label className="field">Text on the screen<input type="text" name={`text_${index}`} defaultValue={shot.on_screen_text} /></label>
                <div className="field">
                  Reference photo
                  <div className="row">
                    {sceneById.get(references[index] ?? "") ? (
                      <img className="ref-thumb" src={sceneById.get(references[index] ?? "")?.image_url} alt="Reference for this scene" referrerPolicy="no-referrer" />
                    ) : (
                      <span className="muted small" style={{ fontWeight: 400 }}>{references[index] ? "This reference was removed" : "No reference: the AI draws the room freely"}</span>
                    )}
                    {references[index] && <button className="btn btn-sm" type="button" onClick={() => chooseReference(index, null)}>No reference</button>}
                  </div>
                  <details>
                    <summary className="muted small" style={{ cursor: "pointer" }}>Choose another reference</summary>
                    <div className="ref-grid">
                      {(scenes.data ?? []).slice(0, 60).map((scene) => (
                        <button key={scene.image_id} type="button" aria-pressed={references[index] === scene.image_id} aria-label={scene.title || "Reference photo"} onClick={() => chooseReference(index, scene.image_id)}>
                          <img className="ref-thumb" src={scene.image_url} alt="" loading="lazy" referrerPolicy="no-referrer" />
                        </button>
                      ))}
                      {scenes.data?.length === 0 && <span className="muted small">No reference photos yet. Collect them from Pinterest first.</span>}
                    </div>
                  </details>
                </div>
                <details>
                  <summary className="muted small" style={{ cursor: "pointer" }}>Advanced: what the AI is told to draw and film</summary>
                  <div className="stack" style={{ marginTop: 10 }}>
                    <label className="field">What the viewer sees<textarea name={`description_${index}`} rows={2} defaultValue={shot.description} /></label>
                    <label className="field">Instruction for the picture<textarea name={`keyframe_${index}`} rows={4} defaultValue={shot.keyframe_prompt} /></label>
                    <label className="field">Instruction for the movement<textarea name={`motion_${index}`} rows={4} defaultValue={shot.motion_prompt} /></label>
                  </div>
                </details>
              </div>
            </section>
          );
        })}
        <ErrorNote error={save.error} />
        <div className="row">
          <button className="btn btn-primary btn-lg" type="submit" disabled={save.isPending}>{save.isPending ? "Saving…" : "Save and continue to the images"}</button>
          <button className="btn btn-lg" type="button" onClick={() => setParams({ step: "images" })}>Skip, keep the script as it is</button>
        </div>
      </form>
      {lightbox.node}
    </>
  );
}
