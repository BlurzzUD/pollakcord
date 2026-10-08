import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { NavLink, useNavigate } from "react-router-dom";

import { api } from "../../api/client";
import { useMembers, useServer } from "../../api/hooks";
import type { Channel, ServerDetail } from "../../api/types";
import { useAuth } from "../../store/auth";
import { useLive } from "../../store/live";
import { useUi } from "../../store/ui";
import { can } from "../../utils/permissions";
import { useVoice } from "../../voice/useVoice";
import { Avatar } from "../Avatar";
import { ConfirmDialog } from "../ConfirmDialog";
import { CopyId } from "../CopyId";
import { errorMessage } from "../ErrorText";
import { Icon } from "../Icon";
import { ServerSettings } from "../../pages/server/ServerSettings";
import { InviteDialog } from "../../pages/server/InviteDialog";

export function ServerSidebar({ serverId }: { serverId: string }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const push = useUi((state) => state.push);
  const server = useServer(serverId);
  const members = useMembers(serverId);
  const liveVoice = useLive((state) => state.voiceStates);
  const joinChannel = useVoice((state) => state.joinChannel);
  const speaking = useVoice((state) => state.speaking);
  const meId = useAuth((state) => state.me?.id);
  const [menu, setMenu] = useState(false);
  const [settings, setSettings] = useState(false);
  const [inviting, setInviting] = useState(false);
  const [leaving, setLeaving] = useState(false);
  const leave = useMutation({
    mutationFn: () => api.post(`/servers/${serverId}/leave`),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["servers"] });
      navigate("/app");
    },
    onError: (failure) => push("error", errorMessage(t, failure)),
  });

  if (server.isError) {
    return <p className="sidebar__empty muted">{t("server.unavailable")}</p>;
  }
  const detail = server.data;
  if (!detail) {
    return <p className="sidebar__empty muted">{t("common.loading")}</p>;
  }
  const names: Record<string, string> = {};
  members.data?.members.forEach((member) => {
    names[member.user.id] = member.nickname ?? member.user.display_name;
  });
  const canManage = detail.is_owner || can(detail.my_permissions, "manage_server") || can(detail.my_permissions, "manage_channels") || can(detail.my_permissions, "manage_roles") || can(detail.my_permissions, "kick_members") || can(detail.my_permissions, "ban_members") || can(detail.my_permissions, "view_audit_log") || can(detail.my_permissions, "manage_messages");
  const canInvite = can(detail.my_permissions, "create_invite");

  const renderChannel = (channel: Channel) => {
    if (channel.type === "text") {
      const unread = detail.unread[channel.id] ?? 0;
      return (
        <li key={channel.id}>
          <NavLink to={`/app/server/${serverId}/${channel.id}`} className={({ isActive }) => `channel${isActive ? " is-active" : ""}${unread ? " has-unread" : ""}`}>
            <Icon name="hash" size={18} />
            <span className="channel__name">{channel.name}</span>
            {unread > 0 ? <span className="badge-count" aria-label={t("server.unread_count", { count: unread })}>{unread}</span> : null}
          </NavLink>
        </li>
      );
    }
    const participants = liveVoice[channel.id] ?? detail.voice_states[channel.id] ?? [];
    return (
      <li key={channel.id}>
        <NavLink
          to={`/app/server/${serverId}/${channel.id}`}
          className={({ isActive }) => `channel${isActive ? " is-active" : ""}`}
          onClick={() => joinChannel(channel.id)}
        >
          <Icon name="volume" size={18} />
          <span className="channel__name">{channel.name}</span>
          {channel.user_limit ? <span className="muted">{participants.length}/{channel.user_limit}</span> : null}
        </NavLink>
        {participants.length > 0 ? (
          <ul className="voice-users" aria-label={t("voice.in_channel", { name: channel.name })}>
            {participants.map((participant) => (
              <li key={participant.user_id} className={speaking[participant.user_id] ? "is-speaking" : ""}>
                <Avatar name={names[participant.user_id] ?? "?"} size={20} />
                <span>{names[participant.user_id] ?? t("message.unknown_user")}</span>
                {participant.muted || participant.server_muted ? <Icon name="micOff" size={14} label={t("voice.muted")} /> : null}
                {participant.user_id === meId ? <span className="muted">({t("common.you")})</span> : null}
              </li>
            ))}
          </ul>
        ) : null}
      </li>
    );
  };

  const uncategorized = detail.channels.filter((channel) => !channel.category_id || !detail.categories.some((category) => category.id === channel.category_id));
  return (
    <div className="sidebar__scroll">
      <div className="server-head">
        <button type="button" className="server-head__button" aria-expanded={menu} aria-haspopup="menu" onClick={() => setMenu((open) => !open)}>
          <strong>{detail.name}</strong>
          <Icon name="chevronDown" size={18} />
        </button>
        {menu ? (
          <div className="menu" role="menu" onMouseLeave={() => setMenu(false)}>
            {canInvite ? (
              <button type="button" role="menuitem" onClick={() => { setMenu(false); setInviting(true); }}>
                <Icon name="userPlus" size={18} /> {t("server.invite_people")}
              </button>
            ) : null}
            {canManage ? (
              <button type="button" role="menuitem" onClick={() => { setMenu(false); setSettings(true); }}>
                <Icon name="settings" size={18} /> {t("server.settings")}
              </button>
            ) : null}
            {!detail.is_owner ? (
              <button type="button" role="menuitem" className="is-danger" onClick={() => { setMenu(false); setLeaving(true); }}>
                <Icon name="logout" size={18} /> {t("server.leave")}
              </button>
            ) : null}
            <div className="menu__ids">
              <CopyId value={detail.id} label={t("developer.server_id")} />
            </div>
          </div>
        ) : null}
      </div>
      <ul className="channel-list">{uncategorized.map(renderChannel)}</ul>
      {detail.categories.map((category) => {
        const channels = detail.channels.filter((channel) => channel.category_id === category.id);
        return (
          <section key={category.id} aria-label={category.name}>
            <h2 className="sidebar__heading">{category.name}</h2>
            <ul className="channel-list">{channels.map(renderChannel)}</ul>
          </section>
        );
      })}
      {settings ? <ServerSettings server={detail} onClose={() => setSettings(false)} /> : null}
      {inviting ? <InviteDialog server={detail as ServerDetail} onClose={() => setInviting(false)} /> : null}
      {leaving ? (
        <ConfirmDialog
          title={t("server.leave")}
          message={t("server.leave_confirm", { name: detail.name })}
          confirmLabel={t("server.leave")}
          danger
          onCancel={() => setLeaving(false)}
          onConfirm={() => leave.mutate()}
          busy={leave.isPending}
        />
      ) : null}
    </div>
  );
}
