import { useQuery } from "@tanstack/react-query";
import { pilotApi } from "../services/pilotApi";

const pilotDashboardKey = ["pilot-dashboard"] as const;

export function usePilotDashboard() {
  return useQuery({
    queryKey: pilotDashboardKey,
    queryFn: ({ signal }) => pilotApi.dashboard(signal),
    refetchInterval: (query) => query.state.data?.summary.active_commands ? 2000 : 15000,
  });
}

export function useCreativeJobs() {
  return useQuery({
    queryKey: ["creative-jobs"],
    queryFn: ({ signal }) => pilotApi.creativeJobs(signal),
    refetchInterval: 15000,
  });
}

export function useCreativeJob(jobId: string | undefined) {
  return useQuery({
    queryKey: ["creative-job", jobId],
    queryFn: ({ signal }) => pilotApi.creativeJob(jobId!, signal),
    enabled: Boolean(jobId),
    refetchInterval: (query) => query.state.data?.status === "awaiting_approval" ? 15000 : false,
  });
}

export function useGmcRuns() {
  return useQuery({
    queryKey: ["pilot-gmc-runs"],
    queryFn: ({ signal }) => pilotApi.gmcRuns(signal),
  });
}

export function useAIUsage(query: string) {
  return useQuery({
    queryKey: ["ai-usage", query],
    queryFn: ({ signal }) => pilotApi.aiUsage(query, signal),
  });
}

export function useAIUsageEvents(query: string) {
  return useQuery({
    queryKey: ["ai-usage-events", query],
    queryFn: ({ signal }) => pilotApi.aiUsageEvents(query, signal),
  });
}

export function useAIUsageEvent(eventId: string | null) {
  return useQuery({
    queryKey: ["ai-usage-event", eventId],
    queryFn: ({ signal }) => pilotApi.aiUsageEvent(eventId ?? "", signal),
    enabled: eventId !== null,
  });
}

export function useAIUsageRuns(query: string) {
  return useQuery({
    queryKey: ["ai-usage-runs", query],
    queryFn: ({ signal }) => pilotApi.aiUsageRuns(query, signal),
  });
}

export function useNotifications() {
  return useQuery({
    queryKey: ["notifications"],
    queryFn: ({ signal }) => pilotApi.notifications(false, signal),
    refetchInterval: 15000,
  });
}
