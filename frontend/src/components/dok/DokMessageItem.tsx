import { useTranslation } from "react-i18next";

import type { DokMessage } from "../../api/types";
import { roleLabel } from "../../utils/dok";
import { formatDateTime, formatTime } from "../../utils/format";
import { Icon } from "../Icon";
import { DokText } from "./DokText";

export function DokMessageItem({ message }: { message: DokMessage }) {
  const { t } = useTranslation();
  const label = roleLabel(t, message.author_role);
  const revealed = message.author && !message.mine ? message.author : null;
  return (
    <article className="message" data-id={message.id} tabIndex={0} aria-label={t("a11y.message_from", { name: label, time: formatDateTime(message.created_at) })}>
      <div className="message__row">
        <span className="message__avatar dok-avatar" aria-hidden="true">
          <Icon name="megaphone" size={20} />
        </span>
        <div className="message__main">
          <header className="message__head">
            <strong className="message__author">{label}</strong>
            <time dateTime={message.created_at}>{formatTime(message.created_at)}</time>
            {message.mine ? <span className="badge">{t("dok.sent_by_you")}</span> : null}
          </header>
          {revealed ? (
            <p className="dok-real-author">
              <Icon name="eye" size={14} /> {t("dok.real_author", { name: revealed.display_name, username: revealed.username })}
            </p>
          ) : null}
          <div className="message__content">
            <DokText content={message.content} />
          </div>
        </div>
      </div>
    </article>
  );
}
