import { useEffect } from "react";
import { useI18n } from "../hooks/useI18n";
import { Modal } from "./Modal";

export type LightboxImage = { src: string; label?: string; href?: string };

export function Lightbox({ images, index, onIndex, onClose }: { images: LightboxImage[]; index: number; onIndex: (index: number) => void; onClose: () => void }) {
  const { t } = useI18n();
  const image = images[index];
  const step = (by: number) => onIndex((index + by + images.length) % images.length);
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "ArrowRight") onIndex((index + 1) % images.length);
      if (event.key === "ArrowLeft") onIndex((index - 1 + images.length) % images.length);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [index, images.length, onIndex]);
  if (!image) return null;
  return (
    <Modal title={image.label ?? "Image"} onClose={onClose} className="lightbox">
      <div className="lightbox__body">
        {images.length > 1 && <button type="button" className="lightbox__nav" aria-label={t("Previous")} onClick={() => step(-1)}>‹</button>}
        <img src={image.src} alt={image.label ?? ""} referrerPolicy="no-referrer" />
        {images.length > 1 && <button type="button" className="lightbox__nav" aria-label={t("Next")} onClick={() => step(1)}>›</button>}
      </div>
      <footer className="lightbox__foot">
        <span>{`${index + 1} / ${images.length}`}</span>
        {image.href && <a href={image.href} target="_blank" rel="noreferrer">{t("Open the source page")}</a>}
      </footer>
    </Modal>
  );
}
