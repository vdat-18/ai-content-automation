import { useEffect, useState } from "react";
import {
  AssistantRuntimeProvider,
  AuiIf,
  ComposerPrimitive,
  MessagePrimitive,
  ThreadPrimitive,
  useLocalRuntime,
  type ChatModelAdapter,
} from "@assistant-ui/react";
import { pilotApi } from "../services/pilotApi";
import { useI18n } from "../hooks/useI18n";

type LabModel = { id: string; label: string; model: string };

export function ModelLabPage() {
  const { t } = useI18n();
  const [models, setModels] = useState<LabModel[]>([]);
  const [selected, setSelected] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const controller = new AbortController();
    pilotApi.modelLabModels(controller.signal)
      .then(({ items }) => {
        setModels(items);
        setSelected(items[0]?.id ?? "");
      })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "Could not load models");
      })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, []);

  return (
    <>
      <header className="page-header">
        <div>
          <p className="eyebrow">AD HOC MODEL TESTING</p>
          <h1>{t("Model Lab")}</h1>
          <p>{t("Try a configured chat model without starting or changing a Marketing workflow.")}</p>
        </div>
      </header>
      <section className="panel model-lab-panel">
        <label className="model-lab-selector">
          <span>Model</span>
          <select value={selected} onChange={(event) => setSelected(event.target.value)} disabled={!models.length}>
            {models.length === 0 && <option value="">{t("No model configured")}</option>}
            {models.map((model) => <option key={model.id} value={model.id}>{model.label} · {model.model}</option>)}
          </select>
        </label>
        {loading && <p>{t("Loading models…")}</p>}
        {error && <p role="alert" className="model-lab-error">{error}</p>}
        {!loading && !error && !selected && <p>{t("Set AIC_AI_MODEL_LAB_CONFIG on the API to enable a model.")}</p>}
        {selected && <ChatPanel key={selected} modelId={selected} />}
      </section>
    </>
  );
}

function ChatPanel({ modelId }: { modelId: string }) {
  const { t } = useI18n();
  const adapter: ChatModelAdapter = {
    async run({ messages, abortSignal }) {
      const response = await pilotApi.modelLabChat(
        modelId,
        messages.map((message) => ({
            role: message.role,
            content: message.content.filter((part) => part.type === "text").map((part) => part.text).join("\n"),
        })),
        abortSignal,
      );
      return { content: [{ type: "text", text: response.text }] };
    },
  };
  const runtime = useLocalRuntime(adapter);
  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <ThreadPrimitive.Root className="model-lab-thread">
        <ThreadPrimitive.Viewport className="model-lab-messages">
          <AuiIf condition={(state) => state.thread.isEmpty}>
            <p className="model-lab-empty">{t("Ask a question to test this model. This conversation stays in this browser tab.")}</p>
          </AuiIf>
          <ThreadPrimitive.Messages>
            {({ message }) => <MessagePrimitive.Root className={`model-lab-message model-lab-message--${message.role}`}>
              <strong>{message.role === "user" ? "You" : "Model"}</strong>
              <MessagePrimitive.Parts />
            </MessagePrimitive.Root>}
          </ThreadPrimitive.Messages>
          <ThreadPrimitive.ViewportFooter>
            <ComposerPrimitive.Root className="model-lab-composer">
              <ComposerPrimitive.Input rows={1} aria-label={t("Message to model")} placeholder={t("Write a message to test the model…")} onInput={(event) => { event.currentTarget.style.height = "auto"; event.currentTarget.style.height = `${Math.min(event.currentTarget.scrollHeight, 240)}px`; }} />
              <ComposerPrimitive.Send className="primary-button">Send</ComposerPrimitive.Send>
              <AuiIf condition={(state) => state.thread.isRunning}>
                <ComposerPrimitive.Cancel type="button">Stop</ComposerPrimitive.Cancel>
              </AuiIf>
            </ComposerPrimitive.Root>
          </ThreadPrimitive.ViewportFooter>
        </ThreadPrimitive.Viewport>
      </ThreadPrimitive.Root>
    </AssistantRuntimeProvider>
  );
}
