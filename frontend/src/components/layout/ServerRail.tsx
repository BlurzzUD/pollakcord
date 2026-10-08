import { useState } from "react";
import { useTranslation } from "react-i18next";
import { NavLink } from "react-router-dom";

import { useDms, useServers } from "../../api/hooks";
import { Avatar } from "../Avatar";
import { Icon } from "../Icon";
import { CreateJoinServer } from "./CreateJoinServer";

export function ServerRail() {
  const { t } = useTranslation();
  const servers = useServers();
  const dms = useDms();
  const [adding, setAdding] = useState(false);
  const unreadDms = (dms.data ?? []).reduce((sum, conversation) => sum + conversation.unread, 0);
  return (
    <>
      <ul className="rail__list">
        <li>
          <NavLink to="/app" end className={({ isActive }) => `rail__item rail__home${isActive ? " is-active" : ""}`} aria-label={t("nav.home")} title={t("nav.home")}>
            <Icon name="home" size={24} />
            {unreadDms > 0 ? <span className="badge-dot">{unreadDms > 9 ? "9+" : unreadDms}</span> : null}
          </NavLink>
        </li>
        <li className="rail__divider" role="separator" />
        {(servers.data ?? []).map((server) => (
          <li key={server.id}>
            <NavLink to={`/app/server/${server.id}`} className={({ isActive }) => `rail__item${isActive ? " is-active" : ""}`} aria-label={server.name} title={server.name}>
              <Avatar name={server.name} url={server.icon_url} size={48} rounded={false} />
            </NavLink>
          </li>
        ))}
        <li>
          <button type="button" className="rail__item rail__add" onClick={() => setAdding(true)} aria-label={t("server.add")} title={t("server.add")}>
            <Icon name="plus" size={24} />
          </button>
        </li>
      </ul>
      {adding ? <CreateJoinServer onClose={() => setAdding(false)} /> : null}
    </>
  );
}
