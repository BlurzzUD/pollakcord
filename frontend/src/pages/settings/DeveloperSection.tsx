import { useTranslation } from "react-i18next";

import type { Me } from "../../api/types";
import { CopyId } from "../../components/CopyId";
import { Toggle } from "../../components/Field";
import { useAuth } from "../../store/auth";
import { useSaveSettings } from "./useSaveSettings";

export function DeveloperSection() {
  const { t } = useTranslation();
  const me = useAuth((state) => state.me) as Me;
  const save = useSaveSettings();
  return (
    <div className="section">
      <h2>{t("settings.developer")}</h2>
      <p className="muted">{t("developer.intro")}</p>
      <Toggle label={t("developer.mode")} hint={t("developer.mode_hint")} checked={me.settings.developer_mode} disabled={save.isPending} onChange={(value) => save.mutate({ developer_mode: value })} />
      <p className="notice">{t("developer.never_shown")}</p>
      <CopyId value={me.id} label={t("developer.user_id")} always />
    </div>
  );
}
