import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { AuthLayout } from "./auth/AuthLayout";

export function NotFoundPage() {
  const { t } = useTranslation();
  return (
    <AuthLayout title={t("errors.not_found_title")} subtitle={t("errors.not_found")}>
      <Link className="button button--primary" to="/">
        {t("common.home")}
      </Link>
    </AuthLayout>
  );
}
