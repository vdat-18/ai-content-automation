import { FileText, Images } from "lucide-react";
import { NavLink, useSearchParams } from "react-router-dom";

import { useI18n } from "../hooks/useI18n";
import { CreativesPage } from "./CreativeJobs";
import { MediaLibraryPage } from "./MediaLibrary";

export function CreativeLibraryPage() {
  const { t } = useI18n();
  const [searchParams] = useSearchParams();
  const view = searchParams.get("view") === "media" ? "media" : "creatives";

  return <>
    <nav className="creative-library-tabs" aria-label={t("Creative Library views")}>
      <NavLink className={view === "creatives" ? "is-active" : ""} to="/creatives" end>
        <FileText size={16} />{t("Creative jobs & briefs")}
      </NavLink>
      <NavLink className={view === "media" ? "is-active" : ""} to="/creatives?view=media">
        <Images size={16} />{t("Generated media")}
      </NavLink>
    </nav>
    {view === "media" ? <MediaLibraryPage /> : <CreativesPage />}
  </>;
}
