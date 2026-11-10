import { useSearchParams } from "react-router-dom";
import { PageHead } from "../components/ui";
import { RulesTab } from "./memory/RulesTab";
import { ScenesTab } from "./memory/ScenesTab";

type Tab = "rules" | "scenes";

export function MemoryPage() {
  const [params, setParams] = useSearchParams();
  const tab: Tab = params.get("tab") === "scenes" ? "scenes" : "rules";
  return (
    <div className="page">
      <PageHead title="AI memory" text="What the AI knows and follows when it makes your videos. Change it here and every next video follows." />
      <div className="tabs" role="tablist" aria-label="AI memory">
        <button role="tab" aria-selected={tab === "rules"} onClick={() => setParams({})}>Rules</button>
        <button role="tab" aria-selected={tab === "scenes"} onClick={() => setParams({ tab: "scenes" })}>Reference scenes</button>
      </div>
      {tab === "rules" ? <RulesTab /> : <ScenesTab />}
    </div>
  );
}
