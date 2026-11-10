import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, getJson, postJson } from "../services/http";
import type { BriefRecord, Clip, Keyframe, OutputItem, PersonSummary, PipelineRun, Product, RunEvent, VideoInfo } from "../types/studio";

export const API = "/api/v1/products";

export const useProducts = () =>
  useQuery({ queryKey: ["products"], queryFn: ({ signal }) => getJson<Product[]>(API, signal), refetchInterval: 15000 });

/** product id -> search keyword; a null keyword means it is still being prepared */
export const useSelections = () =>
  useQuery({
    queryKey: ["product-selections"],
    queryFn: ({ signal }) => getJson<Record<string, string | null>>(`${API}/selections`, signal),
    refetchInterval: (query) => (Object.values(query.state.data ?? {}).some((type) => !type) ? 3000 : false),
  });

export const useOutputs = () => useQuery({ queryKey: ["outputs"], queryFn: ({ signal }) => getJson<OutputItem[]>(`${API}/outputs`, signal) });

export const useBriefs = () => useQuery({ queryKey: ["briefs"], queryFn: ({ signal }) => getJson<BriefRecord[]>(`${API}/briefs`, signal) });

export const useBrief = (productId: string) =>
  useQuery({
    queryKey: ["brief", productId],
    queryFn: async ({ signal }) => {
      try {
        return await getJson<BriefRecord>(`${API}/${productId}/brief`, signal);
      } catch (error) {
        if (error instanceof ApiError && error.status === 404) return null;
        throw error;
      }
    },
  });

export const usePipeline = (productId: string) =>
  useQuery({
    queryKey: ["pipeline", productId],
    queryFn: ({ signal }) => getJson<PipelineRun>(`${API}/${productId}/pipeline`, signal),
    refetchInterval: (query) => (query.state.data?.status === "running" ? 2000 : false),
  });

export const useKeyframes = (productId: string, enabled = true) =>
  useQuery({
    queryKey: ["keyframes", productId],
    queryFn: ({ signal }) => getJson<Keyframe[]>(`${API}/${productId}/keyframes`, signal),
    enabled,
  });

export const useClips = (productId: string, enabled = true) =>
  useQuery({
    queryKey: ["clips", productId],
    queryFn: ({ signal }) => getJson<Clip[]>(`${API}/${productId}/clips`, signal),
    refetchInterval: (query) => (query.state.data?.some((clip) => clip.status === "processing") ? 5000 : false),
    enabled,
  });

export const useVideoInfo = (productId: string) =>
  useQuery({ queryKey: ["video-info", productId], queryFn: ({ signal }) => getJson<VideoInfo>(`${API}/${productId}/video-info`, signal) });

export const usePerson = (productId: string) =>
  useQuery({ queryKey: ["persona", productId], queryFn: ({ signal }) => getJson<PersonSummary>(`${API}/${productId}/persona`, signal) });

export const useEvents = (productId: string, running: boolean) =>
  useQuery({
    queryKey: ["run-log", productId],
    queryFn: ({ signal }) => getJson<RunEvent[]>(`${API}/${productId}/events`, signal),
    refetchInterval: running ? 3000 : false,
  });

export const VOICE_KEY = "aic-voice";

/** Start the server-side run. until="images" stops for review; "video" goes on to the finished video. */
export function useStartPipeline(productId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: { until: "images" | "video"; idea?: string; video_seconds?: number }) =>
      postJson<PipelineRun>(`${API}/${productId}/pipeline`, {
        idea: "",
        video_seconds: 30,
        voice: window.localStorage.getItem(VOICE_KEY) || null,
        ...body,
      }),
    onSuccess: (run) => client.setQueryData(["pipeline", productId], run),
  });
}
