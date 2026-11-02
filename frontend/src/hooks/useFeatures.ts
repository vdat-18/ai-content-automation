import { useQuery } from "@tanstack/react-query";
import { pilotApi } from "../services/pilotApi";

export function useFeatures() {
  return useQuery({
    queryKey: ["features"],
    queryFn: ({ signal }) => pilotApi.features(signal),
    staleTime: Infinity,
  });
}
