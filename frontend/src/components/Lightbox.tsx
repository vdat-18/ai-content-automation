import { X } from "lucide-react";
import { useEffect } from "react";

export type LightboxImage = { src: string; label?: string; href?: string };

export function Lightbox({ images, index, onIndex, onClose }: { images: LightboxImage[]; index: number; onIndex: (index: number) => void; onClose: () => void }) {
  const image = images[index];
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "ArrowRight") onIndex((index + 1) % images.length);
      if (event.key === "ArrowLeft") onIndex((index - 1 + images.length) % images.length);
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [index, images.length, onIndex, onClose]);
  if (!image) return null;
  return (
    <div className="viewer" role="dialog" aria-modal="true" aria-label={image.label ?? "Image"} onClick={onClose}>
      <button type="button" className="icon-button close" aria-label="Close" onClick={onClose} style={{ color: "#fff" }}><X size={22} /></button>
      {images.length > 1 && <button type="button" className="nav-btn prev" aria-label="Previous" onClick={(event) => { event.stopPropagation(); onIndex((index - 1 + images.length) % images.length); }}>‹</button>}
      <img src={image.src} alt={image.label ?? ""} referrerPolicy="no-referrer" onClick={(event) => event.stopPropagation()} />
      {images.length > 1 && <button type="button" className="nav-btn next" aria-label="Next" onClick={(event) => { event.stopPropagation(); onIndex((index + 1) % images.length); }}>›</button>}
      <div className="row small" onClick={(event) => event.stopPropagation()}>
        {image.label && <span>{image.label}</span>}
        <span>{`${index + 1} / ${images.length}`}</span>
        {image.href && <a href={image.href} target="_blank" rel="noreferrer">Open the source page</a>}
      </div>
    </div>
  );
}
