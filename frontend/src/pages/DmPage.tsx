import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { useParams } from "react-router-dom";

import { api } from "../api/client";
import type { Conversation } from "../api/types";
import { Avatar } from "../components/Avatar";
import { MessageTimeline } from "../components/chat/MessageTimeline";
import { CopyId } from "../components/CopyId";
import { EmptyState } from "../components/EmptyState";
import { Icon } from "../components/Icon";
import { PageHeader } from "../components/PageHeader";
import { useAuth } from "../store/auth";
import { useLive } from "../store/live";
import { useUi } from "../store/ui";
import { useVoice } from "../voice/useVoice";

export function DmPage() {
  const { t } = useTranslation();
  const { conversationId = "" } = useParams();
  const me = useAuth((state) => state.me);
  const openProfile = useUi((state) => state.openProfile);
  const startCall = useVoice((state) => state.startCall);
  const inCall = useVoice((state) => Boolean(state.room || state.ringing));
  const conversation = useQuery({ queryKey: ["dm", conversationId], queryFn: () => api.get<Conversation>(`/dms/${conversationId}`), retry: false });
  const livePresence = useLive((state) => (conversation.data ? state.presence[conversation.data.user.id] : undefined));

  if (conversation.isError) {
    return (
      <>
        <PageHeader title={t("dm.unavailable")} />
        <EmptyState icon="warning" title={t("dm.unavailable")} />
      </>
    );
  }
  const other = conversation.data?.user;
  if (!other || !me) {
    return <PageHeader title={t("common.loading")} />;
  }
  const names = { [me.id]: me.display_name, [other.id]: other.display_name };
  return (
    <>
      <PageHeader title={other.display_name} lead={<Avatar name={other.display_name} url={other.avatar_url} size={32} presence={livePresence ?? conversation.data?.presence} />}>
        <CopyId value={conversationId} label={t("developer.conversation_id")} />
        <button type="button" className="icon-button" onClick={() => startCall(conversationId)} disabled={inCall} aria-label={t("voice.start_call")} title={t("voice.start_call")}>
          <Icon name="phone" />
        </button>
        <button type="button" className="icon-button" onClick={() => openProfile(other.id)} aria-label={t("profile.title")} title={t("profile.title")}>
          <Icon name="users" />
        </button>
      </PageHeader>
      <MessageTimeline
        scope="dm"
        id={conversationId}
        names={names}
        candidates={[]}
        placeholder={t("dm.placeholder", { name: other.display_name })}
        canSend
        canReact
        canModerate={false}
        allowEscalate={false}
      />
    </>
  );
}
