import { useQuery } from "@tanstack/react-query";
import { Check } from "lucide-react";
import { Spinner } from "../../components/ui";
import { API } from "../../hooks/useStudio";
import { friendlyStep } from "../../lib/studio";
import { getJson } from "../../services/http";
import type { BriefRecord, Keyframe, PipelineRun } from "../../types/studio";

const STAGES = ["Writing your script", "Creating the first image", "Creating the other scenes", "Filming the scenes", "Recording the voice-over", "Putting the video together", "Writing the caption"];

/** Shown while the server works: where it is, how long it takes, and that the user may leave. */
export function Working({ run, record, frames }: { productId: string; run: PipelineRun; record: BriefRecord | null; frames: Keyframe[] }) {
  const current = friendlyStep(run.step);
  const index = Math.max(0, STAGES.indexOf(current));
  const scenes = useQuery({ queryKey: ["reference-images", "live"], queryFn: ({ signal }) => getJson<{ image_id: string; image_url: string }[]>(`${API}/reference-images?status=live`, signal), enabled: !!record });
  const shots = record?.brief.shots ?? [];
  const toVideo = index >= 3 || (record?.status === "approved" && frames.some((frame) => frame.status === "approved") && index > 0);
  return (
    <div className="card pad stack" style={{ maxWidth: 640 }} role="status" aria-live="polite">
      <div className="row" style={{ gap: 14 }}>
        <Spinner size={28} />
        <h1 style={{ fontSize: 24 }}>{current}…</h1>
      </div>
      <p className="muted">
        {toVideo ? "Making the video takes about 10 minutes." : index === 0 ? "Writing the script takes about a minute." : "Creating the images takes about 8 minutes."} You can leave this page. We keep working and tell you when it is done.
      </p>
      <ol className="stack" style={{ listStyle: "none", margin: 0, padding: 0, gap: 8 }}>
        {STAGES.filter((_, i) => (toVideo ? i >= 3 : i < 3)).map((label) => {
          const position = STAGES.indexOf(label);
          return (
            <li key={label} className="row" style={{ color: position < index ? "var(--ok)" : position === index ? "var(--brand)" : "var(--muted)", fontWeight: position === index ? 600 : 400 }}>
              {position < index ? <Check size={16} aria-hidden="true" /> : position === index ? <Spinner size={14} /> : <span style={{ width: 16 }} />}
              {label}
            </li>
          );
        })}
      </ol>
      {shots.length > 0 && (
        <section className="stack" aria-label="The script so far">
          <h2 style={{ fontSize: 18 }}>{record?.brief.title}</h2>
          {shots.map((shot, at) => {
            const reference = scenes.data?.find((scene) => scene.image_id === record?.brief.shot_references?.[at]);
            return (
              <div key={at} className="row" style={{ alignItems: "flex-start", gap: 12 }}>
                {reference ? <img className="ref-thumb" style={{ width: 56, aspectRatio: "1", objectFit: "cover", borderRadius: 8 }} src={reference.image_url} alt="Reference for this scene" referrerPolicy="no-referrer" /> : <span className="muted small" style={{ width: 56 }}>{index > 0 ? "No reference" : ""}</span>}
                <div className="stack" style={{ gap: 2 }}>
                  <strong className="small">{`Scene ${at + 1}`}</strong>
                  <span className="small">{shot.voiceover}</span>
                  {shot.on_screen_text && <span className="muted small">{`On screen: ${shot.on_screen_text}`}</span>}
                </div>
              </div>
            );
          })}
        </section>
      )}
    </div>
  );
}
