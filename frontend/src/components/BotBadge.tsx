import { useTranslation } from "react-i18next";

export function BotBadge({ isBot }: { isBot?: boolean }) {
  const { t } = useTranslation();
  return isBot ? <span className="badge badge--bot" aria-label={t("bots.badge")}>{t("bots.badge")}</span> : null;
}
