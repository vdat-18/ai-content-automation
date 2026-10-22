import { createContext, useContext } from "react";

export const WorkspaceContext = createContext<{
  brand: string;
  setBrand: (brand: string) => void;
  notify: (message: string, tone: "success" | "error") => void;
} | null>(null);
export function useWorkspace() {
  const value = useContext(WorkspaceContext);
  if (!value) throw new Error("WorkspaceProvider is required.");
  return value;
}
