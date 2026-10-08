import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import { api } from "../../api/client";
import type { Me } from "../../api/types";
import { ErrorText } from "../../components/ErrorText";
import { TextField } from "../../components/Field";
import { useAuth } from "../../store/auth";
import { useUi } from "../../store/ui";
import { safeNext } from "../../utils/navigation";
import { AuthLayout } from "./AuthLayout";
import { KretaVerifier } from "./KretaVerifier";
import { SecuritySetup } from "./SecuritySetup";

type Stage = "choose" | "kreta" | "code" | "security";

export function RecoverPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const setMe = useAuth((state) => state.setMe);
  const push = useUi((state) => state.push);
  const [stage, setStage] = useState<Stage>("choose");
  const [username, setUsername] = useState("");
  const [recoveryCode, setRecoveryCode] = useState("");

  const confirmKreta = useMutation({
    mutationFn: () => api.post("/auth/recover/kreta"),
    onSuccess: () => setStage("security"),
  });
  const useCode = useMutation({
    mutationFn: () => api.post("/auth/recover/code", { username, recovery_code: recoveryCode }),
    onSuccess: () => setStage("security"),
  });

  const finish = (user: Me) => {
    setMe(user);
    push("success", t("auth.greeting", { name: user.display_name }));
    navigate(safeNext(params.get("next")), { replace: true });
  };

  return (
    <AuthLayout title={t("recover.title")} subtitle={t(`recover.subtitle_${stage}`)}>
      {stage === "choose" ? (
        <div className="choice-grid">
          <button type="button" className="choice" onClick={() => setStage("kreta")}>
            <strong>{t("recover.with_kreta")}</strong>
            <span>{t("recover.with_kreta_text")}</span>
          </button>
          <button type="button" className="choice" onClick={() => setStage("code")}>
            <strong>{t("recover.with_code")}</strong>
            <span>{t("recover.with_code_text")}</span>
          </button>
        </div>
      ) : null}
      {stage === "kreta" ? (
        <>
          <KretaVerifier intent="recover" onConfirmed={() => confirmKreta.mutate()} />
          <ErrorText error={confirmKreta.error} />
        </>
      ) : null}
      {stage === "code" ? (
        <form
          onSubmit={(event) => {
            event.preventDefault();
            useCode.mutate();
          }}
        >
          <TextField label={t("auth.username")} value={username} onChange={(event) => setUsername(event.target.value)} autoComplete="username" autoCapitalize="none" required autoFocus />
          <TextField label={t("recover.code_label")} hint={t("recover.code_hint")} value={recoveryCode} onChange={(event) => setRecoveryCode(event.target.value)} autoComplete="off" spellCheck={false} required />
          <ErrorText error={useCode.error} />
          <button type="submit" className="button button--primary button--block" disabled={useCode.isPending || !username || recoveryCode.length < 8}>
            {t("common.next")}
          </button>
        </form>
      ) : null}
      {stage === "security" ? <SecuritySetup onComplete={finish} /> : null}
      <p className="auth__links">
        <Link to="/login">{t("recover.back_to_login")}</Link>
      </p>
    </AuthLayout>
  );
}
