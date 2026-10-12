import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";
import { useTranslation } from "react-i18next";

import { api } from "../../api/client";
import { useMeta } from "../../api/hooks";
import type { ClassSpaceMessage } from "../../api/types";
import { ErrorText } from "../ErrorText";
import { Icon } from "../Icon";

export function ClassSpaceComposer({ classId }: { classId: string }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const meta = useMeta();
  const inputId = useId();
  const [text, setText] = useState("");
  const area = useRef<HTMLTextAreaElement>(null);
  const maxLength = meta.data?.limits.message_max_length ?? 4000;

  useEffect(() => {
    const element = area.current;
    if (element) {
      element.style.height = "auto";
      element.style.height = `${Math.min(element.scrollHeight, 180)}px`;
    }
  }, [text]);

  const send = useMutation({
    mutationFn: (content: string) => api.post<ClassSpaceMessage>(`/class-spaces/${classId}/messages`, { content }),
    onSuccess: () => {
      setText("");
      void queryClient.invalidateQueries({ queryKey: ["class-space"] });
    },
  });

  const submit = () => {
    if (!text.trim() || send.isPending) {
      return;
    }
    send.mutate(text);
  };

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      submit();
    }
  };

  const remaining = maxLength - text.length;

  return (
    <div className="composer">
      <div className="composer__row">
        <label className="sr-only" htmlFor={inputId}>
          {t("classSpace.composer_label")}
        </label>
        <textarea id={inputId} ref={area} rows={1} value={text} maxLength={maxLength} placeholder={t("classSpace.composer_placeholder")} onChange={(event) => setText(event.target.value)} onKeyDown={onKeyDown} />
        <button type="button" className="button button--primary composer__send" onClick={submit} disabled={send.isPending || !text.trim()} aria-label={t("message.send")}>
          <Icon name="send" />
        </button>
      </div>
      <div className="composer__meta">
        <span className="muted">{t("classSpace.composer_hint")}</span>
        {remaining < 200 ? <span className={remaining < 0 ? "form-error" : "muted"}>{remaining}</span> : null}
      </div>
      <ErrorText error={send.error} />
    </div>
  );
}
