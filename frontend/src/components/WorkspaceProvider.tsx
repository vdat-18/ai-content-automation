import { useCallback, useEffect, useState, type ReactNode } from "react";
import { WorkspaceContext } from "../hooks/useWorkspace";

export function WorkspaceProvider({ children }: { children: ReactNode }) {
  const [notice, setNotice] = useState<{ message: string; tone: "success" | "error" } | null>(null);
  const notify = useCallback((message: string, tone: "success" | "error") => setNotice({ message, tone }), []);
  useEffect(() => {
    if (!notice) return;
    const timer = window.setTimeout(() => setNotice(null), 6500);
    return () => window.clearTimeout(timer);
  }, [notice]);
  return (
    <WorkspaceContext.Provider value={{ notify }}>
      {children}
      {notice && (
        <div className={`toast${notice.tone === "error" ? " toast-error" : ""}`} role={notice.tone === "error" ? "alert" : "status"}>
          <span>{notice.message}</span>
          <button aria-label="Dismiss" onClick={() => setNotice(null)}>×</button>
        </div>
      )}
    </WorkspaceContext.Provider>
  );
}
