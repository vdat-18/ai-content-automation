import { ArrowRight, CheckCircle2, Clock3 } from "lucide-react";
import { Link } from "react-router-dom";

import { useI18n } from "../hooks/useI18n";
import { dashboardStreamLabels, decisionPrompt } from "../marketing/labels";
import type { DashboardApproval } from "../types/pilotApi";
import { Badge } from "./ui";

function waitingLabel(value: string, locale: string, t: (source: string, variables?: Record<string, string | number>) => string) {
  const elapsed = Math.max(0, Date.now() - new Date(value).getTime());
  const hours = Math.floor(elapsed / 3_600_000);
  if (hours < 1) return t("Waiting less than an hour");
  if (hours < 24) return t("Waiting {count}h", { count: hours });
  const days = Math.floor(hours / 24);
  return new Intl.RelativeTimeFormat(locale, { numeric: "auto" }).format(-days, "day");
}

export function DecisionCard({
  approval,
  previewUrl,
  compact = false,
}: {
  approval: DashboardApproval;
  previewUrl?: string;
  compact?: boolean;
}) {
  const { t, locale, formatDate } = useI18n();
  const prompt = t(decisionPrompt(approval.decision_type));
  return (
    <article className={`decision-card ${previewUrl ? "decision-card--preview" : ""} ${compact ? "decision-card--compact" : ""}`}>
      {previewUrl
        ? <img className="decision-card__preview" src={previewUrl} alt="" />
        : <span className="decision-card__icon" aria-hidden="true"><CheckCircle2 size={21} /></span>}
      <div className="decision-card__body">
        <div className="decision-card__meta">
          <Badge tone="info">{t(dashboardStreamLabels[approval.workstream])}</Badge>
          {approval.brand_id && <span>{approval.brand_id}</span>}
          <span title={formatDate(approval.created_at)}><Clock3 size={13} />{waitingLabel(approval.created_at, locale, t)}</span>
        </div>
        <h2>{prompt}</h2>
        {!compact && <p>{approval.detail}</p>}
      </div>
      <Link className="decision-card__action" to={approval.action_path} aria-label={`${t("Review decision")}: ${prompt}`}>
        <span>{t("Review decision")}</span><ArrowRight size={17} />
      </Link>
    </article>
  );
}
