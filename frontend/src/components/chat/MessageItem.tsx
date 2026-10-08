import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { Message } from "../../api/types";
import { useAuth } from "../../store/auth";
import { useUi } from "../../store/ui";
import { formatDateTime, formatTime } from "../../utils/format";
import { Avatar } from "../Avatar";
import { CopyId } from "../CopyId";
import { Icon } from "../Icon";
import { RichText } from "./RichText";

interface MessageItemProps {
  message: Message;
  compact: boolean;
  names: Record<string, string>;
  reactions: string[];
  canReact: boolean;
  canDelete: boolean;
  canPin: boolean;
  canReport: boolean;
  onReply: (message: Message) => void;
  onReact: (message: Message, emoji: string, present: boolean) => void;
  onDelete: (message: Message) => void;
  onPin: (message: Message) => void;
  onReport: (message: Message) => void;
}

export function MessageItem(props: MessageItemProps) {
  const { message, compact, names, reactions, canReact, canDelete, canPin, canReport } = props;
  const { t } = useTranslation();
  const meId = useAuth((state) => state.me?.id);
  const openProfile = useUi((state) => state.openProfile);
  const [picker, setPicker] = useState(false);
  const author = message.author;
  const displayName = author ? (author.nickname ?? author.display_name) : t("message.deleted_user");
  const mine = author?.id === meId;
  const mentionsMe = !message.deleted && message.content?.includes(`<@${meId}>`);

  if (message.deleted) {
    return (
      <article className="message message--deleted" data-id={message.id}>
        <span className="muted">{t("message.deleted")}</span>
      </article>
    );
  }

  return (
    <article className={`message${compact ? " message--compact" : ""}${mentionsMe ? " message--mention" : ""}`} data-id={message.id} tabIndex={0} aria-label={t("a11y.message_from", { name: displayName, time: formatDateTime(message.created_at) })}>
      {message.reply_to ? (
        <div className="message__reply">
          <Icon name="reply" size={14} />
          {message.reply_to.deleted ? (
            <span className="muted">{t("message.reply_deleted")}</span>
          ) : (
            <span>
              <strong>{names[message.reply_to.author_id ?? ""] ?? t("message.unknown_user")}</strong> {message.reply_to.preview}
            </span>
          )}
        </div>
      ) : null}
      <div className="message__row">
        {compact ? (
          <time className="message__gutter" dateTime={message.created_at}>
            {formatTime(message.created_at)}
          </time>
        ) : (
          <button type="button" className="message__avatar" onClick={() => author && openProfile(author.id)} aria-label={t("a11y.open_profile", { name: displayName })}>
            <Avatar name={displayName} url={author?.avatar_url} size={40} />
          </button>
        )}
        <div className="message__main">
          {compact ? null : (
            <header className="message__head">
              <button type="button" className="message__author" onClick={() => author && openProfile(author.id)}>
                {displayName}
              </button>
              {author?.staff ? <span className="badge">{t("common.staff")}</span> : null}
              <time dateTime={message.created_at}>{formatTime(message.created_at)}</time>
              {message.pinned ? <Icon name="pin" size={14} label={t("message.pinned")} /> : null}
              {author ? <CopyId value={message.id} label={t("developer.message_id")} /> : null}
            </header>
          )}
          <div className="message__content">
            <RichText content={message.content ?? ""} names={names} />
          </div>
          {message.reactions.length > 0 ? (
            <div className="message__reactions">
              {message.reactions.map((reaction) => (
                <button
                  key={reaction.emoji}
                  type="button"
                  className={`reaction${reaction.me ? " is-mine" : ""}`}
                  aria-pressed={reaction.me}
                  aria-label={t("message.reaction_label", { emoji: reaction.emoji, count: reaction.count })}
                  disabled={!canReact}
                  onClick={() => props.onReact(message, reaction.emoji, !reaction.me)}
                >
                  <span aria-hidden="true">{reaction.emoji}</span> {reaction.count}
                </button>
              ))}
            </div>
          ) : null}
        </div>
        <div className="message__tools" role="toolbar" aria-label={t("a11y.message_actions")}>
          {canReact ? (
            <div className="message__picker">
              <button type="button" className="icon-button" onClick={() => setPicker((open) => !open)} aria-expanded={picker} aria-label={t("message.add_reaction")} title={t("message.add_reaction")}>
                <Icon name="smile" size={18} />
              </button>
              {picker ? (
                <div className="emoji-picker" role="menu">
                  {reactions.map((emoji) => (
                    <button
                      key={emoji}
                      type="button"
                      role="menuitem"
                      onClick={() => {
                        setPicker(false);
                        props.onReact(message, emoji, !message.reactions.find((r) => r.emoji === emoji)?.me);
                      }}
                    >
                      {emoji}
                    </button>
                  ))}
                </div>
              ) : null}
            </div>
          ) : null}
          <button type="button" className="icon-button" onClick={() => props.onReply(message)} aria-label={t("message.reply")} title={t("message.reply")}>
            <Icon name="reply" size={18} />
          </button>
          {canPin ? (
            <button type="button" className="icon-button" onClick={() => props.onPin(message)} aria-label={message.pinned ? t("message.unpin") : t("message.pin")} title={message.pinned ? t("message.unpin") : t("message.pin")}>
              <Icon name="pin" size={18} />
            </button>
          ) : null}
          {canReport && !mine ? (
            <button type="button" className="icon-button" onClick={() => props.onReport(message)} aria-label={t("message.report")} title={t("message.report")}>
              <Icon name="flag" size={18} />
            </button>
          ) : null}
          {mine || canDelete ? (
            <button type="button" className="icon-button icon-button--danger" onClick={() => props.onDelete(message)} aria-label={t("message.delete")} title={t("message.delete")}>
              <Icon name="trash" size={18} />
            </button>
          ) : null}
        </div>
      </div>
    </article>
  );
}
