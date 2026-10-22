import { useI18n } from "../hooks/useI18n";
import type { SplitHandleProps } from "../hooks/useSplitResize";

export function SplitHandle({ label, ...handleProps }: SplitHandleProps & { label: string }) {
  const { t } = useI18n();
  return (
    <div
      className="split-handle"
      role="separator"
      aria-orientation="vertical"
      tabIndex={0}
      aria-label={t(label)}
      title={t("Drag to resize · double-click to reset")}
      {...handleProps}
    />
  );
}
