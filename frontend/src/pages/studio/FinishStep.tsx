import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Copy, Download } from "lucide-react";
import { useState } from "react";
import { ErrorNote } from "../../components/ui";
import { ClipsPanel } from "./ClipsPanel";
import { API } from "../../hooks/useStudio";
import { imagesApproved } from "../../lib/studio";
import { getJson, postJson } from "../../services/http";
import type { BriefRecord, Keyframe, PostPackage } from "../../types/studio";

type Usage = { by_operation: { key: string; request_count: number }[] };
const USED = { keyframe: "images", clip: "clips", voiceover: "voice readings" } as Record<string, string>;
const linkKey = (productId: string) => `aic-affiliate-${productId}`;
const readLink = (productId: string) => {
  try {
    return window.localStorage.getItem(linkKey(productId)) ?? "";
  } catch {
    return "";
  }
};

export function FinishStep({ productId, record, frames, hasVideo }: { productId: string; record: BriefRecord; frames: Keyframe[]; hasVideo: boolean }) {
  const client = useQueryClient();
  const [copied, setCopied] = useState("");
  const [link, setLink] = useState(() => readLink(productId));
  const [review, setReview] = useState("");
  const pack = record.brief.post_package;
  const usage = useQuery({ queryKey: ["usage", productId], queryFn: ({ signal }) => getJson<Usage>(`/api/v1/ai-usage/summary?correlation_id=${productId}`, signal) });
  const used = (usage.data?.by_operation ?? []).filter((item) => USED[item.key]);

  const writePack = useMutation({
    mutationFn: () => postJson<PostPackage>(`${API}/${productId}/post-package`),
    onSuccess: () => client.invalidateQueries({ queryKey: ["brief", productId] }),
  });
  const sendReview = useMutation({
    mutationFn: () => postJson<{ status: string }>(`${API}/${productId}/feedback`, { text: review.trim(), asset_type: "brief" }),
    onSuccess: () => setReview(""),
  });

  const copy = (key: string, text: string) => {
    void navigator.clipboard?.writeText(text).then(() => {
      setCopied(key);
      window.setTimeout(() => setCopied(""), 1800);
    });
  };
  const saveLink = (value: string) => {
    setLink(value);
    try {
      window.localStorage.setItem(linkKey(productId), value);
    } catch {
      /* the link is just not remembered */
    }
  };

  // Before the video exists, the scenes page above has the button; here only the clips that need a look show
  if (!hasVideo) return imagesApproved(record, frames) ? <ClipsPanel productId={productId} /> : null;

  const withLink = (text: string) => (link.trim() ? `${text}\n${link.trim()}` : text);
  return (
    <>
      <header className="page-head"><div><h1>Your video is ready</h1><p>Watch it, download it and post it on TikTok.</p></div></header>
      <div className="finish">
        <div className="stack" style={{ alignItems: "center", flex: "0 0 300px" }}>
          <div className="phone"><div className="screen"><video src={`${API}/${productId}/video`} poster={`${API}/${productId}/cover`} controls playsInline /></div></div>
        </div>

        <div className="right">
          <div className="card pad stack">
            <div className="row">
              <span className="pill">{`${record.brief.shots?.length ?? 0} scenes`}</span>
              <span className="pill">With voice-over</span>
            </div>
            {used.length > 0 && <p className="muted small">{`Made with ${used.map((item) => `${item.request_count} ${USED[item.key]}`).join(", ")}`}</p>}
            <div className="row">
              <a className="btn btn-primary btn-lg" href={`${API}/${productId}/video?download=true`}><Download size={18} aria-hidden="true" />Download video</a>
              <a className="btn btn-lg" href={`${API}/${productId}/cover?download=true`}>Download cover picture</a>
            </div>
            <div className="stack">
              <label className="field">
                <span className="small">What would make the next video better?</span>
                <textarea rows={2} value={review} onChange={(event) => setReview(event.target.value)} placeholder="For example: the opening was slow, start with a question." />
              </label>
              <div className="row">
                <button className="btn btn-sm" disabled={!review.trim() || sendReview.isPending} onClick={() => sendReview.mutate()}>Send to AI memory</button>
                {sendReview.isSuccess && <span className="muted small">{sendReview.data?.status === "approved" ? "Saved as a rule. The AI uses it from the next video." : "Sent. It waits in AI memory until the AI can turn it into a rule."}</span>}
              </div>
              <ErrorNote error={sendReview.error} />
            </div>
          </div>

          <div className="card pad stack">
            <h2>Caption and hashtags</h2>
            {pack ? (
              <>
                {pack.captions.map((caption, index) => (
                  <div className="caption-box" key={index}>
                    <p>{caption}</p>
                    <button className="btn btn-sm" onClick={() => copy(`c${index}`, withLink(caption))}><Copy size={14} aria-hidden="true" />{copied === `c${index}` ? "Copied" : link.trim() ? "Copy with link" : "Copy"}</button>
                  </div>
                ))}
                <div className="caption-box">
                  <p>{pack.hashtags.join(" ")}</p>
                  <button className="btn btn-sm" onClick={() => copy("tags", pack.hashtags.join(" "))}><Copy size={14} aria-hidden="true" />{copied === "tags" ? "Copied" : "Copy"}</button>
                </div>
                <label className="field">Your affiliate link<input type="text" value={link} onChange={(event) => saveLink(event.target.value)} placeholder="Paste your link here" /></label>
              </>
            ) : (
              <>
                <p className="muted">The AI writes a caption and hashtags that match your video.</p>
                <div><button className="btn btn-primary" disabled={writePack.isPending} onClick={() => writePack.mutate()}>{writePack.isPending ? "Writing…" : "Write caption and hashtags"}</button></div>
              </>
            )}
            <ErrorNote error={writePack.error} />
          </div>
        </div>
      </div>
    </>
  );
}
