import { useTranslation } from "react-i18next";
import { Link, Navigate } from "react-router-dom";

import { Brand } from "../../components/Brand";
import { Icon, type IconName } from "../../components/Icon";
import { LanguageSwitcher } from "../../components/LanguageSwitcher";
import { useAuth } from "../../store/auth";

const FEATURES: { icon: IconName; key: string }[] = [
  { icon: "shield", key: "private" },
  { icon: "users", key: "school" },
  { icon: "volume", key: "voice" },
];

export function LandingPage() {
  const { t } = useTranslation();
  const status = useAuth((state) => state.status);
  if (status === "authenticated") {
    return <Navigate to="/app" replace />;
  }
  return (
    <div className="landing">
      <a className="skip-link" href="#landing-main">
        {t("a11y.skip_to_content")}
      </a>
      <header className="auth__bar">
        <Brand />
        <LanguageSwitcher />
      </header>
      <main id="landing-main" className="landing__hero" tabIndex={-1}>
        <p className="landing__kicker">{t("landing.kicker")}</p>
        <h1>{t("landing.headline")}</h1>
        <p className="landing__lead">{t("landing.lead")}</p>
        <div className="landing__actions">
          <Link to="/login" className="button button--primary button--large">
            {t("auth.login")}
          </Link>
          <Link to="/register" className="button button--outline button--large">
            {t("auth.register")}
          </Link>
        </div>
        <ul className="landing__features">
          {FEATURES.map((feature) => (
            <li key={feature.key}>
              <Icon name={feature.icon} size={26} />
              <h2>{t(`landing.features.${feature.key}.title`)}</h2>
              <p>{t(`landing.features.${feature.key}.text`)}</p>
            </li>
          ))}
        </ul>
      </main>
      <footer className="auth__foot">{t("landing.privacy_note")}</footer>
    </div>
  );
}
