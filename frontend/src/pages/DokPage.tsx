import { useTranslation } from "react-i18next";
import { Link, useNavigate } from "react-router-dom";

import { useDokInbox } from "../api/hooks";
import { DokComposer } from "../components/dok/DokComposer";
import { Icon } from "../components/Icon";
import { PageHeader } from "../components/PageHeader";
import { useAuth } from "../store/auth";
import { threadLabel } from "../utils/dok";
import { formatRelative } from "../utils/format";

export function DokPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const me = useAuth((state) => state.me);
  const inbox = useDokInbox();
  const data = inbox.data;
  const threads = data?.threads ?? [];
  return (
    <>
      <PageHeader title={t("dok.title")} lead={<Icon name="megaphone" />} />
      <div className="page">
        <p className="notice">{t("dok.anonymous_notice")}</p>
        {data && !data.send.allowed && me && !me.class_code ? <p className="notice">{t("dok.no_class_hint")}</p> : null}
        {data?.send.allowed ? (
          <section className="card" aria-labelledby="dok-compose">
            <header className="card__head">
              <h3 id="dok-compose">{t("dok.compose_title")}</h3>
            </header>
            <DokComposer targets={data.send.targets} onSent={(message) => navigate(`/app/dok/${message.thread_id}`)} />
          </section>
        ) : null}
        <section className="card" aria-labelledby="dok-threads">
          <header className="card__head">
            <h3 id="dok-threads">{t("dok.threads")}</h3>
          </header>
          {threads.length === 0 ? (
            <p className="muted">{t("dok.empty")}</p>
          ) : (
            <ul className="list">
              {threads.map((thread) => (
                <li key={thread.id}>
                  <Link className="list__item list__item--stack" to={`/app/dok/${thread.id}`}>
                    <span>
                      <strong>{threadLabel(t, thread)}</strong>
                      {thread.unread > 0 ? <span className="badge-count">{thread.unread}</span> : null}
                    </span>
                    <span className="muted">{thread.last_message?.preview}</span>
                    <time className="muted" dateTime={thread.last_message_at}>
                      {formatRelative(thread.last_message_at)}
                    </time>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </>
  );
}
