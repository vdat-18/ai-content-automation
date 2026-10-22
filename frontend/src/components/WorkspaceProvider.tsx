import { useCallback, useEffect, useState, type ReactNode } from "react";
import { WorkspaceContext } from "../hooks/useWorkspace";
import { useI18n } from "../hooks/useI18n";

export function WorkspaceProvider({ children }: { children: ReactNode }) {
  const { t } = useI18n();
  const [brand, updateBrand] = useState(() => sessionStorage.getItem("aic-workspace-brand") ?? "all");
  const setBrand = useCallback((value: string) => {
    sessionStorage.setItem("aic-workspace-brand", value);
    updateBrand(value);
  }, []);
  const [notice, setNotice] = useState<{ message: string; tone: "success" | "error" } | null>(null);
  const notify = useCallback((message: string, tone: "success" | "error") => setNotice({ message: t(message), tone }), [t]);
  useEffect(() => {
    if (!notice) return;
    const timer = window.setTimeout(() => setNotice(null), 6500);
    return () => window.clearTimeout(timer);
  }, [notice]);
  return <WorkspaceContext.Provider value={{ brand, setBrand, notify }}>{children}
    {notice && <div className={"toast toast--" + notice.tone} role={notice.tone === "error" ? "alert" : "status"}><span>{notice.message}</span><button aria-label={t("Dismiss notification")} onClick={() => setNotice(null)}>×</button></div>}
  </WorkspaceContext.Provider>;
}
