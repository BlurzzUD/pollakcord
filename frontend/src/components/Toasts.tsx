import { useTranslation } from "react-i18next";

import { useUi } from "../store/ui";
import { Icon } from "./Icon";

export function Toasts() {
  const { t } = useTranslation();
  const toasts = useUi((state) => state.toasts);
  const dismiss = useUi((state) => state.dismiss);
  return (
    <div className="toasts" role="region" aria-label={t("a11y.notifications_region")}>
      {toasts.map((toast) => (
        <div key={toast.id} className={`toast toast--${toast.kind}`} role={toast.kind === "error" ? "alert" : "status"}>
          <span>{toast.message}</span>
          <button type="button" className="icon-button" onClick={() => dismiss(toast.id)} aria-label={t("common.dismiss")}>
            <Icon name="close" size={16} />
          </button>
        </div>
      ))}
    </div>
  );
}
