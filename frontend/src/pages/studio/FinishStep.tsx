import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Copy, Download, Info } from "lucide-react";
import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { ErrorNote, Spinner } from "../../components/ui";
import { API, useStartPipeline, useVideoCheck, VOICE_KEY } from "../../hooks/useStudio";
import { imagesApproved } from "../../lib/studio";
import { getJson, postJson } from "../../services/http";
import type { BriefRecord, Keyframe, PipelineRun, PostPackage, Voice } from "../../types/studio";

type Hook = { id: string; angle: string; text: string; built: boolean };
const linkKey = (productId: string) => `aic-affiliate-${productId}`;
const readLink = (productId: string) => {
  try {
    return window.localStorage.getItem(linkKey(productId)) ?? "";
  } catch {
    return "";
  }
};

export function FinishStep({ productId, record, frames, hasVideo, run }: { productId: string; record: BriefRecord; frames: Keyframe[]; hasVideo: boolean; run: PipelineRun | undefined }) {
  const [, setParams] = useSearchParams();
  const client = useQueryClient();
  const start = useStartPipeline(productId);
  const [version, setVersion] = useState(0);
  const [copied, setCopied] = useState("");
  const [link, setLink] = useState(() => readLink(productId));
  const [captions, setCaptions] = useState(false);
  const [stickers, setStickers] = useState(false);
  const [review, setReview] = useState("");
  const [voice, setVoice] = useState(() => window.localStorage.getItem(VOICE_KEY) ?? "");
  const pack = record.brief.post_package;
  const check = useVideoCheck(productId, version).data;
  const voices = useQuery({ queryKey: ["voices"], queryFn: ({ signal }) => getJson<Voice[]>(`${API}/voices`, signal), staleTime: Infinity });
  const selectedVoice = voice || voices.data?.find((option) => option.id !== "auto")?.id || "";

  const writePack = useMutation({
    mutationFn: () => postJson<PostPackage>(`${API}/${productId}/post-package`),
    onSuccess: () => client.invalidateQueries({ queryKey: ["brief", productId] }),
  });
  const sendReview = useMutation({
    mutationFn: () => postJson(`${API}/${productId}/feedback`, { text: review.trim(), asset_type: "brief" }),
    onSuccess: () => setReview(""),
  });
  const hooks = useQuery({ queryKey: ["hooks", productId], queryFn: ({ signal }) => getJson<Hook[]>(`${API}/${productId}/hooks`, signal) });
  const writeHooks = useMutation({
    mutationFn: () => postJson(`${API}/${productId}/hooks`),
    onSuccess: () => client.invalidateQueries({ queryKey: ["hooks", productId] }),
  });
  const buildHook = useMutation({
    mutationFn: (hook: Hook) => postJson(`${API}/${productId}/hooks/${hook.id}/video`, { voice: selectedVoice || null, captions, stickers }),
    onSuccess: () => client.invalidateQueries({ queryKey: ["hooks", productId] }),
  });
  const remake = useMutation({
    mutationFn: async () => {
      await postJson(`${API}/${productId}/voiceover`, { voice: selectedVoice || null });
      await postJson(`${API}/${productId}/video`, { captions, stickers });
    },
    onSuccess: () => {
      setVersion((v) => v + 1);
      void client.invalidateQueries({ queryKey: ["video-info", productId] });
    },
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

  if (!hasVideo) {
    const ready = imagesApproved(record, frames);
    return (
      <div className="card pad stack" style={{ maxWidth: 640 }}>
        <h1 style={{ fontSize: 24 }}>{ready ? "Ready to make your video" : "Approve the images first"}</h1>
        <p className="muted">{ready ? "The AI films every scene, records the voice-over and puts it all together. It takes about 10 minutes and you can leave the page." : "Make sure every scene is approved, then come back here."}</p>
        {run && (run.status === "paused" || run.status === "failed") && <div className="notice notice-warn" role="alert"><div>The last run stopped. {run.message}</div></div>}
        {ready ? (
          <button className="btn btn-primary btn-lg" style={{ alignSelf: "flex-start" }} disabled={start.isPending} onClick={() => start.mutate({ until: "video" })}>{start.isPending ? "Starting…" : "Make the video"}</button>
        ) : (
          <button className="btn btn-primary btn-lg" style={{ alignSelf: "flex-start" }} onClick={() => setParams({ step: "images" })}>Go to the images</button>
        )}
        <ErrorNote error={start.error} />
      </div>
    );
  }

  const withLink = (text: string) => (link.trim() ? `${text}\n${link.trim()}` : text);
  return (
    <>
      <header className="page-head"><div><h1>Your video is ready</h1><p>Watch it, download it and post it on TikTok. Not happy with a scene? Go back and fix just that scene.</p></div></header>
      <div className="finish">
        <div className="stack" style={{ alignItems: "center", flex: "0 0 300px" }}>
          <div className="phone"><div className="screen"><video key={version} src={`${API}/${productId}/video?v=${version}`} poster={`${API}/${productId}/cover`} controls playsInline /></div></div>
        </div>

        <div className="right">
          <div className="card pad stack">
            <div className="row">
              <span className="pill">{`${record.brief.shots?.length ?? 0} scenes`}</span>
              <span className="pill">With voice-over</span>
            </div>
            <div className="row">
              <a className="btn btn-primary btn-lg" href={`${API}/${productId}/video?download=true`}><Download size={18} aria-hidden="true" />Download video</a>
              <a className="btn btn-lg" href={`${API}/${productId}/cover?download=true`}>Download cover picture</a>
            </div>
            {check && (
              <div className={check.issues.length ? "notice notice-warn" : "notice"} role="status">
                <div>
                  <strong>{`Automatic check: ${check.score}/100`}</strong>
                  {check.issues.length ? <ul>{check.issues.map((issue) => <li key={issue.message}>{issue.message}</li>)}</ul> : " No problems found."}
                </div>
              </div>
            )}
            <div className="stack">
              <label className="field">
                <span className="small">What would make the next video better?</span>
                <textarea rows={2} value={review} onChange={(event) => setReview(event.target.value)} placeholder="For example: the opening was slow, start with a question." />
              </label>
              <div className="row">
                <button className="btn btn-sm" disabled={!review.trim() || sendReview.isPending} onClick={() => sendReview.mutate()}>Send to AI memory</button>
                {sendReview.isSuccess && <span className="muted small">Sent. Approve it in AI memory to use it in the next videos.</span>}
              </div>
              <ErrorNote error={sendReview.error} />
            </div>
            <div className="stack">
              <div className="row">
                <strong className="small">Try other opening lines</strong>
                <button className="btn btn-sm" disabled={writeHooks.isPending} onClick={() => writeHooks.mutate()}>{writeHooks.isPending ? <><Spinner size={14} />Writing…</> : hooks.data?.length ? "Write new ones" : "Write 3 opening lines"}</button>
              </div>
              <p className="muted small">Only the first line changes. The scenes are reused, so no new scene is paid for. It uses the voice and options chosen below.</p>
              {hooks.data?.map((hook) => (
                <div className="caption-box" key={hook.id}>
                  <p><span className="muted small">{hook.angle}</span><br />{hook.text}</p>
                  <div className="row">
                    <button className="btn btn-sm" disabled={buildHook.isPending} onClick={() => buildHook.mutate(hook)}>{buildHook.isPending && buildHook.variables?.id === hook.id ? <><Spinner size={14} />Making…</> : hook.built ? "Make again" : "Make this video"}</button>
                    {hook.built && <a className="btn btn-sm" href={`${API}/${productId}/hooks/${hook.id}/video?download=true`}><Download size={14} aria-hidden="true" />Download</a>}
                    {hook.built && <a className="btn btn-sm" href={`${API}/${productId}/hooks/${hook.id}/video`} target="_blank" rel="noreferrer">Watch</a>}
                  </div>
                </div>
              ))}
              <ErrorNote error={writeHooks.error ?? buildHook.error} />
            </div>
            <details>
              <summary className="muted small" style={{ cursor: "pointer" }}>More options: change the voice or show on-screen text</summary>
              <div className="stack" style={{ marginTop: 12 }}>
                <label className="field">Voice
                  <select value={selectedVoice} onChange={(event) => { setVoice(event.target.value); window.localStorage.setItem(VOICE_KEY, event.target.value); }}>
                    {(voices.data ?? []).map((option) => <option key={option.id} value={option.id}>{option.label}</option>)}
                  </select>
                </label>
                {selectedVoice && <audio key={selectedVoice} controls preload="none" src={`${API}/voices/${encodeURIComponent(selectedVoice)}/sample`} />}
                <label className="check"><input type="checkbox" checked={captions} onChange={(event) => setCaptions(event.target.checked)} />Show the on-screen text in the video (it can cover the product).</label>
                <label className="check"><input type="checkbox" checked={stickers} onChange={(event) => setStickers(event.target.checked)} />Show price, sales and rating stickers from the product data, in the shot that mentions them.</label>
                <div><button className="btn" disabled={remake.isPending} onClick={() => remake.mutate()}>{remake.isPending ? <><Spinner size={14} />Remaking…</> : "Remake the video with these choices"}</button></div>
                <ErrorNote error={remake.error} />
              </div>
            </details>
          </div>

          <div className="notice notice-warn"><Info size={20} aria-hidden="true" /><span><strong>Before you post:</strong> turn on TikTok's "AI-generated content" label and replace the product link with your own affiliate link.</span></div>

          <div className="card pad stack">
            <h2>Caption and hashtags</h2>
            {pack ? (
              <>
                {!!pack.warnings?.length && <div className="notice notice-warn" role="alert"><div>TikTok may flag these words. Rewrite them before posting:<ul>{pack.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul></div></div>}
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
                <div><button className="link" disabled={writePack.isPending} onClick={() => writePack.mutate()}>{writePack.isPending ? "Writing…" : "Write a different caption"}</button></div>
              </>
            ) : (
              <>
                <p className="muted">The AI writes a caption and hashtags that match your video.</p>
                <div><button className="btn btn-primary" disabled={writePack.isPending} onClick={() => writePack.mutate()}>{writePack.isPending ? "Writing…" : "Write caption and hashtags"}</button></div>
              </>
            )}
            <ErrorNote error={writePack.error} />
          </div>

          <button className="link" style={{ alignSelf: "flex-start" }} onClick={() => setParams({ step: "images" })}>Not happy with a scene? Go back and fix it</button>
        </div>
      </div>
    </>
  );
}
