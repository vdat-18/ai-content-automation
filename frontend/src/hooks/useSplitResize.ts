import { useEffect, useRef, useState, type CSSProperties, type PointerEvent as ReactPointerEvent, type RefObject } from "react";

export type SplitHandleProps = {
  onPointerDown: (event: ReactPointerEvent<HTMLDivElement>) => void;
  onPointerMove: (event: ReactPointerEvent<HTMLDivElement>) => void;
  onPointerUp: (event: ReactPointerEvent<HTMLDivElement>) => void;
  onPointerCancel: (event: ReactPointerEvent<HTMLDivElement>) => void;
  onDoubleClick: () => void;
  onKeyDown: (event: React.KeyboardEvent<HTMLDivElement>) => void;
};

const readStoredWidth = (storageKey: string, min: number, max: number) => {
  const stored = Number(window.localStorage.getItem(storageKey));
  return Number.isFinite(stored) && stored >= min && stored <= max ? stored : null;
};

/**
 * Drag-to-resize controller for the secondary (right) column of a two-column
 * detail grid. The owning layout applies `style` and toggles the
 * `split-active` class; the collapsed-layout media queries in styles.css
 * override both so mobile/tablet stacks stay intact.
 */
export function useSplitResize(storageKey: string, min: number, max: number, panelRef: RefObject<HTMLElement | null>) {
  const [width, setWidth] = useState<number | null>(() => readStoredWidth(storageKey, min, max));
  const drag = useRef<{ pointerId: number; startX: number; startWidth: number } | null>(null);

  useEffect(() => {
    if (width !== null) window.localStorage.setItem(storageKey, String(width));
  }, [width, storageKey]);
  useEffect(() => () => { document.body.classList.remove("column-resizing"); }, []);

  const endDrag = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (drag.current?.pointerId !== event.pointerId) return;
    drag.current = null;
    delete event.currentTarget.dataset.active;
    document.body.classList.remove("column-resizing");
  };

  const handleProps: SplitHandleProps = {
    onPointerDown: (event) => {
      if (event.pointerType === "mouse" && event.button !== 0) return;
      event.preventDefault();
      event.currentTarget.setPointerCapture(event.pointerId);
      drag.current = {
        pointerId: event.pointerId,
        startX: event.clientX,
        startWidth: panelRef.current?.getBoundingClientRect().width ?? min,
      };
      event.currentTarget.dataset.active = "true";
      document.body.classList.add("column-resizing");
    },
    onPointerMove: (event) => {
      const current = drag.current;
      if (!current || current.pointerId !== event.pointerId) return;
      // Dragging left widens the right-hand column.
      setWidth(Math.min(max, Math.max(min, current.startWidth + (current.startX - event.clientX))));
    },
    onPointerUp: endDrag,
    onPointerCancel: endDrag,
    onDoubleClick: () => {
      drag.current = null;
      document.body.classList.remove("column-resizing");
      window.localStorage.removeItem(storageKey);
      setWidth(null);
    },
    onKeyDown: (event) => {
      if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
      event.preventDefault();
      setWidth((current) => Math.min(max, Math.max(min, (current ?? min) + (event.key === "ArrowLeft" ? 16 : -16))));
    },
  };

  return {
    active: width !== null,
    style: width !== null ? ({ "--split-w": `${width}px` } as CSSProperties) : undefined,
    handleProps,
  };
}
