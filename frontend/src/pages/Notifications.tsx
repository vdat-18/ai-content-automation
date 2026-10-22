import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bell, Check, ExternalLink } from "lucide-react";
import { Link } from "react-router-dom";
import { EmptyState, PageHeader, Panel, SkeletonPage } from "../components/ui";
import { useI18n } from "../hooks/useI18n";
import { pilotApi } from "../services/pilotApi";

export function NotificationsPage() {
  const { t } = useI18n();
  const client = useQueryClient();
  const query = useQuery({
    queryKey: ["notifications"],
    queryFn: ({ signal }) => pilotApi.notifications(false, signal),
    refetchInterval: 15000,
  });
  const markRead = useMutation({
    mutationFn: pilotApi.markNotificationRead,
    onSuccess: () => client.invalidateQueries({ queryKey: ["notifications"] }),
  });

  if (query.isLoading) return <SkeletonPage />;
  if (query.error || !query.data) {
    return <EmptyState icon={<Bell />} title="Could not load notifications" text={query.error?.message ?? "The notification service returned no data."} />;
  }

  return (
    <>
      <PageHeader
        eyebrow="Marketing workspace"
        title="Notifications"
        description="Only actionable Creative events and completed batches appear here."
        actions={<span className="badge badge--warning">{query.data.unread} {t("unread")}</span>}
      />
      <div className="notification-list">
        {query.data.items.map((item) => (
          <Panel key={item.notification_id} className={`notification-row ${item.read_at ? "is-read" : "is-unread"}`}>
            <div className="notification-row__marker" aria-hidden="true" />
            <div className="notification-row__copy">
              <div>
                <strong>{item.title}</strong>
                <time dateTime={item.created_at}>{new Date(item.created_at).toLocaleString()}</time>
              </div>
              <p>{item.detail}</p>
              <small>{item.kind.replaceAll("_", " ")}</small>
            </div>
            <div className="notification-row__actions">
              {!item.read_at && (
                <button className="secondary-button" disabled={markRead.isPending} onClick={() => markRead.mutate(item.notification_id)}>
                  <Check size={15} /> {t("Mark read")}
                </button>
              )}
              {item.action_path && <Link className="primary-button" to={item.action_path}><ExternalLink size={15} /> {t("Open")}</Link>}
            </div>
          </Panel>
        ))}
      </div>
      {!query.data.items.length && <EmptyState icon={<Bell />} title="No notifications" text="Actionable Creative events will appear here." />}
    </>
  );
}
