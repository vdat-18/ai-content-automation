import type { BriefRecord, Keyframe, PipelineRun } from "../types/studio";

export type StepId = "idea" | "images";
export const STEPS: { id: StepId; label: string }[] = [
  { id: "idea", label: "Idea" },
  { id: "images", label: "Scenes and video" },
];

/** What the server is doing, in words a marketer uses. */
export function friendlyStep(step: string): string {
  const text = step.toLowerCase();
  if (text.includes("storyboard") || text.includes("reference")) return "Writing your script";
  if (text.includes("master")) return "Creating the first image";
  if (text.includes("keyframe")) return "Creating the other scenes";
  if (text.includes("clip")) return "Filming the scenes";
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
export const checkNote = (problem: string) => (problem ? (isUnchecked(problem) ? problem : `The AI suggests a second look: ${problem}`) : "The AI check found no problem");

export function imagesApproved(brief: BriefRecord | null | undefined, keyframes: Keyframe[]): boolean {
  const shots = brief?.brief.shots?.length ?? 0;
  return shots > 0 && Array.from({ length: shots }, (_, index) => keyframes.find((k) => k.shot_index === index)?.status === "approved").every(Boolean);
}

export function doneSteps(brief: BriefRecord | null | undefined, keyframes: Keyframe[], hasVideo: boolean): Record<StepId, boolean> {
  return { idea: !!brief, images: hasVideo };
}

/** The step a person most likely wants next: scenes and video are one page. */
export const suggestedStep = (brief: BriefRecord | null | undefined): StepId => (brief ? "images" : "idea");

/** A product can have many videos: the id of a video is the product id, then "-v" and a suffix. */
export const productOf = (projectId: string) => projectId.split("-v")[0];
export const newProjectId = (productId: string) => `${productId}-v${Date.now().toString(36)}`;

export const toNumber = (value: number | string | null | undefined) => Number(String(value ?? 0).replace(/[.,]/g, "")) || 0;
export const vnd = (value: string | null | undefined) => (value ? `${toNumber(value).toLocaleString("en-US")} ₫` : "");
