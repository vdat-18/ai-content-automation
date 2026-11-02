import { useQuery } from "@tanstack/react-query";
import { pilotApi } from "../services/pilotApi";

export function useNotifications() {
  return useQuery({
    queryKey: ["notifications"],
    queryFn: ({ signal }) => pilotApi.notifications(false, signal),
    refetchInterval: 15000,
  });
}
