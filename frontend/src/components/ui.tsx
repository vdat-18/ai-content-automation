import { Loader2 } from "lucide-react";
import type { ReactNode } from "react";
import { friendlyMessage } from "../services/http";

export function PageHead({ title, text, actions }: { title: string; text?: string; actions?: ReactNode }) {
  return (
    <header className="page-head">
      <div>
        <h1>{title}</h1>
        {text && <p>{text}</p>}
      </div>
      {actions && <div className="row">{actions}</div>}
    </header>
  );
}

export function Skeleton() {
  return <div className="skeleton" aria-busy="true" aria-label="Loading" />;
}

export function Empty({ icon, title, text, children }: { icon: ReactNode; title: string; text: string; children?: ReactNode }) {
  return (
    <div className="card empty">
      {icon}
      <h2>{title}</h2>
      <p>{text}</p>
      {children}
    </div>
  );
}

export function Spinner({ size = 16 }: { size?: number }) {
  return <Loader2 size={size} className="spin" aria-hidden="true" />;
}

/** A problem in plain words; the technical detail stays one click away. */
export function ErrorNote({ error }: { error: unknown }) {
  if (!error) return null;
  const detail = error instanceof Error ? error.message : String(error);
  return (
    <div className="notice notice-error" role="alert">
      <div>
        {friendlyMessage(error)}
        <details>
          <summary>Details</summary>
          {detail.slice(0, 400)}
        </details>
      </div>
    </div>
  );
}
