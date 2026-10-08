import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "../../api/client";
import { ErrorText } from "../../components/ErrorText";
import { TextField } from "../../components/Field";

type Step = "credentials" | "twofactor" | "confirm";
type StartResult = { status: "two_factor_required" } | { status: "identified"; full_name: string; resume: boolean };

interface KretaVerifierProps {
  intent: "register" | "recover";
  onConfirmed: () => void;
}

export function KretaVerifier({ intent, onConfirmed }: KretaVerifierProps) {
  const { t } = useTranslation();
  const [step, setStep] = useState<Step>("credentials");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [fullName, setFullName] = useState("");
  const [resume, setResume] = useState(false);

  const reset = () => {
    setStep("credentials");
    setPassword("");
    setCode("");
    setFullName("");
  };

  const handle = (result: StartResult) => {
    setPassword("");
    if (result.status === "two_factor_required") {
      setStep("twofactor");
      return;
    }
    setFullName(result.full_name);
    setResume(result.resume);
    setStep("confirm");
  };

  const start = useMutation({
    mutationFn: () => api.post<StartResult>("/auth/kreta/start", { intent, username, password }),
    onSuccess: handle,
  });
  const twoFactor = useMutation({
    mutationFn: () => api.post<StartResult>("/auth/kreta/two-factor", { code }),
    onSuccess: handle,
    onError: reset,
  });
  const decide = useMutation({
    mutationFn: (confirmed: boolean) => api.post("/auth/kreta/confirm", { confirmed }),
    onSuccess: (_, confirmed) => {
      if (confirmed) {
        setFullName("");
        onConfirmed();
      } else {
        reset();
      }
    },
  });

  if (step === "confirm") {
    return (
      <div className="confirm-identity">
        <p className="confirm-identity__question" aria-live="polite">
          {t("kreta.are_you", { name: fullName })}
        </p>
        <p className="muted">{resume ? t("kreta.resume_note") : t("kreta.private_note")}</p>
        <ErrorText error={decide.error} />
        <div className="button-row">
          <button type="button" className="button button--primary" onClick={() => decide.mutate(true)} disabled={decide.isPending} data-autofocus autoFocus>
            {t("common.yes")}
          </button>
          <button type="button" className="button button--outline" onClick={() => decide.mutate(false)} disabled={decide.isPending}>
            {t("common.no")}
          </button>
        </div>
      </div>
    );
  }

  if (step === "twofactor") {
    return (
      <form
        onSubmit={(event) => {
          event.preventDefault();
          twoFactor.mutate();
        }}
      >
        <p>{t("kreta.two_factor_intro")}</p>
        <TextField
          label={t("kreta.two_factor_code")}
          hint={t("kreta.two_factor_hint")}
          value={code}
          onChange={(event) => setCode(event.target.value.replace(/\D/g, "").slice(0, 6))}
          inputMode="numeric"
          autoComplete="one-time-code"
          pattern="[0-9]{6}"
          required
          autoFocus
        />
        <ErrorText error={twoFactor.error} />
        <button type="submit" className="button button--primary button--block" disabled={twoFactor.isPending || code.length !== 6}>
          {t("common.next")}
        </button>
      </form>
    );
  }

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        start.mutate();
      }}
    >
      <div className="notice" role="note">
        <strong>{t("kreta.notice_title")}</strong>
        <p>{t("kreta.notice_text")}</p>
      </div>
      <TextField label={t("kreta.username")} value={username} onChange={(event) => setUsername(event.target.value)} autoComplete="off" autoCapitalize="none" spellCheck={false} required autoFocus />
      <TextField label={t("kreta.password")} type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete="off" required />
      <ErrorText error={start.error ?? twoFactor.error} />
      <button type="submit" className="button button--primary button--block" disabled={start.isPending || !username.trim() || !password}>
        {start.isPending ? t("kreta.verifying") : t("kreta.verify")}
      </button>
    </form>
  );
}
