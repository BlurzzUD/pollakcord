import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";
import { useTranslation } from "react-i18next";

import { api } from "../../api/client";
import { useMeta } from "../../api/hooks";
import type { DokMessage, DokTarget } from "../../api/types";
import { useAuth } from "../../store/auth";
import { targetLabel, targetValue } from "../../utils/dok";
import { ConfirmDialog } from "../ConfirmDialog";
import { ErrorText } from "../ErrorText";
import { SelectField } from "../Field";
import { Icon } from "../Icon";

interface DokComposerProps {
  targets: DokTarget[];
  preferred?: string;
  onSent: (message: DokMessage) => void;
}

function defaultValue(targets: DokTarget[], preferred: string | undefined, ownClass: string | null | undefined): string {
  if (preferred && targets.some((target) => targetValue(target) === preferred)) {
    return preferred;
  }
  const own = targets.find((target) => target.type === "class" && target.code === ownClass);
  const fallback = own ?? targets.find((target) => target.type === "class") ?? targets[0];
  return fallback ? targetValue(fallback) : "";
}

export function DokComposer({ targets, preferred, onSent }: DokComposerProps) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const meta = useMeta();
  const inputId = useId();
  const ownClass = useAuth((state) => state.me?.class_code);
  const [text, setText] = useState("");
  const [selected, setSelected] = useState(() => defaultValue(targets, preferred, ownClass));
  const [confirming, setConfirming] = useState(false);
  const area = useRef<HTMLTextAreaElement>(null);
  const maxLength = meta.data?.limits.message_max_length ?? 4000;
  const current = targets.find((target) => targetValue(target) === selected) ?? targets[0];

  useEffect(() => {
    const element = area.current;
    if (element) {
      element.style.height = "auto";
      element.style.height = `${Math.min(element.scrollHeight, 180)}px`;
    }
  }, [text]);

  const send = useMutation({
    mutationFn: (target: DokTarget) =>
      api.post<DokMessage>("/dok/messages", {
        content: text,
        target: target.type === "school" ? { type: "school" } : { type: "class", class_id: target.class_id },
      }),
    onSuccess: (message) => {
      setText("");
      setConfirming(false);
      void queryClient.invalidateQueries({ queryKey: ["dok"] });
      onSent(message);
    },
    onError: () => setConfirming(false),
  });

  const submit = () => {
    if (!current || !text.trim() || send.isPending) {
      return;
    }
    if (current.type === "school") {
      setConfirming(true);
      return;
    }
    send.mutate(current);
  };

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      submit();
    }
  };

  const remaining = maxLength - text.length;

  return (
    <div className="composer dok-composer">
      {targets.length > 1 ? (
        <SelectField
          label={t("dok.to")}
          value={selected}
          onChange={(event) => setSelected(event.target.value)}
          options={targets.map((target) => ({ value: targetValue(target), label: targetLabel(t, target) }))}
        />
      ) : current ? (
        <p className="dok-target">
          <Icon name="users" size={16} /> {t("dok.to_locked", { target: targetLabel(t, current) })}
        </p>
      ) : null}
      <p className="dok-sender-notice">{t("dok.sender_notice")}</p>
      <div className="composer__row">
        <label className="sr-only" htmlFor={inputId}>
          {t("dok.composer_label")}
        </label>
        <textarea id={inputId} ref={area} rows={1} value={text} maxLength={maxLength} placeholder={t("dok.composer_placeholder")} onChange={(event) => setText(event.target.value)} onKeyDown={onKeyDown} />
        <button type="button" className="button button--primary composer__send" onClick={submit} disabled={send.isPending || !text.trim()} aria-label={t("message.send")}>
          <Icon name="send" />
        </button>
      </div>
      <div className="composer__meta">
        <span className="muted">{t("dok.composer_hint")}</span>
        {remaining < 200 ? <span className={remaining < 0 ? "form-error" : "muted"}>{remaining}</span> : null}
      </div>
      <ErrorText error={send.error} />
      {confirming && current ? (
        <ConfirmDialog
          title={t("dok.confirm_school_title")}
          message={t("dok.confirm_school_message")}
          confirmLabel={t("dok.confirm_school_confirm")}
          busy={send.isPending}
          onCancel={() => setConfirming(false)}
          onConfirm={() => send.mutate(current)}
        />
      ) : null}
    </div>
  );
}
