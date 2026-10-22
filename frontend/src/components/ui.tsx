import type { ReactNode } from "react";
import { useI18n } from "../hooks/useI18n";

export function Badge({ children, tone = "neutral" }: { children: ReactNode; tone?: "success" | "warning" | "danger" | "info" | "neutral" | "violet" }) {
  const { t } = useI18n();
  return <span className={`badge badge--${tone}`}>{typeof children === "string" ? t(children) : children}</span>;
}

export function StatusBadge({ status }: { status: string }) {
  const { t } = useI18n();
  const normalized = status.replaceAll("_", " ");
  const tone = ["approved", "completed", "healthy", "pass", "resolved", "sent", "booked", "ready", "supported"].includes(status)
    ? "success"
    : ["rejected", "failed", "critical", "disconnected", "fail", "blocked", "mismatch"].includes(status)
      ? "danger"
      : ["waiting", "pending", "delayed", "warning", "awaiting_approval", "qa_review", "waiting_reply", "unknown", "partial"].includes(status)
        ? "warning"
        : ["running", "testing", "in_progress", "generating", "processing", "revising", "handoff", "scheduled"].includes(status)
          ? "info"
          : "neutral";
  return <Badge tone={tone}>{t(normalized)}</Badge>;
}

export function PageHeader({ eyebrow, title, description, actions, variant = "default" }: { eyebrow: string; title: string; description?: string; actions?: ReactNode; variant?: "default" | "campaign" | "library" | "decision" | "analytics" | "operator" }) {
  const { t } = useI18n();
  return (
    <header className={`page-header page-header--${variant}`}>
      <div>
        <p className="eyebrow">{t(eyebrow)}</p>
        <h1>{t(title)}</h1>
        {description && <p className="page-description">{t(description)}</p>}
      </div>
      {actions && <div className="page-actions">{actions}</div>}
      {variant !== "operator" && <span className="page-header__art" aria-hidden="true"><i /><i /><i /></span>}
    </header>
  );
}

export function Panel({ children, className = "", id }: { children: ReactNode; className?: string; id?: string }) {
  return <section id={id} className={`panel ${className}`}>{children}</section>;
}

export function PanelHeader({ title, meta, action }: { title: string; meta?: string; action?: ReactNode }) {
  const { t } = useI18n();
  return (
    <div className="panel-header">
      <div><h2>{t(title)}</h2>{meta && <p>{t(meta)}</p>}</div>
      {action}
    </div>
  );
}

export function SkeletonPage() {
  return <div className="skeleton-page"><div /><div className="skeleton-grid"><span /><span /><span /></div><div className="skeleton-panel" /></div>;
}

export function EmptyState({ icon, title, text }: { icon: ReactNode; title: string; text: string }) {
  const { t } = useI18n();
  return (
    <div className="empty-state">
      <div className="empty-state-icon">{icon}</div>
      <h3>{t(title)}</h3>
      <p>{t(text)}</p>
    </div>
  );
}
