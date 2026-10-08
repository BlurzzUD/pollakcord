import { useTranslation } from "react-i18next";

import { useAuth } from "../store/auth";
import { useUi } from "../store/ui";
import { copyText } from "../utils/clipboard";
import { Icon } from "./Icon";

interface CopyIdProps {
  value: string;
  label: string;
  always?: boolean;
}

export function useDeveloperMode(): boolean {
  return useAuth((state) => state.me?.settings.developer_mode ?? false);
}

export function CopyId({ value, label, always }: CopyIdProps) {
  const { t } = useTranslation();
  const developer = useDeveloperMode();
  const push = useUi((state) => state.push);
  if (!developer && !always) {
    return null;
  }
  const copy = async () => {
    const ok = await copyText(value);
    push(ok ? "success" : "error", ok ? t("developer.copied", { label }) : t("developer.copy_failed"));
  };
  return (
    <button type="button" className="id-chip" onClick={copy} aria-label={t("developer.copy_label", { label })} title={t("developer.copy_label", { label })}>
      <span className="id-chip__label">{label}</span>
      <code>{value}</code>
      <Icon name="copy" size={14} />
    </button>
  );
}
