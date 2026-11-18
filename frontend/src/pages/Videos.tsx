import { Film, Plus } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { Empty, PageHead, Skeleton } from "../components/ui";
import { useBriefs, useOutputs, useProducts } from "../hooks/useStudio";
import { productOf } from "../lib/studio";
import { VideoCard } from "./Home";

type Tab = "all" | "finished" | "working";

export function VideosPage() {
  const [tab, setTab] = useState<Tab>("all");
  const outputs = useOutputs();
  const briefs = useBriefs();
  const products = useProducts();
  if (outputs.isLoading || briefs.isLoading) return <div className="page"><Skeleton /></div>;
  const finished = outputs.data ?? [];
  const finishedIds = new Set(finished.map((item) => item.product_id));
  const imageById = new Map((products.data ?? []).map((product) => [product.product_id, product.images[0]]));
  const working = (briefs.data ?? []).filter((record) => !finishedIds.has(record.product_id));
  const shown = { finished: tab !== "working" ? finished : [], working: tab !== "finished" ? working : [] };

  return (
    <div className="page">
      <PageHead
        title="My videos"
        text="Every video you made or are still making."
        actions={<Link className="btn btn-primary" to="/products"><Plus size={18} aria-hidden="true" />Make a new video</Link>}
      />
      <div className="tabs" role="tablist" aria-label="Filter videos">
        {([["all", "All"], ["finished", "Finished"], ["working", "In progress"]] as [Tab, string][]).map(([id, label]) => (
          <button key={id} role="tab" aria-selected={tab === id} onClick={() => setTab(id)}>{label}</button>
        ))}
      </div>
      {shown.finished.length + shown.working.length === 0 ? (
        <Empty icon={<Film size={32} aria-hidden="true" />} title="Nothing here yet" text="Pick a product to make your first video." />
      ) : (
        <div className="video-grid">
          {shown.working.map((record) => (
            <Link key={record.product_id} to={`/studio/${record.product_id}`} className="video-card">
              <div className="cover">
                {imageById.get(productOf(record.product_id)) && <img src={imageById.get(productOf(record.product_id))} alt="" loading="lazy" referrerPolicy="no-referrer" />}
                <span className="tag pill pill-warn">In progress</span>
              </div>
              <div><strong>{record.brief.title}</strong><span className="muted small">{`${record.brief.shots?.length ?? 0} scenes`}</span></div>
            </Link>
          ))}
          {shown.finished.map((item) => <VideoCard key={item.product_id} item={item} />)}
        </div>
      )}
    </div>
  );
}
