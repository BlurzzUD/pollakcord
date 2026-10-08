import { useTranslation } from "react-i18next";

import { ApiError } from "../api/client";

export function errorMessage(t: (key: string, options?: Record<string, unknown>) => string, error: unknown): string {
  if (error instanceof ApiError) {
    const key = `errors.${error.code}`;
    const translated = t(key, error.params);
    return translated === key ? t("errors.request_failed") : translated;
  }
  return t("errors.network_error");
}

export function ErrorText({ error, id }: { error: unknown; id?: string }) {
  const { t } = useTranslation();
  if (!error) {
    return null;
  }
  return (
    <p className="form-error" role="alert" id={id}>
      {errorMessage(t, error)}
    </p>
  );
}
