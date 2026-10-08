import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Navigate, useParams } from "react-router-dom";

import { useMembers, useServer } from "../../api/hooks";
import { MessageTimeline } from "../../components/chat/MessageTimeline";
import type { MentionCandidate } from "../../components/chat/Composer";
import { CopyId } from "../../components/CopyId";
import { EmptyState, Spinner } from "../../components/EmptyState";
import { Icon } from "../../components/Icon";
import { PageHeader } from "../../components/PageHeader";
import { useAuth } from "../../store/auth";
import { useLive } from "../../store/live";
import { useUi } from "../../store/ui";
import { can } from "../../utils/permissions";
import { MemberList } from "./MemberList";
import { PinnedModal } from "./PinnedModal";
import { VoiceRoomView } from "./VoiceRoomView";

export function ServerPage() {
  const { t } = useTranslation();
  const { serverId = "", channelId } = useParams();
  const me = useAuth((state) => state.me);
  const server = useServer(serverId);
  const members = useMembers(serverId);
  const seed = useLive((state) => state.seedVoiceStates);
  const membersOpen = useUi((state) => state.membersOpen);
  const toggleMembers = useUi((state) => state.toggleMembers);
  const [pinsOpen, setPinsOpen] = useState(false);
  const detail = server.data;

  useEffect(() => {
    if (detail) {
      seed(detail.voice_states);
    }
  }, [detail, seed]);

  if (server.isError) {
    return (
      <>
        <PageHeader title={t("server.unavailable")} />
        <EmptyState icon="warning" title={t("server.unavailable")} />
      </>
    );
  }
  if (!detail || !me) {
    return <Spinner label={t("common.loading")} />;
  }
  const channel = detail.channels.find((item) => item.id === channelId);
  if (!channelId) {
    const first = detail.channels.find((item) => item.type === "text") ?? detail.channels[0];
    if (first) {
      return <Navigate to={`/app/server/${serverId}/${first.id}`} replace />;
    }
    return (
      <>
        <PageHeader title={detail.name} />
        <EmptyState icon="hash" title={t("server.no_channels")} />
      </>
    );
  }
  if (!channel) {
    return (
      <>
        <PageHeader title={detail.name} />
        <EmptyState icon="warning" title={t("channel.unavailable")} />
      </>
    );
  }

  const memberList = members.data?.members ?? [];
  const names: Record<string, string> = {};
  const candidates: MentionCandidate[] = [];
  for (const member of memberList) {
    const name = member.nickname ?? member.user.display_name;
    names[member.user.id] = name;
    if (member.user.id !== me.id) {
      candidates.push({ id: member.user.id, name, avatarUrl: member.user.avatar_url });
    }
  }
  const mine = memberList.find((member) => member.user.id === me.id);
  const timedOut = Boolean(mine?.timeout_until);
  const canSend = can(channel.my_permissions, "send_messages") && !timedOut;
  const blockedReason = timedOut ? t("server.timeout_notice") : !can(channel.my_permissions, "send_messages") ? t("channel.no_send_permission") : null;

  return (
    <>
      <PageHeader title={channel.name} lead={<Icon name={channel.type === "text" ? "hash" : "volume"} />}>
        {channel.topic ? <span className="page-header__topic muted">{channel.topic}</span> : null}
        <CopyId value={channel.id} label={t("developer.channel_id")} />
        {channel.type === "text" ? (
          <button type="button" className="icon-button" onClick={() => setPinsOpen(true)} aria-label={t("channel.pinned")} title={t("channel.pinned")}>
            <Icon name="pin" />
          </button>
        ) : null}
        <button type="button" className="icon-button" onClick={toggleMembers} aria-pressed={membersOpen} aria-label={t("server.toggle_members")} title={t("server.toggle_members")}>
          <Icon name="users" />
        </button>
      </PageHeader>
      <div className={`server-body${membersOpen ? " has-members" : ""}`}>
        <section className="server-body__main">
          {channel.type === "text" ? (
            <MessageTimeline
              key={channel.id}
              scope="channel"
              id={channel.id}
              serverId={serverId}
              names={names}
              candidates={candidates}
              placeholder={t("channel.placeholder", { name: channel.name })}
              canSend={canSend}
              sendBlockedReason={blockedReason}
              canReact={can(channel.my_permissions, "add_reactions")}
              canModerate={can(channel.my_permissions, "manage_messages")}
              allowEscalate={detail.moderation_settings.reports_enabled}
            />
          ) : (
            <VoiceRoomView channel={channel} server={detail} members={memberList} />
          )}
        </section>
        {membersOpen ? <MemberList server={detail} members={memberList} /> : null}
      </div>
      {pinsOpen ? <PinnedModal channelId={channel.id} onClose={() => setPinsOpen(false)} /> : null}
    </>
  );
}
