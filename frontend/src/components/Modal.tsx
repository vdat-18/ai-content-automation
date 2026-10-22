import { useEffect, useId, useRef, type ReactNode } from "react";
import { useI18n } from "../hooks/useI18n";

export function Modal({ title, children, onClose, className = "" }: { title: string; children: ReactNode; onClose: () => void; className?: string }) {
  const { t } = useI18n();
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  useEffect(() => {
    const dialog = ref.current!;
    const previous = document.activeElement as HTMLElement | null;
    dialog.showModal();
    dialog.querySelector<HTMLElement>("[data-modal-autofocus]")?.focus();
    return () => { dialog.close(); previous?.focus(); };
  }, []);
  return <dialog ref={ref} className={`app-dialog ${className}`.trim()} aria-labelledby={titleId} onKeyDown={(event) => {
    if (event.key !== "Tab") return;
    const focusable = Array.from(event.currentTarget.querySelectorAll<HTMLElement>('a[href], button:not(:disabled), input:not(:disabled), textarea:not(:disabled), select:not(:disabled), [tabindex="0"]')).filter((item) => item.getClientRects().length);
    const first = focusable[0];
    const last = focusable.at(-1);
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
  }} onCancel={(event) => { event.preventDefault(); onClose(); }} onClick={(event) => { if (event.target === ref.current) { const rect = ref.current.getBoundingClientRect(); if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) onClose(); } }}>
    <header><h2 id={titleId}>{t(title)}</h2><button className="icon-button" aria-label={t("Close dialog")} onClick={onClose}>×</button></header>
    {children}
  </dialog>;
}
