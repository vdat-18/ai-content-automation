import { useState, type KeyboardEvent } from "react";
import { Lightbox, type LightboxImage } from "../components/Lightbox";

/** Click an image to see it large; arrow keys and the side buttons walk through the group it came from. */
export function useLightbox() {
  const [shown, setShown] = useState<{ images: LightboxImage[]; index: number } | null>(null);
  const open = (images: LightboxImage[], index: number) => setShown({ images, index });
  /** Props that make an <img> open the group at its own position. */
  const zoom = (images: LightboxImage[], index: number) => ({
    className: "zoomable",
    role: "button" as const,
    tabIndex: 0,
    onClick: () => open(images, index),
    onKeyDown: (event: KeyboardEvent) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        open(images, index);
      }
    },
  });
  const node = shown ? <Lightbox images={shown.images} index={shown.index} onIndex={(index) => setShown({ ...shown, index })} onClose={() => setShown(null)} /> : null;
  return { zoom, node };
}
