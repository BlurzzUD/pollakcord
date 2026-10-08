import { useTranslation } from "react-i18next";

import { Modal } from "./Modal";

interface ConfirmDialogProps {
  title: string;
  message: string;
  confirmLabel?: string;
  danger?: boolean;
  busy?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

export function ConfirmDialog({ title, message, confirmLabel, danger, busy, onConfirm, onCancel }: ConfirmDialogProps) {
  const { t } = useTranslation();
  return (
    <Modal
      title={title}
      onClose={onCancel}
      footer={
        <>
          <button type="button" className="button button--ghost" onClick={onCancel}>
            {t("common.cancel")}
          </button>
          <button type="button" className={`button ${danger ? "button--danger" : "button--primary"}`} onClick={onConfirm} disabled={busy} data-autofocus>
            {confirmLabel ?? t("common.confirm")}
          </button>
        </>
      }
    >
      <p>{message}</p>
    </Modal>
  );
}
