import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "../../api/client";
import type { Me } from "../../api/types";
import { ErrorText } from "../../components/ErrorText";
import { Icon } from "../../components/Icon";
import { TextField } from "../../components/Field";
import { useUi } from "../../store/ui";
import { copyText } from "../../utils/clipboard";

interface SetupResult {
  user: Me;
  recovery_codes: string[];
}

interface TotpBegin {
  manual_key: string;
  otpauth_uri: string;
  qr_svg: string;
}

export function RecoveryCodes({ codes, onDone }: { codes: string[]; onDone: () => void }) {
  const { t } = useTranslation();
  const push = useUi((state) => state.push);
  const [saved, setSaved] = useState(false);
  const text = codes.join("\n");
  const copy = async (value: string) => {
    const ok = await copyText(value);
    push(ok ? "success" : "error", ok ? t("common.copied") : t("developer.copy_failed"));
  };
  const download = () => {
    const blob = new Blob([`PollákCord\n\n${text}\n`], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "pollakcord-recovery-codes.txt";
    link.click();
    URL.revokeObjectURL(url);
  };
  return (
    <div>
      <p>{t("security.recovery_intro")}</p>
      <ul className="recovery-codes" aria-label={t("security.recovery_codes")}>
        {codes.map((code) => (
          <li key={code}>
            <code>{code}</code>
          </li>
        ))}
      </ul>
      <div className="button-row">
        <button type="button" className="button button--outline" onClick={() => void copy(text)}>
          <Icon name="copy" /> {t("common.copy")}
        </button>
        <button type="button" className="button button--outline" onClick={download}>
          {t("security.download")}
        </button>
      </div>
      <label className="check">
        <input type="checkbox" checked={saved} onChange={(event) => setSaved(event.target.checked)} />
        <span>{t("security.recovery_saved")}</span>
      </label>
      <button type="button" className="button button--primary button--block" disabled={!saved} onClick={onDone}>
        {t("common.continue")}
      </button>
    </div>
  );
}

export function SecuritySetup({ onComplete }: { onComplete: (user: Me) => void }) {
  const { t } = useTranslation();
  const push = useUi((state) => state.push);
  const [method, setMethod] = useState<"password" | "totp" | null>(null);
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [code, setCode] = useState("");
  const [totp, setTotp] = useState<TotpBegin | null>(null);
  const [result, setResult] = useState<SetupResult | null>(null);
  const copy = async (value: string) => {
    const ok = await copyText(value);
    push(ok ? "success" : "error", ok ? t("common.copied") : t("developer.copy_failed"));
  };

  const savePassword = useMutation({
    mutationFn: () => api.post<SetupResult>("/auth/security/password", { password }),
    onSuccess: setResult,
  });
  const beginTotp = useMutation({
    mutationFn: () => api.post<TotpBegin>("/auth/security/totp/begin"),
    onSuccess: (data) => {
      setMethod("totp");
      setTotp(data);
    },
  });
  const confirmTotp = useMutation({
    mutationFn: () => api.post<SetupResult>("/auth/security/totp/confirm", { code }),
    onSuccess: setResult,
  });

  if (result) {
    return <RecoveryCodes codes={result.recovery_codes} onDone={() => onComplete(result.user)} />;
  }

  if (method === null) {
    return (
      <div>
        <p>{t("security.choose_intro")}</p>
        <div className="choice-grid">
          <button type="button" className="choice" onClick={() => setMethod("password")}>
            <Icon name="lock" size={26} />
            <strong>{t("security.method_password")}</strong>
            <span>{t("security.method_password_text")}</span>
          </button>
          <button type="button" className="choice" onClick={() => beginTotp.mutate()} disabled={beginTotp.isPending}>
            <Icon name="shield" size={26} />
            <strong>{t("security.method_totp")}</strong>
            <span>{t("security.method_totp_text")}</span>
          </button>
        </div>
        <ErrorText error={beginTotp.error} />
      </div>
    );
  }

  if (method === "password") {
    const mismatch = confirm.length > 0 && confirm !== password;
    return (
      <form
        onSubmit={(event) => {
          event.preventDefault();
          if (!mismatch) {
            savePassword.mutate();
          }
        }}
      >
        <TextField label={t("auth.new_password")} hint={t("security.password_hint")} type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete="new-password" minLength={10} maxLength={128} required autoFocus />
        <TextField label={t("auth.confirm_password")} type="password" value={confirm} onChange={(event) => setConfirm(event.target.value)} autoComplete="new-password" error={mismatch ? t("auth.passwords_differ") : null} required />
        <ErrorText error={savePassword.error} />
        <button type="submit" className="button button--primary button--block" disabled={savePassword.isPending || password.length < 10 || mismatch || !confirm}>
          {t("security.save_password")}
        </button>
        <button type="button" className="button button--ghost button--block" onClick={() => setMethod(null)}>
          {t("common.back")}
        </button>
      </form>
    );
  }

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        confirmTotp.mutate();
      }}
    >
      <p>{t("security.totp_intro")}</p>
      {totp ? (
        <>
          <img className="qr" src={totp.qr_svg} alt={t("security.qr_alt")} width={200} height={200} />
          <div className="manual-key">
            <span className="muted">{t("security.manual_key")}</span>
            <code>{totp.manual_key}</code>
            <button type="button" className="icon-button" aria-label={t("common.copy")} onClick={() => void copy(totp.manual_key.replace(/ /g, ""))}>
              <Icon name="copy" />
            </button>
          </div>
        </>
      ) : null}
      <TextField
        label={t("auth.totp_code")}
        hint={t("security.totp_confirm_hint")}
        value={code}
        onChange={(event) => setCode(event.target.value.replace(/\D/g, "").slice(0, 6))}
        inputMode="numeric"
        autoComplete="one-time-code"
        pattern="[0-9]{6}"
        required
        autoFocus
      />
      <ErrorText error={confirmTotp.error} />
      <button type="submit" className="button button--primary button--block" disabled={confirmTotp.isPending || code.length !== 6}>
        {t("security.confirm_totp")}
      </button>
      <button type="button" className="button button--ghost button--block" onClick={() => { setMethod(null); setTotp(null); setCode(""); }}>
        {t("common.back")}
      </button>
    </form>
  );
}
