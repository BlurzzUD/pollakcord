import { useTranslation } from "react-i18next";

import type { Me, Privacy } from "../../api/types";
import { SelectField } from "../../components/Field";
import { useAuth } from "../../store/auth";
import { useSaveSettings } from "./useSaveSettings";

const OPTIONS: { key: keyof Privacy; values: string[] }[] = [
  { key: "friend_requests", values: ["everyone", "shared_servers", "nobody"] },
  { key: "direct_messages", values: ["everyone", "shared_servers", "friends"] },
  { key: "class_visibility", values: ["hidden", "friends", "shared_servers", "everyone"] },
  { key: "online_status", values: ["friends", "shared_servers", "nobody"] },
  { key: "profile_visibility", values: ["shared_context", "friends", "everyone"] },
  { key: "activity_visibility", values: ["friends", "nobody"] },
  { key: "voice_calls", values: ["friends", "nobody"] },
];

export function PrivacySection() {
  const { t } = useTranslation();
  const me = useAuth((state) => state.me) as Me;
  const save = useSaveSettings();
  return (
    <div className="section">
      <h2>{t("settings.privacy")}</h2>
      <p className="muted">{t("privacy.intro")}</p>
      {OPTIONS.map(({ key, values }) => (
        <SelectField
          key={key}
          label={t(`privacy.${key}`)}
          hint={t(`privacy.${key}_hint`)}
          value={me.settings.privacy[key]}
          disabled={save.isPending}
          onChange={(event) => save.mutate({ [key]: event.target.value })}
          options={values.map((value) => ({ value, label: t(`privacy.${key}_${value}`) }))}
        />
      ))}
    </div>
  );
}
