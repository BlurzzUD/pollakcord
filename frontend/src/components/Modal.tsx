import { useEffect, useId, useRef, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { useTranslation } from "react-i18next";

import { Icon } from "./Icon";

interface ModalProps {
  title: string;
  onClose: () => void;
  children: ReactNode;
  wide?: boolean;
  footer?: ReactNode;
}

const FOCUSABLE = 'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])';

export function Modal({ title, onClose, children, wide, footer }: ModalProps) {
  const { t } = useTranslation();
  const titleId = useId();
  const panel = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const first = panel.current?.querySelector<HTMLElement>("[data-autofocus]") ?? panel.current?.querySelector<HTMLElement>(FOCUSABLE);
    first?.focus();
    document.body.classList.add("modal-open");
    return () => {
      document.body.classList.remove("modal-open");
      previous?.focus();
    };
  }, []);

  const onKeyDown = (event: React.KeyboardEvent) => {
    if (event.key === "Escape") {
      event.stopPropagation();
      onClose();
      return;
    }
    if (event.key !== "Tab" || !panel.current) {
      return;
    }
    const items = Array.from(panel.current.querySelectorAll<HTMLElement>(FOCUSABLE));
    if (items.length === 0) {
      return;
    }
    const first = items[0];
    const last = items[items.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  };

  return createPortal(
    <div className="modal-backdrop" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <div ref={panel} className={`modal${wide ? " modal--wide" : ""}`} role="dialog" aria-modal="true" aria-labelledby={titleId} onKeyDown={onKeyDown}>
        <header className="modal__header">
          <h2 id={titleId}>{title}</h2>
          <button type="button" className="icon-button" onClick={onClose} aria-label={t("common.close")}>
            <Icon name="close" />
          </button>
        </header>
        <div className="modal__body">{children}</div>
        {footer ? <footer className="modal__footer">{footer}</footer> : null}
      </div>
    </div>,
    document.body,
  );
}
