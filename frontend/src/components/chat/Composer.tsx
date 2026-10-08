import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import type { Message } from "../../api/types";
import { realtime } from "../../realtime/socket";
import { encodeMentions } from "../../utils/text";
import { Avatar } from "../Avatar";
import { ErrorText } from "../ErrorText";
import { Icon } from "../Icon";

export interface MentionCandidate {
  id: string;
  name: string;
  avatarUrl: string | null;
}

interface ComposerProps {
  placeholder: string;
  disabledReason: string | null;
  maxLength: number;
  typingTarget: { scope: "dm" | "channel"; id: string };
  replyTo: Message | null;
  onCancelReply: () => void;
  onSend: (content: string, replyTo: string | null) => Promise<void>;
  candidates: MentionCandidate[];
}

const TYPING_INTERVAL_MS = 3000;

export function Composer({ placeholder, disabledReason, maxLength, typingTarget, replyTo, onCancelReply, onSend, candidates }: ComposerProps) {
  const { t } = useTranslation();
  const [text, setText] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [picks, setPicks] = useState<Record<string, string>>({});
  const [cursor, setCursor] = useState(0);
  const [active, setActive] = useState(0);
  const area = useRef<HTMLTextAreaElement>(null);
  const lastTyping = useRef(0);

  useEffect(() => {
    setText("");
    setPicks({});
  }, [typingTarget.id]);

  useEffect(() => {
    if (replyTo) {
      area.current?.focus();
    }
  }, [replyTo]);

  useEffect(() => {
    const element = area.current;
    if (element) {
      element.style.height = "auto";
      element.style.height = `${Math.min(element.scrollHeight, 180)}px`;
    }
  }, [text]);

  const mentionQuery = useMemo(() => {
    const before = text.slice(0, cursor);
    const match = /(?:^|\s)@([^\s@]{0,32})$/u.exec(before);
    return match ? match[1].toLowerCase() : null;
  }, [text, cursor]);

  const suggestions = useMemo(() => {
    if (mentionQuery === null) {
      return [];
    }
    return candidates.filter((candidate) => candidate.name.toLowerCase().includes(mentionQuery)).slice(0, 6);
  }, [candidates, mentionQuery]);

  const choose = (candidate: MentionCandidate) => {
    const before = text.slice(0, cursor).replace(/@([^\s@]{0,32})$/u, `@${candidate.name} `);
    const next = before + text.slice(cursor);
    setText(next);
    setPicks((current) => ({ ...current, [candidate.name]: candidate.id }));
    setActive(0);
    window.setTimeout(() => {
      area.current?.focus();
      area.current?.setSelectionRange(before.length, before.length);
    });
  };

  const emitTyping = () => {
    const now = Date.now();
    if (now - lastTyping.current > TYPING_INTERVAL_MS) {
      lastTyping.current = now;
      realtime.send("typing", typingTarget);
    }
  };

  const submit = async () => {
    const content = encodeMentions(text.trim(), picks);
    if (!content || busy || disabledReason) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await onSend(content, replyTo?.id ?? null);
      setText("");
      setPicks({});
      onCancelReply();
    } catch (failure) {
      setError(failure);
    } finally {
      setBusy(false);
    }
  };

  const onKeyDown = (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (suggestions.length > 0) {
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault();
        setActive((index) => (index + (event.key === "ArrowDown" ? 1 : -1) + suggestions.length) % suggestions.length);
        return;
      }
      if (event.key === "Enter" || event.key === "Tab") {
        event.preventDefault();
        choose(suggestions[active] ?? suggestions[0]);
        return;
      }
    }
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      void submit();
    }
  };

  const remaining = maxLength - text.length;

  return (
    <div className="composer">
      {replyTo ? (
        <div className="composer__reply">
          <span>{t("message.replying_to", { name: replyTo.author?.display_name ?? t("message.unknown_user") })}</span>
          <button type="button" className="icon-button" onClick={onCancelReply} aria-label={t("message.cancel_reply")}>
            <Icon name="close" size={16} />
          </button>
        </div>
      ) : null}
      {suggestions.length > 0 ? (
        <ul className="composer__mentions" role="listbox" aria-label={t("message.mention_suggestions")}>
          {suggestions.map((candidate, index) => (
            <li key={candidate.id} role="option" aria-selected={index === active}>
              <button type="button" className={index === active ? "is-active" : ""} onMouseDown={(event) => event.preventDefault()} onClick={() => choose(candidate)}>
                <Avatar name={candidate.name} url={candidate.avatarUrl} size={24} />
                {candidate.name}
              </button>
            </li>
          ))}
        </ul>
      ) : null}
      <div className="composer__row">
        <label className="sr-only" htmlFor="composer-input">
          {placeholder}
        </label>
        <textarea
          id="composer-input"
          ref={area}
          rows={1}
          value={text}
          maxLength={maxLength}
          placeholder={disabledReason ?? placeholder}
          disabled={Boolean(disabledReason)}
          onChange={(event) => {
            setText(event.target.value);
            setCursor(event.target.selectionStart);
            if (event.target.value) {
              emitTyping();
            }
          }}
          onSelect={(event) => setCursor(event.currentTarget.selectionStart)}
          onKeyDown={onKeyDown}
        />
        <button type="button" className="button button--primary composer__send" onClick={() => void submit()} disabled={busy || !text.trim() || Boolean(disabledReason)} aria-label={t("message.send")}>
          <Icon name="send" />
        </button>
      </div>
      <div className="composer__meta">
        <span className="muted">{t("message.composer_hint")}</span>
        {remaining < 200 ? <span className={remaining < 0 ? "form-error" : "muted"}>{remaining}</span> : null}
      </div>
      <ErrorText error={error} />
    </div>
  );
}
