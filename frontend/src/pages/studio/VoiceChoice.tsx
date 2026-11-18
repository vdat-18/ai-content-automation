import { useQuery } from "@tanstack/react-query";
import { ErrorNote } from "../../components/ui";
import { API } from "../../hooks/useStudio";
import { getJson } from "../../services/http";
import type { Voice } from "../../types/studio";

export function VoiceChoice({ voice, onChoose }: { voice: string; onChoose: (id: string) => void }) {
  const voices = useQuery({ queryKey: ["voices"], queryFn: ({ signal }) => getJson<Voice[]>(`${API}/voices`, signal), staleTime: Infinity });
  const options = (voices.data ?? []).filter((option) => option.id !== "auto");
  return (
    <div className="stack" style={{ gap: 10 }}>
      <strong>Choose the voice</strong>
      <span className="muted small">Listen, then pick one. Every video uses it until you change it.</span>
      {options.map((option) => (
        <div key={option.id} className="stack" style={{ gap: 4 }}>
          <label className="check"><input type="radio" name="voice" checked={voice === option.id} onChange={() => onChoose(option.id)} />{option.label}</label>
          <audio controls preload="none" style={{ width: "100%", height: 32 }} src={`${API}/voices/${encodeURIComponent(option.id)}/sample`} />
        </div>
      ))}
      <ErrorNote error={voices.error} />
    </div>
  );
}
