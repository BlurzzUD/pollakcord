import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";

import { api } from "../../api/client";
import type { Conversation, Profile } from "../../api/types";
import { useAuth } from "../../store/auth";
import { useLive } from "../../store/live";
import { useUi } from "../../store/ui";
import { formatDate, formatRelative } from "../../utils/format";
import { Avatar } from "../Avatar";
import { CopyId } from "../CopyId";
import { errorMessage } from "../ErrorText";
import { Modal } from "../Modal";

export function ProfileModal() {
  const userId = useUi((state) => state.profileUserId);
  const close = useUi((state) => state.closeProfile);
  if (!userId) {
    return null;
  }
  return <ProfileContent userId={userId} onClose={close} />;
}

function ProfileContent({ userId, onClose }: { userId: string; onClose: () => void }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const push = useUi((state) => state.push);
  const meId = useAuth((state) => state.me?.id);
  const livePresence = useLive((state) => state.presence[userId]);
  const profile = useQuery({ queryKey: ["profile", userId], queryFn: () => api.get<Profile>(`/users/${userId}`), retry: false });
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ["profile", userId] });
    void queryClient.invalidateQueries({ queryKey: ["friends"] });
    void queryClient.invalidateQueries({ queryKey: ["friend-requests"] });
  };
  const act = useMutation({
    mutationFn: (action: () => Promise<unknown>) => action(),
    onSuccess: refresh,
    onError: (failure) => push("error", errorMessage(t, failure)),
  });
  const message = useMutation({
    mutationFn: () => api.post<Conversation>("/dms", { user_id: userId }),
    onSuccess: (conversation) => {
      onClose();
      navigate(`/app/dm/${conversation.id}`);
    },
    onError: (failure) => push("error", errorMessage(t, failure)),
  });

  const data = profile.data;
  const relation = data?.relation;
  const own = userId === meId;
  const presence = livePresence ?? data?.presence;
  return (
    <Modal title={data ? data.display_name : t("profile.title")} onClose={onClose}>
      {profile.isLoading ? <p role="status">{t("common.loading")}</p> : null}
      {profile.isError ? <p className="form-error" role="alert">{t("profile.unavailable")}</p> : null}
      {data ? (
        <div className="profile">
          <div className="profile__banner" style={data.banner_url ? { backgroundImage: `url(${data.banner_url})` } : data.accent_color ? { background: data.accent_color } : undefined} />
          <div className="profile__head">
            <Avatar name={data.display_name} url={data.avatar_url} size={84} presence={presence} />
            <div>
              <h3>
                {data.display_name} {data.staff ? <span className="badge">{t("common.staff")}</span> : null}
              </h3>
              <p className="muted">@{data.username}</p>
            </div>
          </div>
          {data.bio ? <p className="profile__bio">{data.bio}</p> : null}
          <dl className="profile__facts">
            <div>
              <dt>{t("profile.joined")}</dt>
              <dd>{formatDate(data.created_at)}</dd>
            </div>
            {data.class_code ? (
              <div>
                <dt>{t("profile.class")}</dt>
                <dd>{data.class_code}</dd>
              </div>
            ) : null}
            {presence ? (
              <div>
                <dt>{t("profile.status")}</dt>
                <dd>{t(`profile.presence_${presence}`)}</dd>
              </div>
            ) : null}
            {data.last_seen_at && presence !== "online" ? (
              <div>
                <dt>{t("profile.last_seen")}</dt>
                <dd>{formatRelative(data.last_seen_at)}</dd>
              </div>
            ) : null}
            {data.mutual_friends !== null && !own ? (
              <div>
                <dt>{t("profile.mutual_friends")}</dt>
                <dd>{data.mutual_friends}</dd>
              </div>
            ) : null}
          </dl>
          {data.shared_servers.length > 0 ? (
            <section>
              <h4>{t("profile.shared_servers")}</h4>
              <ul className="chips">
                {data.shared_servers.map((server) => (
                  <li key={server.id}>
                    <Avatar name={server.name} url={server.icon_url} size={20} rounded={false} /> {server.name}
                  </li>
                ))}
              </ul>
            </section>
          ) : null}
          <CopyId value={data.id} label={t("developer.user_id")} />
          {!own && relation ? (
            <div className="profile__actions">
              <button type="button" className="button button--primary" onClick={() => message.mutate()} disabled={relation.blocked}>
                {t("profile.send_message")}
              </button>
              {relation.friends ? (
                <button type="button" className="button button--ghost" onClick={() => act.mutate(() => api.del(`/friends/${userId}`))}>
                  {t("friends.remove")}
                </button>
              ) : relation.pending === "outgoing" ? (
                <span className="muted">{t("friends.pending")}</span>
              ) : (
                <button type="button" className="button button--ghost" onClick={() => act.mutate(() => api.post("/friends/requests", { user_id: userId }))}>
                  {relation.pending === "incoming" ? t("friends.accept") : t("friends.add")}
                </button>
              )}
              {relation.blocked ? (
                <button type="button" className="button button--ghost" onClick={() => act.mutate(() => api.del(`/blocks/${userId}`))}>
                  {t("friends.unblock")}
                </button>
              ) : (
                <button type="button" className="button button--danger-ghost" onClick={() => act.mutate(() => api.put(`/blocks/${userId}`))}>
                  {t("friends.block")}
                </button>
              )}
            </div>
          ) : null}
        </div>
      ) : null}
    </Modal>
  );
}
