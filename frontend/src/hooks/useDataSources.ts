import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { pilotApi } from "../services/pilotApi";
import { useWorkspace } from "./useWorkspace";

const dataSourcesKey = ["data-sources"] as const;

export function useDataSources() {
  return useQuery({
    queryKey: dataSourcesKey,
    queryFn: ({ signal }) => pilotApi.dataSources(signal),
    refetchInterval: (query) => query.state.data?.items.some((source) => source.sync_status) ? 2_000 : false,
  });
}

export function useDataSourceSync() {
  const client = useQueryClient();
  const { notify } = useWorkspace();
  return useMutation({
    mutationFn: pilotApi.syncDataSource,
    onSuccess: async (result) => {
      await Promise.all([
        client.invalidateQueries({ queryKey: dataSourcesKey }),
      ]);
      notify(result.created ? "Source sync queued." : "Source sync is already running.", "success");
    },
    onError: (error: Error) => notify(error.message, "error"),
  });
}

export function useDataSourcesSyncAll() {
  const client = useQueryClient();
  const { notify } = useWorkspace();
  return useMutation({
    mutationFn: pilotApi.syncAllDataSources,
    onSuccess: async (result) => {
      await Promise.all([
        client.invalidateQueries({ queryKey: dataSourcesKey }),
      ]);
      notify(result.created ? "All source syncs queued." : "Source sync is already running.", "success");
    },
    onError: (error: Error) => notify(error.message, "error"),
  });
}
