import { useEffect, useState } from "react";
import { useI18n } from "../hooks/useI18n";

type MediaLabJobProgressProps = {
  steps: string[];
  currentStep: number;
  startedAt: string | null;
  completedAt: string | null;
  status: string;
  revision?: string;
};

export function MediaLabJobProgress({
  steps,
  currentStep,
  startedAt,
  completedAt,
  status,
  revision,
}: MediaLabJobProgressProps) {
  const { t } = useI18n();
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (!startedAt || completedAt) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1_000);
    return () => window.clearInterval(timer);
  }, [completedAt, startedAt]);

  const start = startedAt ? new Date(startedAt).getTime() : null;
  const end = completedAt ? new Date(completedAt).getTime() : now;
  const elapsed = start === null || Number.isNaN(start) ? null : Math.max(0, end - start);

  return (
    <section className="media-lab-progress" aria-live="polite">
      <div className="media-lab-progress-heading">
        <div>
          <strong>{status}</strong>
          {revision && <span>{revision}</span>}
        </div>
        <span>
          {elapsed === null
            ? t("Starting…")
            : t("Elapsed time: {time}").replace("{time}", formatElapsed(elapsed))}
        </span>
      </div>
      <ol className="media-lab-progress-steps">
        {steps.map((step, index) => {
          const state = index < currentStep ? "complete" : index === currentStep ? "current" : "upcoming";
          return (
            <li className={`media-lab-progress-step media-lab-progress-step--${state}`} key={step}>
              <span aria-hidden="true">{state === "complete" ? "✓" : index + 1}</span>
              <small>{step}</small>
            </li>
          );
        })}
      </ol>
    </section>
  );
}

function formatElapsed(milliseconds: number): string {
  const totalSeconds = Math.floor(milliseconds / 1_000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}
