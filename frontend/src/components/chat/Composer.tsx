import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import type { MediaConfig, Message, MessageMediaInput } from "../../api/types";
import { realtime } from "../../realtime/socket";
import { encodeMentions } from "../../utils/text";
import { Avatar } from "../Avatar";
import { ErrorText } from "../ErrorText";
import { Icon } from "../Icon";
import { SlashAutocomplete, type SlashHandle } from "./SlashAutocomplete";
import { GiphyPicker } from "./GiphyPicker";
import { formatFileSize } from "./MessageMedia";
import { useComposerMedia } from "./useComposerMedia";

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
  onSend: (content: string, replyTo: string | null, media?: MessageMediaInput) => Promise<void>;
  candidates: MentionCandidate[];
  mediaConfig?: MediaConfig;
}

const TYPING_INTERVAL_MS = 3000;

export function Composer({ placeholder, disabledReason, maxLength, typingTarget, replyTo, onCancelReply, onSend, candidates, mediaConfig }: ComposerProps) {
  const { t } = useTranslation();
  const [text, setText] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [picks, setPicks] = useState<Record<string, string>>({});
  const [cursor, setCursor] = useState(0);
  const [active, setActive] = useState(0);
  const [giphyOpen, setGiphyOpen] = useState(false);
  const media = useComposerMedia(typingTarget, mediaConfig);
  const fileInput = useRef<HTMLInputElement>(null);
  const currentTarget = useRef(typingTarget.id);
  currentTarget.current = typingTarget.id;
  const area = useRef<HTMLTextAreaElement>(null);
  const slash = useRef<SlashHandle>(null);
  const slashOpen = typingTarget.scope === "channel" && text.startsWith("/") && !disabledReason;
  const lastTyping = useRef(0);

  useEffect(() => {
    setText("");
    setPicks({});
    setGiphyOpen(false);
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
    if (slashOpen) { slash.current?.openFirst(); return; }
    const content = encodeMentions(text.trim(), picks);
    const hasMedia = media.attachments.length > 0 || Boolean(media.giphyId);
    if ((!content && !hasMedia) || busy || media.uploading || disabledReason) {
      return;
    }
    const target = typingTarget.id;
    setBusy(true);
    setError(null);
    try {
      if (hasMedia) {
        await onSend(content, replyTo?.id ?? null, { attachmentIds: media.attachments.map((file) => file.id), giphyId: media.giphyId });
      } else {
        await onSend(content, replyTo?.id ?? null);
      }
      if (currentTarget.current === target) {
        media.commit();
        setText("");
        setPicks({});
        onCancelReply();
      }
    } catch (failure) {
      setError(failure);
    } finally {
      setBusy(false);
    }
  };

  const onKeyDown = (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (!event.nativeEvent.isComposing && slashOpen && slash.current?.keyDown(event.key)) { event.preventDefault(); return; }
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
      {slashOpen ? <SlashAutocomplete ref={slash} channelId={typingTarget.id} text={text} onComplete={() => { setText(""); setPicks({}); onCancelReply(); }} /> : null}
      {suggestions.length > 0 && !slashOpen ? (
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
        {mediaConfig ? (
          <>
            <input ref={fileInput} type="file" multiple hidden aria-label={t("media.attach")} onChange={(event) => {
              const files = Array.from(event.target.files ?? []);
              event.target.value = "";
              void media.selectFiles(files);
            }} />
            <button type="button" className="icon-button" onClick={() => fileInput.current?.click()} disabled={busy || media.uploading || Boolean(disabledReason)} aria-label={t("media.attach")} title={t("media.attach")}><Icon name="plus" /></button>
            {mediaConfig.giphy_api_key ? <button type="button" className="button button--small button--ghost" disabled={busy || media.uploading || Boolean(disabledReason)} onClick={() => setGiphyOpen(true)} aria-label={t("media.giphy_title")}>GIF</button> : null}
          </>
        ) : null}
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
          disabled={busy || Boolean(disabledReason)}
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
        <button type="button" className="button button--primary composer__send" onClick={() => void submit()} disabled={busy || media.uploading || (!text.trim() && media.attachments.length === 0 && !media.giphyId) || Boolean(disabledReason)} aria-label={t("message.send")}>
          <Icon name="send" />
        </button>
      </div>
      {media.attachments.length > 0 || media.giphyId ? (
        <ul className="composer-attachments" aria-label={t("media.pending")}>
          {media.attachments.map((file) => <li key={file.id}><span>{file.filename} · {formatFileSize(file.size_bytes)} · {file.mime_type}</span><button type="button" className="icon-button" disabled={busy} onClick={() => media.remove(file.id)} aria-label={t("media.remove", { filename: file.filename })}><Icon name="close" size={16} /></button></li>)}
          {media.giphyId ? <li><span>{t("media.giphy_selected")}</span><button type="button" className="icon-button" disabled={busy} onClick={() => media.setGiphyId(null)} aria-label={t("media.remove_gif")}><Icon name="close" size={16} /></button></li> : null}
        </ul>
      ) : null}
      {media.progress ? <div className="composer-upload" role="status"><label htmlFor="attachment-progress">{t("media.uploading", { filename: media.progress.filename, percent: media.progress.percent })}</label><progress id="attachment-progress" max={100} value={media.progress.percent} /></div> : null}
      <div className="composer__meta">
        <span className="muted">{t("message.composer_hint")}</span>
        {mediaConfig ? <span className="muted">{t("media.limit", { size: formatFileSize(mediaConfig.max_attachment_bytes) })}</span> : null}
        {remaining < 200 ? <span className={remaining < 0 ? "form-error" : "muted"}>{remaining}</span> : null}
      </div>
      <ErrorText error={error} />
      <ErrorText error={media.error} />
      {giphyOpen && mediaConfig?.giphy_api_key ? <GiphyPicker apiKey={mediaConfig.giphy_api_key} onClose={() => setGiphyOpen(false)} onChoose={(id) => { media.setGiphyId(id); setGiphyOpen(false); }} /> : null}
    </div>
  );
}
