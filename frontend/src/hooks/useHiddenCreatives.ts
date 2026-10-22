import { useState } from "react";

const HIDDEN_CREATIVES_KEY = "aic-hidden-creative-ids";

const readHiddenCreatives = () => {
  try {
    const value = JSON.parse(globalThis.localStorage?.getItem(HIDDEN_CREATIVES_KEY) ?? "[]");
    return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
  } catch {
    return [];
  }
};

export function useHiddenCreatives() {
  const [hiddenIds, setHiddenIds] = useState<string[]>(readHiddenCreatives);

  const save = (ids: string[]) => {
    setHiddenIds(ids);
    try {
      globalThis.localStorage?.setItem(HIDDEN_CREATIVES_KEY, JSON.stringify(ids));
    } catch {
      // Keep the current session usable when browser storage is unavailable.
    }
  };

  return {
    hiddenIds,
    hideCreative: (creativeId: string) => save([...new Set([...hiddenIds, creativeId])]),
    hideCreatives: (creativeIds: string[]) => save([...new Set([...hiddenIds, ...creativeIds])]),
    restoreAll: () => save([]),
  };
}
