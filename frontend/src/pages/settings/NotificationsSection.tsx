import { useTranslation } from "react-i18next";

import type { Me, NotificationPrefs } from "../../api/types";
import { Toggle } from "../../components/Field";
import { useAuth } from "../../store/auth";
import { useSaveSettings } from "./useSaveSettings";

const KEYS: (keyof NotificationPrefs)[] = ["friend_requests", "direct_messages", "mentions", "server", "calls", "moderation", "dok", "sounds"];

export function NotificationsSection() {
  const { t } = useTranslation();
  const me = useAuth((state) => state.me) as Me;
  const save = useSaveSettings();
  return (
    <div className="section">
      <h2>{t("settings.notifications")}</h2>
      <p className="muted">{t("notifications.settings_intro")}</p>
      {KEYS.map((key) => (
        <Toggle key={key} label={t(`notifications.pref_${key}`)} hint={t(`notifications.pref_${key}_hint`)} checked={me.settings.notification_prefs[key]} disabled={save.isPending} onChange={(value) => save.mutate({ notification_prefs: { [key]: value } })} />
      ))}
    </div>
  );
}
