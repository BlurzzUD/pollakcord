import { useTranslation } from "react-i18next";

import { api } from "../api/client";
import { LANGUAGES, isLanguage, setLanguage } from "../i18n";
import { useAuth } from "../store/auth";

export function LanguageSwitcher() {
  const { t, i18n } = useTranslation();
  const authenticated = useAuth((state) => state.status === "authenticated");
  const change = (value: string) => {
    if (!isLanguage(value)) {
      return;
    }
    setLanguage(value);
    if (authenticated) {
      void api.patch("/me/settings", { language: value });
    }
  };
  return (
    <div className="language-switcher">
      <label htmlFor="language-select" className="sr-only">
        {t("settings.language")}
      </label>
      <select id="language-select" value={i18n.language} onChange={(event) => change(event.target.value)}>
        {LANGUAGES.map((language) => (
          <option key={language.code} value={language.code}>
            {language.label}
          </option>
        ))}
      </select>
    </div>
  );
}
