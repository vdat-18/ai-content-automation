import type { BriefRecord, Keyframe, PipelineRun } from "../types/studio";

export type StepId = "idea" | "images" | "finish";
export const STEPS: { id: StepId; label: string }[] = [
  { id: "idea", label: "Idea" },
  { id: "images", label: "Images" },
  { id: "finish", label: "Finish" },
];

/** What the server is doing, in words a marketer uses. */
export function friendlyStep(step: string): string {
  const text = step.toLowerCase();
  if (text.includes("storyboard") || text.includes("reference")) return "Writing your script";
  if (text.includes("master")) return "Creating the first image";
  if (text.includes("keyframe")) return "Creating the other scenes";
  if (text.includes("clips")) return "Filming the scenes";
  if (text.includes("voice")) return "Recording the voice-over";
  if (text.includes("stitching")) return "Putting the video together";
  if (text.includes("caption")) return "Writing the caption";
  return "Getting started";
}

/** The last run did not finish: it needs a look, failed, or was cut off by a restart. */
export const runStopped = (run: PipelineRun | undefined) => !!run && ["paused", "failed", "interrupted"].includes(run.status);

/** The AI check could not run, so a person has to look at the picture or clip. */
export const isUnchecked = (problem: string) => problem.startsWith("Not checked");

/** What to tell the person about the AI check of one picture or clip. */
export const checkNote = (problem: string) => (problem ? (isUnchecked(problem) ? problem : `The AI suggests a second look: ${problem}`) : "The AI checked: matches the real product");

export function imagesApproved(brief: BriefRecord | null | undefined, keyframes: Keyframe[]): boolean {
  const shots = brief?.brief.shots?.length ?? 0;
  return shots > 0 && Array.from({ length: shots }, (_, index) => keyframes.find((k) => k.shot_index === index)?.status === "approved").every(Boolean);
}

export function doneSteps(brief: BriefRecord | null | undefined, keyframes: Keyframe[], hasVideo: boolean): Record<StepId, boolean> {
  return { idea: !!brief, images: imagesApproved(brief, keyframes), finish: hasVideo };
}

/** The step a person most likely wants next. */
export function suggestedStep(brief: BriefRecord | null | undefined, keyframes: Keyframe[], hasVideo: boolean, run?: PipelineRun): StepId {
  if (!brief) return "idea";
  if (hasVideo) return "finish";
  // With every scene approved the Images page already has the button that makes the video: the Finish page opens once the video run has started
  const filming = !!run && ["Filming the scenes", "Recording the voice-over", "Putting the video together", "Writing the caption"].includes(friendlyStep(run.step));
  return imagesApproved(brief, keyframes) && filming ? "finish" : "images";
}

export const toNumber = (value: number | string | null | undefined) => Number(String(value ?? 0).replace(/[.,]/g, "")) || 0;
export const vnd = (value: string | null | undefined) => (value ? `${toNumber(value).toLocaleString("en-US")} ₫` : "");
