import { useTranslation } from "react-i18next";

import type { ClassSpaceMessage } from "../../api/types";
import { messageAuthorLabel } from "../../utils/classSpace";
import { formatDateTime, formatTime } from "../../utils/format";
import { Avatar } from "../Avatar";
import { Icon } from "../Icon";
import { ClassSpaceText } from "./ClassSpaceText";

interface ClassSpaceMessageItemProps {
  message: ClassSpaceMessage;
  onDelete: (message: ClassSpaceMessage) => void;
  onReport: (message: ClassSpaceMessage) => void;
}

export function ClassSpaceMessageItem({ message, onDelete, onReport }: ClassSpaceMessageItemProps) {
  const { t } = useTranslation();
  const label = messageAuthorLabel(t, message);
  return (
    <article className="message" data-id={message.id} tabIndex={0} aria-label={t("a11y.message_from", { name: label, time: formatDateTime(message.created_at) })}>
      <div className="message__row">
        {message.author ? (
          <span className="message__avatar" aria-hidden="true">
            <Avatar name={message.author.display_name} url={message.author.avatar_url} size={40} />
          </span>
        ) : (
          <span className="message__avatar class-space-avatar" aria-hidden="true">
            <Icon name="users" size={20} />
          </span>
        )}
        <div className="message__main">
          <header className="message__head">
            <strong className="message__author">{label}</strong>
            <time dateTime={message.created_at}>{formatTime(message.created_at)}</time>
          </header>
          <div className="message__content">
            <ClassSpaceText content={message.content} />
          </div>
        </div>
        <div className="message__tools" role="toolbar" aria-label={t("a11y.message_actions")}>
          {message.mine ? (
            <button type="button" className="icon-button icon-button--danger" onClick={() => onDelete(message)} aria-label={t("message.delete")} title={t("message.delete")}>
              <Icon name="trash" size={18} />
            </button>
          ) : (
            <button type="button" className="icon-button" onClick={() => onReport(message)} aria-label={t("message.report")} title={t("message.report")}>
              <Icon name="flag" size={18} />
            </button>
          )}
        </div>
      </div>
    </article>
  );
}
