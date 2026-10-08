import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { Brand } from "../../components/Brand";
import { LanguageSwitcher } from "../../components/LanguageSwitcher";
import { Toasts } from "../../components/Toasts";

export function AuthLayout({ title, subtitle, children, wide }: { title: string; subtitle?: string; children: ReactNode; wide?: boolean }) {
  const { t } = useTranslation();
  return (
    <div className="auth">
      <a className="skip-link" href="#auth-main">
        {t("a11y.skip_to_content")}
      </a>
      <header className="auth__bar">
        <Brand />
        <LanguageSwitcher />
      </header>
      <main id="auth-main" className={`auth__card${wide ? " auth__card--wide" : ""}`} tabIndex={-1}>
        <h1>{title}</h1>
        {subtitle ? <p className="auth__subtitle">{subtitle}</p> : null}
        {children}
      </main>
      <footer className="auth__foot">{t("landing.privacy_note")}</footer>
      <Toasts />
    </div>
  );
}
