import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";

import { api } from "../../api/client";
import type { Me, SessionRow } from "../../api/types";
import { ErrorText } from "../../components/ErrorText";
import { TextField } from "../../components/Field";
import { useAuth } from "../../store/auth";
import { useUi } from "../../store/ui";
import { formatDateTime } from "../../utils/format";
import { RecoveryCodes, SecuritySetup } from "../auth/SecuritySetup";

export function SecuritySection() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const setMe = useAuth((state) => state.setMe);
  const logout = useAuth((state) => state.logout);
  const push = useUi((state) => state.push);
  const [secret, setSecret] = useState("");
  const [mode, setMode] = useState<"idle" | "change" | "codes">("idle");
  const [codes, setCodes] = useState<string[]>([]);
  const sessions = useQuery({ queryKey: ["sessions"], queryFn: () => api.get<SessionRow[]>("/me/sessions") });
  const remaining = useQuery({ queryKey: ["recovery-count"], queryFn: () => api.get<{ remaining: number }>("/me/recovery-codes") });
  const revoke = useMutation({
    mutationFn: (id: string) => api.del(`/me/sessions/${id}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["sessions"] }),
  });
  const begin = useMutation({
    mutationFn: () => api.post("/me/security/begin", { current_secret: secret }),
    onSuccess: () => {
      setSecret("");
      setMode("change");
    },
  });
  const regenerate = useMutation({
    mutationFn: () => api.post<{ recovery_codes: string[] }>("/me/recovery-codes", { current_secret: secret }),
    onSuccess: (result) => {
      setSecret("");
      setCodes(result.recovery_codes);
      setMode("codes");
      void queryClient.invalidateQueries({ queryKey: ["recovery-count"] });
    },
  });

  if (mode === "change") {
    return (
      <div className="section">
        <h2>{t("security.change_title")}</h2>
        <SecuritySetup
          onComplete={(user: Me) => {
            setMe(user);
            setMode("idle");
            push("success", t("common.saved"));
          }}
        />
      </div>
    );
  }
  if (mode === "codes") {
    return (
      <div className="section">
        <h2>{t("security.recovery_codes")}</h2>
        <RecoveryCodes codes={codes} onDone={() => setMode("idle")} />
      </div>
    );
  }

  return (
    <div className="section">
      <h2>{t("settings.security")}</h2>
      <section>
        <h3>{t("security.reauth_title")}</h3>
        <p className="muted">{t("security.reauth_text")}</p>
        <TextField label={t("security.current_secret")} type="password" value={secret} onChange={(event) => setSecret(event.target.value)} autoComplete="current-password" />
        <ErrorText error={begin.error ?? regenerate.error} />
        <div className="button-row">
          <button type="button" className="button button--outline" onClick={() => begin.mutate()} disabled={!secret || begin.isPending}>
            {t("security.change_credentials")}
          </button>
          <button type="button" className="button button--outline" onClick={() => regenerate.mutate()} disabled={!secret || regenerate.isPending}>
            {t("security.regenerate_codes")}
          </button>
        </div>
        <p className="muted">{t("security.codes_remaining", { count: remaining.data?.remaining ?? 0 })}</p>
      </section>
      <section>
        <h3>{t("security.sessions")}</h3>
        <ul className="list">
          {(sessions.data ?? []).map((session) => (
            <li key={session.id} className="list__row">
              <div className="list__item list__item--stack">
                <strong>
                  {session.user_agent.slice(0, 60) || t("security.unknown_device")} {session.current ? <span className="badge">{t("security.this_device")}</span> : null}
                </strong>
                <span className="muted">
                  {t("security.last_active")}: {formatDateTime(session.last_seen_at)} · {session.ip_hint}
                </span>
              </div>
              {!session.current ? (
                <button type="button" className="button button--small button--danger-ghost" onClick={() => revoke.mutate(session.id)}>
                  {t("security.revoke")}
                </button>
              ) : null}
            </li>
          ))}
        </ul>
      </section>
      <button
        type="button"
        className="button button--danger"
        onClick={async () => {
          await logout();
          navigate("/", { replace: true });
        }}
      >
        {t("auth.logout")}
      </button>
    </div>
  );
}
