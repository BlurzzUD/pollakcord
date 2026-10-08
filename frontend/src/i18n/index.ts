import i18n from "i18next";
import { initReactI18next } from "react-i18next";

import type { Language } from "../api/types";
import de from "./locales/de.json";
import en from "./locales/en.json";
import hu from "./locales/hu.json";

export const LANGUAGES: { code: Language; label: string }[] = [
  { code: "hu", label: "Magyar" },
  { code: "en", label: "English" },
  { code: "de", label: "Deutsch" },
];
const STORAGE_KEY = "pc.language";

export function isLanguage(value: unknown): value is Language {
  return value === "hu" || value === "en" || value === "de";
}

function initialLanguage(): Language {
  const stored = typeof localStorage === "undefined" ? null : localStorage.getItem(STORAGE_KEY);
  return isLanguage(stored) ? stored : "hu";
}

void i18n.use(initReactI18next).init({
  resources: { hu: { translation: hu }, en: { translation: en }, de: { translation: de } },
  lng: initialLanguage(),
  fallbackLng: "hu",
  supportedLngs: ["hu", "en", "de"],
  interpolation: { escapeValue: false },
  returnNull: false,
});

export function setLanguage(language: Language): void {
  localStorage.setItem(STORAGE_KEY, language);
  document.documentElement.lang = language;
  void i18n.changeLanguage(language);
}

document.documentElement.lang = i18n.language;

export default i18n;
