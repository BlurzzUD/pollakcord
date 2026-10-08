import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Navigate, useLocation } from "react-router-dom";

import { useAuth } from "../store/auth";
import { Spinner } from "./EmptyState";

export function RequireAuth({ children }: { children: ReactNode }) {
  const { t } = useTranslation();
  const status = useAuth((state) => state.status);
  const location = useLocation();
  if (status === "loading") {
    return <Spinner label={t("common.loading")} />;
  }
  if (status !== "authenticated") {
    return <Navigate to={`/login?next=${encodeURIComponent(location.pathname)}`} replace />;
  }
  return <>{children}</>;
}
