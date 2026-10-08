import { useTranslation } from "react-i18next";
import { Navigate, NavLink, useParams } from "react-router-dom";

import { Brand } from "../../components/Brand";
import { Icon } from "../../components/Icon";
import { Toasts } from "../../components/Toasts";
import { AccountSection } from "./AccountSection";
import { AppearanceSection } from "./AppearanceSection";
import { DeveloperSection } from "./DeveloperSection";
import { NotificationsSection } from "./NotificationsSection";
import { PrivacySection } from "./PrivacySection";
import { SecuritySection } from "./SecuritySection";

const SECTIONS = {
  account: AccountSection,
  privacy: PrivacySection,
  notifications: NotificationsSection,
  appearance: AppearanceSection,
  security: SecuritySection,
  developer: DeveloperSection,
} as const;

type SectionKey = keyof typeof SECTIONS;

export function SettingsPage() {
  const { t } = useTranslation();
  const { section } = useParams();
  if (!section) {
    return <Navigate to="/app/settings/account" replace />;
  }
  if (!(section in SECTIONS)) {
    return <Navigate to="/app/settings/account" replace />;
  }
  const Section = SECTIONS[section as SectionKey];
  return (
    <div className="settings">
      <a className="skip-link" href="#settings-main">
        {t("a11y.skip_to_content")}
      </a>
      <aside className="settings__nav">
        <Brand to="/app" />
        <NavLink to="/app" className="nav-item">
          <Icon name="arrowLeft" /> {t("settings.back_to_app")}
        </NavLink>
        <nav aria-label={t("settings.title")}>
          {(Object.keys(SECTIONS) as SectionKey[]).map((key) => (
            <NavLink key={key} to={`/app/settings/${key}`} className={({ isActive }) => `nav-item${isActive ? " is-active" : ""}`}>
              {t(`settings.${key}`)}
            </NavLink>
          ))}
        </nav>
      </aside>
      <main id="settings-main" className="settings__main" tabIndex={-1}>
        <Section />
      </main>
      <Toasts />
    </div>
  );
}
