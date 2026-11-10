import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bell, Check } from "lucide-react";
import { Link } from "react-router-dom";
import { Empty, ErrorNote, PageHead, Skeleton } from "../components/ui";
import { pilotApi } from "../services/pilotApi";

export function NotificationsPage() {
  const client = useQueryClient();
  const query = useQuery({ queryKey: ["notifications"], queryFn: ({ signal }) => pilotApi.notifications(false, signal), refetchInterval: 15000 });
  const markRead = useMutation({ mutationFn: pilotApi.markNotificationRead, onSuccess: () => client.invalidateQueries({ queryKey: ["notifications"] }) });
  if (query.isLoading) return <div className="page"><Skeleton /></div>;
  if (query.error || !query.data) return <div className="page"><ErrorNote error={query.error ?? new Error("No data")} /></div>;
  return (
    <div className="page">
      <PageHead title="Notifications" text="Things that need you, and videos that are done." actions={query.data.unread > 0 ? <span className="pill pill-warn">{`${query.data.unread} unread`}</span> : undefined} />
      {query.data.items.length === 0 && <Empty icon={<Bell size={32} aria-hidden="true" />} title="Nothing new" text="We will tell you here when something needs you." />}
      <div className="stack">
        {query.data.items.map((item) => (
          <div key={item.notification_id} className={`card note-row${item.read_at ? "" : " unread"}`}>
            <div className="copy">
              <strong>{item.title}</strong>
              <p className="muted">{item.detail}</p>
              <span className="muted small">{new Date(item.created_at).toLocaleString()}</span>
            </div>
            {!item.read_at && <button className="btn btn-sm" disabled={markRead.isPending} onClick={() => markRead.mutate(item.notification_id)}><Check size={14} aria-hidden="true" />Mark as read</button>}
            {item.action_path && <Link className="btn btn-primary btn-sm" to={item.action_path}>Open</Link>}
          </div>
        ))}
      </div>
    </div>
  );
}
