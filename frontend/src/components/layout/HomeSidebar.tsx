import { useState } from "react";
import { useTranslation } from "react-i18next";
import { NavLink } from "react-router-dom";

import { useDms, useDokInbox, useFriendRequests } from "../../api/hooks";
import { useLive } from "../../store/live";
import { threadLabel } from "../../utils/dok";
import { Avatar } from "../Avatar";
import { Icon } from "../Icon";
import { SearchDialog } from "./SearchDialog";

export function HomeSidebar() {
  const { t } = useTranslation();
  const dms = useDms();
  const requests = useFriendRequests();
  const dok = useDokInbox();
  const presence = useLive((state) => state.presence);
  const [searching, setSearching] = useState(false);
  const pending = requests.data?.incoming.length ?? 0;
  const dokThreads = dok.data?.threads ?? [];
  const dokUnread = dok.data?.unread ?? 0;
  return (
    <div className="sidebar__scroll">
      <button type="button" className="search-button" onClick={() => setSearching(true)}>
        <Icon name="search" size={18} />
        <span>{t("search.placeholder")}</span>
      </button>
      <nav aria-label={t("a11y.home_navigation")}>
        <NavLink to="/app" end className={({ isActive }) => `nav-item${isActive ? " is-active" : ""}`}>
          <Icon name="home" /> {t("nav.home")}
        </NavLink>
        <NavLink to="/app/friends" className={({ isActive }) => `nav-item${isActive ? " is-active" : ""}`}>
          <Icon name="users" /> {t("nav.friends")}
          {pending > 0 ? <span className="badge-count">{pending}</span> : null}
        </NavLink>
        <NavLink to="/app/dok" end className={({ isActive }) => `nav-item${isActive ? " is-active" : ""}`}>
          <Icon name="megaphone" /> {t("nav.dok")}
          {dokUnread > 0 ? <span className="badge-count">{dokUnread}</span> : null}
        </NavLink>
      </nav>
      {dokThreads.length > 0 ? (
        <>
          <h2 className="sidebar__heading">{t("dok.threads")}</h2>
          <ul className="dm-list">
            {dokThreads.map((thread) => (
              <li key={thread.id}>
                <NavLink to={`/app/dok/${thread.id}`} className={({ isActive }) => `dm-item${isActive ? " is-active" : ""}`}>
                  <span className="dok-avatar" aria-hidden="true">
                    <Icon name="megaphone" size={18} />
                  </span>
                  <span className="dm-item__text">
                    <strong>{threadLabel(t, thread)}</strong>
                    <span className="muted">{thread.last_message?.preview ?? ""}</span>
                  </span>
                  {thread.unread > 0 ? <span className="badge-count">{thread.unread}</span> : null}
                </NavLink>
              </li>
            ))}
          </ul>
        </>
      ) : null}
      <h2 className="sidebar__heading">{t("nav.direct_messages")}</h2>
      <ul className="dm-list">
        {(dms.data ?? []).map((conversation) => (
          <li key={conversation.id}>
            <NavLink to={`/app/dm/${conversation.id}`} className={({ isActive }) => `dm-item${isActive ? " is-active" : ""}`}>
              <Avatar name={conversation.user.display_name} url={conversation.user.avatar_url} size={36} presence={presence[conversation.user.id] ?? conversation.presence} />
              <span className="dm-item__text">
                <strong>{conversation.user.display_name}</strong>
                <span className="muted">{conversation.last_message?.content ?? ""}</span>
              </span>
              {conversation.unread > 0 ? <span className="badge-count">{conversation.unread}</span> : null}
            </NavLink>
          </li>
        ))}
        {dms.data?.length === 0 ? <li className="muted sidebar__empty">{t("nav.no_conversations")}</li> : null}
      </ul>
      {searching ? <SearchDialog onClose={() => setSearching(false)} /> : null}
    </div>
  );
}
