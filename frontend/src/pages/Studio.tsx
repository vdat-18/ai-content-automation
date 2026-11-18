import { useQueryClient } from "@tanstack/react-query";
import { Check, Package } from "lucide-react";
import { useEffect, useRef } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { Empty, ErrorNote, Skeleton } from "../components/ui";
import { useBrief, useKeyframes, usePipeline, useProducts, useSelections, useVideoInfo } from "../hooks/useStudio";
import { doneSteps, friendlyStep, productOf, STEPS, suggestedStep, type StepId } from "../lib/studio";
import { FinishStep } from "./studio/FinishStep";
import { IdeaStep } from "./studio/IdeaStep";
import { ImagesStep } from "./studio/ImagesStep";
import { Working } from "./studio/Working";

export function StudioPage() {
  const { productId = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const client = useQueryClient();
  const products = useProducts();
  const selections = useSelections();
  const pipeline = usePipeline(productId);
  const brief = useBrief(productId, pipeline.data?.status === "running");
  const running = pipeline.data?.status === "running";
  const keyframes = useKeyframes(productId, !!brief.data, running);
  const video = useVideoInfo(productId);
  // When a run ends, pull in everything it made.
  const wasRunning = useRef(false);
  useEffect(() => {
    if (running) {
      wasRunning.current = true;
    } else if (wasRunning.current) {
      wasRunning.current = false;
      for (const key of ["brief", "briefs", "keyframes", "clips", "video-info", "outputs", "persona"]) void client.invalidateQueries({ queryKey: [key] });
    }
  }, [running, client]);

  if (products.isLoading || brief.isLoading) return <div className="page"><Skeleton /></div>;
  const product = products.data?.find((item) => item.product_id === productOf(productId));
  if (!product) {
    return <div className="page"><Empty icon={<Package size={32} aria-hidden="true" />} title="Product not found" text="Pick a product from the list to make a video."><Link className="btn btn-primary" to="/products">Go to products</Link></Empty></div>;
  }
  if (brief.error) return <div className="page"><ErrorNote error={brief.error} /></div>;

  const record = brief.data ?? null;
  const frames = keyframes.data ?? [];
  const hasVideo = !!video.data?.exists;
  const done = doneSteps(record, frames, hasVideo);
  const asked = params.get("step") as StepId | null;
  const step: StepId = asked && STEPS.some((item) => item.id === asked) ? asked : suggestedStep(record);
  const reachable = (id: StepId) => id === "idea" || !!record;
  const productType = selections.data?.[productOf(productId)] ?? null;
  // Once the first image exists, making the other scenes and the video happens on the one scenes page
  const onePage = running && !!record && frames.length > 0;
  const makingScenes = onePage && friendlyStep(pipeline.data!.step) === "Creating the other scenes";
  const makingVideo = onePage && !makingScenes;

  return (
    <div className="page">
      <ol className="stepper" aria-label="Steps">
        {STEPS.map((item, index) => {
          const state = step === item.id ? "current" : done[item.id] ? "done" : "";
          return (
            <li key={item.id} className={state} aria-current={step === item.id ? "step" : undefined}>
              <button type="button" disabled={!reachable(item.id)} onClick={() => setParams(item.id === suggestedStep(record) ? {} : { step: item.id })}>
                <span className="n">{done[item.id] && step !== item.id ? <Check size={14} aria-hidden="true" /> : index + 1}</span>
                {item.label}
              </button>
            </li>
          );
        })}
      </ol>

      {onePage ? (
        <ImagesStep productId={productId} record={record!} frames={frames} run={pipeline.data} hasVideo={hasVideo} making={makingScenes} makingVideo={makingVideo} />
      ) : running ? (
        <Working productId={productId} run={pipeline.data!} record={record} frames={frames} />
      ) : step === "idea" ? (
        <IdeaStep productId={productId} product={product} productType={productType} record={record} run={pipeline.data} />
      ) : record ? (
        <>
          <ImagesStep productId={productId} record={record} frames={frames} run={pipeline.data} hasVideo={hasVideo} />
          {frames.length > 0 && <FinishStep productId={productId} record={record} hasVideo={hasVideo} />}
        </>
      ) : null}
    </div>
  );
}
