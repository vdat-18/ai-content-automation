export type Shot = {
  role: string;
  description: string;
  keyframe_prompt: string;
  motion_prompt: string;
  delivery?: "narrated" | "talking";
  duration_seconds: number;
  on_screen_text: string;
  voiceover: string;
};
export type PostPackage = { captions: string[]; hashtags: string[]; product_url: string; warnings?: string[]; ai_label_reminder?: string };
export type Brief = {
  title: string;
  script?: string;
  quality_problems?: string[];
  warnings?: string[];
  shots?: Shot[];
  post_package?: PostPackage;
  with_person?: boolean;
};
export type BriefRecord = { product_id: string; user_idea: string; brief: Brief; status: "draft" | "approved" };
export type Keyframe = { shot_index: number; status: "ready" | "approved" | "rejected" | "failed"; attempts: number; error: string | null; qa_problem: string };
export type Clip = { shot_index: number; status: "processing" | "ready" | "failed"; seconds: number; attempts: number; error: string | null; qa_problem: string };
export type PipelineRun = { status: "idle" | "running" | "paused" | "failed" | "done"; step: string; message: string };
export type Product = {
  product_id: string;
  title: string | null;
  url: string;
  price: { sale: string | null };
  sold_count: number | string | null;
  rating: number | string | null;
  seller: { name: string | null };
  images: string[];
};
export type OutputItem = {
  product_id: string;
  title: string | null;
  product_title: string | null;
  image: string | null;
  built_at: string | null;
  seconds: number | null;
  shots: number;
  has_cover: boolean;
};
export type VideoInfo = { exists: boolean; voiceover: boolean };
export type RunEvent = { id: number; at: string; step: string; shot_index: number | null; status: string; message: string };
export type Voice = { id: string; label: string };
export type PersonSummary = { photos: number; attempts: number };
