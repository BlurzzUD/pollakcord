import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, Navigate, useNavigate, useSearchParams } from "react-router-dom";

import { api } from "../../api/client";
import type { Me } from "../../api/types";
import { ErrorText } from "../../components/ErrorText";
import { TextField } from "../../components/Field";
import { useAuth } from "../../store/auth";
import { useUi } from "../../store/ui";
import { safeNext } from "../../utils/navigation";
import { AuthLayout } from "./AuthLayout";

type Method = "password" | "totp";

export function LoginPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const status = useAuth((state) => state.status);
  const setMe = useAuth((state) => state.setMe);
  const push = useUi((state) => state.push);
  const [username, setUsername] = useState("");
  const [secret, setSecret] = useState("");
  const [method, setMethod] = useState<Method | null>(null);

  const identify = useMutation({
    mutationFn: () => api.post<{ method: Method }>("/auth/login/method", { username }),
    onSuccess: (result) => setMethod(result.method),
  });
  const login = useMutation({
    mutationFn: () => api.post<{ user: Me }>("/auth/login", { username, secret }),
    onSuccess: ({ user }) => {
      setMe(user);
      push("success", t("auth.greeting", { name: user.display_name }));
      navigate(safeNext(params.get("next")), { replace: true });
    },
    onError: () => setSecret(""),
  });

  if (status === "authenticated" && !login.isSuccess) {
    return <Navigate to={safeNext(params.get("next"))} replace />;
  }

  return (
    <AuthLayout title={t("auth.login")} subtitle={method ? t("auth.hello_again", { username }) : t("auth.login_subtitle")}>
      {method === null ? (
        <form
          onSubmit={(event) => {
            event.preventDefault();
            identify.mutate();
          }}
        >
          <TextField label={t("auth.username")} value={username} onChange={(event) => setUsername(event.target.value)} autoComplete="username" autoCapitalize="none" spellCheck={false} required data-autofocus autoFocus />
          <ErrorText error={identify.error} />
          <button type="submit" className="button button--primary button--block" disabled={identify.isPending || !username.trim()}>
            {t("common.next")}
          </button>
        </form>
      ) : (
        <form
          onSubmit={(event) => {
            event.preventDefault();
            login.mutate();
          }}
        >
          {method === "password" ? (
            <TextField label={t("auth.password")} type="password" value={secret} onChange={(event) => setSecret(event.target.value)} autoComplete="current-password" required autoFocus />
          ) : (
            <TextField
              label={t("auth.totp_code")}
              hint={t("auth.totp_hint")}
              value={secret}
              onChange={(event) => setSecret(event.target.value.replace(/\D/g, "").slice(0, 6))}
              inputMode="numeric"
              autoComplete="one-time-code"
              pattern="[0-9]{6}"
              required
              autoFocus
            />
          )}
          <ErrorText error={login.error} />
          <button type="submit" className="button button--primary button--block" disabled={login.isPending || !secret}>
            {t("auth.login")}
          </button>
          <button
            type="button"
            className="button button--ghost button--block"
            onClick={() => {
              setMethod(null);
              setSecret("");
              login.reset();
            }}
          >
            {t("common.back")}
          </button>
        </form>
      )}
      <p className="auth__links">
        <Link to="/recover">{t("auth.forgot")}</Link>
        <span>
          {t("auth.no_account")} <Link to="/register">{t("auth.register")}</Link>
        </span>
      </p>
    </AuthLayout>
  );
}
