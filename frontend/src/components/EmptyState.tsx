import type { ReactNode } from "react";

import { Icon, type IconName } from "./Icon";

export function EmptyState({ icon, title, children }: { icon: IconName; title: string; children?: ReactNode }) {
  return (
    <div className="empty">
      <Icon name={icon} size={32} />
      <h3>{title}</h3>
      {children ? <p>{children}</p> : null}
    </div>
  );
}

export function Spinner({ label }: { label: string }) {
  return (
    <div className="spinner" role="status" aria-live="polite">
      <span className="spinner__ring" aria-hidden="true" />
      <span className="sr-only">{label}</span>
    </div>
  );
}
