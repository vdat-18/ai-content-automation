import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ErrorNote, Spinner } from "../../components/ui";
import { API, useClips } from "../../hooks/useStudio";
import { postJson, putJson } from "../../services/http";

/** The clips that need a person: failed, flagged by the AI check, or still being made. */
export function ClipsPanel({ productId }: { productId: string }) {
  const client = useQueryClient();
  const clips = useClips(productId);
  const refresh = () => client.invalidateQueries({ queryKey: ["clips", productId] });
  const remake = useMutation({ mutationFn: (index: number) => postJson(`${API}/${productId}/clips`, { shot_index: index }), onSuccess: refresh });
  const accept = useMutation({ mutationFn: (index: number) => putJson(`${API}/${productId}/clips/${index}/review`, {}), onSuccess: refresh });
  const needsLook = (clips.data ?? []).filter((clip) => clip.status !== "ready" || clip.qa_problem);
  if (needsLook.length === 0) return null;

  return (
    <div className="card pad stack" style={{ maxWidth: 640 }}>
      <h2>Scenes that need a look</h2>
      <p className="muted small">Making a scene again films it again and costs one more clip.</p>
      {needsLook.map((clip) => {
        const remaking = remake.isPending && remake.variables === clip.shot_index;
        const busy = remaking || (accept.isPending && accept.variables === clip.shot_index);
        return (
          <div key={clip.shot_index} className="stack" style={{ gap: 8 }}>
            <strong>{`Scene ${clip.shot_index + 1}`}</strong>
            {clip.status === "ready" && <video src={`${API}/${productId}/clips/${clip.shot_index}/video?v=${clip.attempts}`} controls playsInline preload="metadata" style={{ maxHeight: 260, alignSelf: "flex-start" }} />}
            {clip.status === "processing" && <span className="muted small"><Spinner size={14} /> Still being filmed</span>}
            {clip.status === "failed" && <p className="check-warn">{`This scene could not be filmed: ${clip.error ?? "the video job failed"}`}</p>}
            {clip.qa_problem && <p className="check-warn">{`The AI suggests a second look: ${clip.qa_problem}`}</p>}
            {clip.status !== "processing" && (
              <div className="row">
                <button className="btn btn-sm" disabled={busy} onClick={() => remake.mutate(clip.shot_index)}>{remaking ? <><Spinner size={14} />Starting…</> : "Make this scene again"}</button>
                {clip.status === "ready" && <button className="btn btn-ok btn-sm" disabled={busy} onClick={() => accept.mutate(clip.shot_index)}>Use it as it is</button>}
              </div>
            )}
          </div>
        );
      })}
      <ErrorNote error={remake.error ?? accept.error} />
    </div>
  );
}
