import { useTranslation } from "react-i18next";

import { DISMISS_DELAY_MS } from "../../utils/dok";
import { useVisibleFor } from "./useVisibleFor";

export function DokDismiss({ onDismiss, busy = false }: { onDismiss: () => void; busy?: boolean }) {
  const { t } = useTranslation();
  const ready = useVisibleFor(DISMISS_DELAY_MS);
  return (
    <button type="button" className="button button--ghost button--small" disabled={!ready || busy} title={ready ? undefined : t("dok.dismiss_wait")} onClick={onDismiss}>
      {t("common.dismiss")}
    </button>
  );
}
