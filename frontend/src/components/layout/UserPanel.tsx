import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { useNotifications } from "../../api/hooks";
import { useAuth } from "../../store/auth";
import { useLive } from "../../store/live";
import { isStaffRole } from "../../utils/roles";
import { Avatar } from "../Avatar";
import { CopyId } from "../CopyId";
import { Icon } from "../Icon";
import { NotificationsPanel } from "./NotificationsPanel";

export function UserPanel() {
  const { t } = useTranslation();
  const me = useAuth((state) => state.me);
  const connected = useLive((state) => state.connected);
  const notifications = useNotifications();
  const [open, setOpen] = useState(false);
  if (!me) {
    return null;
  }
  const unread = notifications.data?.unread ?? 0;
  return (
    <div className="user-panel">
      <Avatar name={me.display_name} url={me.avatar_url} size={36} presence={connected ? "online" : "offline"} />
      <div className="user-panel__names">
        <strong>{me.display_name}</strong>
        <span className="muted">@{me.username}</span>
        <CopyId value={me.id} label={t("developer.user_id")} />
      </div>
      <button type="button" className="icon-button icon-button--badge" onClick={() => setOpen(true)} aria-label={unread ? t("notifications.open_with_count", { count: unread }) : t("notifications.open")} title={t("notifications.title")}>
        <Icon name="bell" />
        {unread > 0 ? <span className="badge-dot">{unread > 9 ? "9+" : unread}</span> : null}
      </button>
      {isStaffRole(me.platform_role) ? (
        <Link className="icon-button" to="/app/moderation" aria-label={t("moderation.title")} title={t("moderation.title")}>
          <Icon name="gavel" />
        </Link>
      ) : null}
      <Link className="icon-button" to="/app/settings" aria-label={t("settings.title")} title={t("settings.title")}>
        <Icon name="settings" />
      </Link>
      {open ? <NotificationsPanel onClose={() => setOpen(false)} /> : null}
    </div>
  );
}
