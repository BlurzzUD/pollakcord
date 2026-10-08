import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import { api } from "../../api/client";
import type { Me, SchoolClass } from "../../api/types";
import { ErrorText } from "../../components/ErrorText";
import { SelectField, TextField } from "../../components/Field";
import { useAuth } from "../../store/auth";
import { useUi } from "../../store/ui";
import { safeNext } from "../../utils/navigation";
import { AuthLayout } from "./AuthLayout";
import { KretaVerifier } from "./KretaVerifier";
import { SecuritySetup } from "./SecuritySetup";

type Step = "kreta" | "account" | "security" | "class";
const STEPS: Step[] = ["kreta", "account", "security", "class"];

function ClassPrompt({ onDone }: { onDone: (user: Me) => void }) {
  const { t } = useTranslation();
  const [show, setShow] = useState<boolean | null>(null);
  const [classId, setClassId] = useState("");
  const [visibility, setVisibility] = useState("everyone");
  const classes = useQuery({ queryKey: ["classes"], queryFn: () => api.get<SchoolClass[]>("/me/classes") });
  const save = useMutation({
    mutationFn: (payload: { class_id?: string; visibility: string }) => api.put<Me>("/me/class", payload),
    onSuccess: onDone,
  });

  if (show === null) {
    return (
      <div>
        <p className="confirm-identity__question">{t("class.prompt")}</p>
        <p className="muted">{t("class.prompt_text")}</p>
        <div className="button-row">
          <button type="button" className="button button--primary" onClick={() => setShow(true)} autoFocus>
            {t("common.yes")}
          </button>
          <button type="button" className="button button--outline" onClick={() => save.mutate({ visibility: "hidden" })} disabled={save.isPending}>
            {t("common.no")}
          </button>
        </div>
        <ErrorText error={save.error} />
      </div>
    );
  }
  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        save.mutate({ class_id: classId, visibility });
      }}
    >
      <SelectField
        label={t("class.choose")}
        value={classId}
        onChange={(event) => setClassId(event.target.value)}
        options={[{ value: "", label: t("class.select_placeholder") }, ...(classes.data ?? []).map((item) => ({ value: item.id, label: item.code }))]}
        required
      />
      <SelectField
        label={t("class.who_sees")}
        hint={t("class.who_sees_hint")}
        value={visibility}
        onChange={(event) => setVisibility(event.target.value)}
        options={(["everyone", "shared_servers", "friends"] as const).map((value) => ({ value, label: t(`privacy.class_visibility_${value}`) }))}
      />
      <ErrorText error={save.error} />
      <button type="submit" className="button button--primary button--block" disabled={!classId || save.isPending}>
        {t("common.save")}
      </button>
      <button type="button" className="button button--ghost button--block" onClick={() => setShow(null)}>
        {t("common.back")}
      </button>
    </form>
  );
}

export function RegisterPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const status = useAuth((state) => state.status);
  const setup = useAuth((state) => state.setup);
  const me = useAuth((state) => state.me);
  const setMe = useAuth((state) => state.setMe);
  const push = useUi((state) => state.push);
  const [step, setStep] = useState<Step>("kreta");
  const [started, setStarted] = useState(false);
  const [username, setUsername] = useState("");
  const [displayName, setDisplayName] = useState("");

  useEffect(() => {
    if (started || status === "loading") {
      return;
    }
    if (status === "authenticated" && me && !me.settings.class_prompt_answered) {
      setStep("class");
    } else if (status === "anonymous" && setup) {
      setStep("security");
    }
    setStarted(true);
  }, [status, setup, me, started]);

  const create = useMutation({
    mutationFn: () => api.post<{ username: string; display_name: string }>("/auth/register", { username, display_name: displayName }),
    onSuccess: () => setStep("security"),
  });

  const finish = (user: Me) => {
    setMe(user);
    push("success", t("auth.greeting", { name: user.display_name }));
    navigate(safeNext(params.get("next")), { replace: true });
  };

  return (
    <AuthLayout title={t("auth.register")} subtitle={t(`register.subtitle_${step}`)}>
      <ol className="steps" aria-label={t("register.progress")}>
        {STEPS.map((value, index) => (
          <li key={value} aria-current={value === step ? "step" : undefined} className={STEPS.indexOf(step) > index ? "is-done" : value === step ? "is-current" : ""}>
            <span className="steps__number">{index + 1}</span>
            <span className="steps__label">{t(`register.step_${value}`)}</span>
          </li>
        ))}
      </ol>
      {step === "kreta" ? <KretaVerifier intent="register" onConfirmed={() => setStep("account")} /> : null}
      {step === "account" ? (
        <form
          onSubmit={(event) => {
            event.preventDefault();
            create.mutate();
          }}
        >
          <p className="muted">{t("register.account_note")}</p>
          <TextField label={t("auth.username")} hint={t("register.username_hint")} value={username} onChange={(event) => setUsername(event.target.value.toLowerCase())} autoComplete="username" autoCapitalize="none" spellCheck={false} minLength={3} maxLength={24} required autoFocus />
          <TextField label={t("auth.display_name")} hint={t("register.display_name_hint")} value={displayName} onChange={(event) => setDisplayName(event.target.value)} autoComplete="nickname" maxLength={32} required />
          <ErrorText error={create.error} />
          <button type="submit" className="button button--primary button--block" disabled={create.isPending || username.length < 3 || !displayName.trim()}>
            {t("common.next")}
          </button>
        </form>
      ) : null}
      {step === "security" ? (
        <SecuritySetup
          onComplete={(user) => {
            setMe(user);
            setStep("class");
          }}
        />
      ) : null}
      {step === "class" ? <ClassPrompt onDone={finish} /> : null}
      {step === "kreta" ? (
        <p className="auth__links">
          <span>
            {t("auth.have_account")} <Link to="/login">{t("auth.login")}</Link>
          </span>
        </p>
      ) : null}
    </AuthLayout>
  );
}
