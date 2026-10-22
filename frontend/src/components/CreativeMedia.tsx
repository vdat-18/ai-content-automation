import { useEffect, useRef, useState } from "react";
import { Film, Play } from "lucide-react";
import "../marketing/creative.css";
import { useI18n } from "../hooks/useI18n";

interface CreativeMediaProps {
  type: "static" | "video";
  src: string;
  alt: string;
  compact?: boolean;
  seekTo?: number;
}

export function CreativeMedia({ type, src, alt, compact = false, seekTo }: CreativeMediaProps) {
  const { t } = useI18n();
  const video = useRef<HTMLVideoElement>(null);
  const recording = useRef<MediaRecorder | null>(null);
  const stop = useRef<(() => void) | null>(null);
  const [preview, setPreview] = useState<{ source: string; url: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const synthetic = src.startsWith("synthetic-video:");
  const activeUrl = preview?.source === src ? preview.url : undefined;
  useEffect(() => () => { stop.current?.(); }, []);
  useEffect(() => () => { if (preview) URL.revokeObjectURL(preview.url); }, [preview]);
  useEffect(() => {
    if (seekTo !== undefined && video.current) video.current.currentTime = Math.min(5.9, Math.max(0, seekTo));
  }, [seekTo]);

  async function prepare() {
    if (busy) return;
    setError("");
    if (!window.MediaRecorder || !HTMLCanvasElement.prototype.captureStream) { setError("Motion preview is not supported in this browser. The script and storyboard remain available below."); return; }
    setBusy(true);
    const canvas = document.createElement("canvas");
    canvas.width = 360; canvas.height = 640;
    const context = canvas.getContext("2d");
    if (!context) { setBusy(false); setError("Canvas unavailable. Inspect the storyboard below."); return; }
    const stream = canvas.captureStream(15);
    let cancelled = false;
    let frame = 0;
    let timeout = 0;
    const chunks: BlobPart[] = [];
    const mimeType = ["video/webm;codecs=vp8", "video/webm", "video/mp4"].find((mime) => MediaRecorder.isTypeSupported(mime));
    let recorder: MediaRecorder;
    try { recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined); }
    catch { stream.getTracks().forEach((track) => track.stop()); setBusy(false); setError(t("The browser could not encode this preview. Inspect the storyboard below.")); return; }
    recording.current = recorder;
    const cleanup = () => { cancelAnimationFrame(frame); window.clearTimeout(timeout); stream.getTracks().forEach((track) => track.stop()); recording.current = null; };
    stop.current = () => { cancelled = true; if (recorder.state !== "inactive") recorder.stop(); cleanup(); };
    recorder.ondataavailable = (event) => { if (event.data.size) chunks.push(event.data); };
    recorder.onerror = () => { cancelled = true; cleanup(); setError(t("Preview encoding failed. You can still inspect the saved storyboard.")); setBusy(false); };
    recorder.onstop = () => {
      cleanup();
      if (cancelled) return;
      const blob = new Blob(chunks, { type: recorder.mimeType });
      if (!blob.size) { setError(t("No preview frames were captured. Please try again in an active tab.")); setBusy(false); return; }
      setPreview({ source: src, url: URL.createObjectURL(blob) });
      setBusy(false);
    };
    const started = performance.now();
    const oldVersion = src.includes("creative-motion-demo:v1");
    const draw = () => {
      const second = Math.min(6, (performance.now() - started) / 1000);
      const ending = second >= (oldVersion ? 2 : 4);
      context.fillStyle = "#171833"; context.fillRect(0, 0, 360, 640);
      const gradient = context.createLinearGradient(0, 0, 360, 640); gradient.addColorStop(0, "#632b6c"); gradient.addColorStop(1, "#26a9e0");
      context.fillStyle = gradient; context.beginPath(); context.ellipse(180 + Math.sin(second) * 20, 310, 94 + second * 2, 125, 0, 0, Math.PI * 2); context.fill();
      context.fillStyle = "#ffffff"; context.textAlign = "center"; context.font = "14px sans-serif"; context.fillText("SYNTHETIC MOTION PREVIEW", 180, 55);
      context.font = "bold 23px sans-serif"; context.fillText(ending ? "Make space." : second < 2 ? "A new perspective." : "Notice the shape.", 180, 480);
      context.font = "14px sans-serif"; context.fillText("Geometric fixture · no AI generation", 180, 545); context.fillText("Silent · " + second.toFixed(1) + " / 6.0s", 180, 575);
      context.fillStyle = "#ffffff"; context.fillRect(24, 605, 312 * second / 6, 3);
      frame = requestAnimationFrame(draw);
    };
    draw();
    recorder.start();
    timeout = window.setTimeout(() => { if (recorder.state !== "inactive") recorder.stop(); }, 6000);
  }

  if (type === "static") return <img src={src} alt={alt} />;
  if (!synthetic) return <div className="creative-media legacy-video"><img src={src} alt={alt + " · " + t("saved poster only")} /><p><Film size={16} />{t("Historical poster only. No playable video was saved for this version.")}</p></div>;
  if (compact) return <div className="creative-media motion-poster" role="img" aria-label={alt + " · " + t("synthetic video fixture")}><Film size={30} /><strong>{t("Motion study")}</strong><span>{t("6s · silent synthetic preview")}</span></div>;
  return <div className="creative-media motion-player">
    {activeUrl ? <video key={activeUrl} ref={video} src={activeUrl} controls muted playsInline aria-label={alt} onLoadedMetadata={() => { if (video.current && seekTo !== undefined) video.current.currentTime = Math.min(5.9, seekTo); }} /> : <div className="motion-poster"><Film size={38} /><strong>{t("Synthetic motion preview")}</strong><p>{t("6-second geometric animation. No model, product image, voice or external service is used.")}</p><button className="secondary-button" disabled={busy} onClick={prepare}><Play size={16} />{t(busy ? "Preparing 6-second clip…" : "Prepare motion preview")}</button></div>}
    <p className="motion-caption">{t("Synthetic preview · browser-only · not AI-generated creative. Playback controls do not change workflow state.")}</p>
    {error && <p role="alert">{error}</p>}
  </div>;
}
