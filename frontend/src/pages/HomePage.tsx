import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Link, useNavigate } from "react-router-dom";

import { api } from "../api/client";
import { useDms, useFriends, useNotifications, useServers, useSuggestions } from "../api/hooks";
import type { Conversation } from "../api/types";
import { Avatar } from "../components/Avatar";
import { EmptyState } from "../components/EmptyState";
import { errorMessage } from "../components/ErrorText";
import { PageHeader } from "../components/PageHeader";
import { useAuth } from "../store/auth";
import { useLive } from "../store/live";
import { useUi } from "../store/ui";
import { formatRelative } from "../utils/format";
import { describeNotification } from "../utils/notifications";

export function HomePage() {
  const { t } = useTranslation();
  const me = useAuth((state) => state.me);
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const push = useUi((state) => state.push);
  const openProfile = useUi((state) => state.openProfile);
  const presence = useLive((state) => state.presence);
  const friends = useFriends();
  const dms = useDms();
  const servers = useServers();
  const notifications = useNotifications();
  const suggestions = useSuggestions();
  const startDm = useMutation({
    mutationFn: (userId: string) => api.post<Conversation>("/dms", { user_id: userId }),
    onSuccess: (conversation) => navigate(`/app/dm/${conversation.id}`),
    onError: (failure) => push("error", errorMessage(t, failure)),
  });
  const addFriend = useMutation({
    mutationFn: (username: string) => api.post("/friends/requests", { username }),
    onSuccess: () => {
      push("success", t("friends.request_sent"));
      void queryClient.invalidateQueries({ queryKey: ["suggestions"] });
    },
    onError: (failure) => push("error", errorMessage(t, failure)),
  });

  if (!me) {
    return null;
  }
  const online = (friends.data ?? []).filter((friend) => (presence[friend.id] ?? friend.presence) === "online");
  const classShared = me.settings.privacy.class_visibility !== "hidden" && me.class_code;

  return (
    <>
      <PageHeader title={t("nav.home")} />
      <div className="page">
        <section className="hero-greeting">
          <h2>{t("home.greeting", { name: me.display_name })}</h2>
          <p className="muted">{t("home.subtitle")}</p>
        </section>
        <div className="cards">
          <section className="card" aria-labelledby="card-friends">
            <header className="card__head">
              <h3 id="card-friends">{t("home.friends")}</h3>
              <Link to="/app/friends">{t("home.see_all")}</Link>
            </header>
            {online.length === 0 ? (
              <p className="muted">{friends.data?.length ? t("home.no_friends_online") : t("home.no_friends")}</p>
            ) : (
              <ul className="list">
                {online.slice(0, 6).map((friend) => (
                  <li key={friend.id} className="list__row">
                    <button type="button" className="list__item" onClick={() => openProfile(friend.id)}>
                      <Avatar name={friend.display_name} url={friend.avatar_url} size={32} presence="online" /> {friend.display_name}
                    </button>
                    <button type="button" className="button button--small" onClick={() => startDm.mutate(friend.id)}>
                      {t("profile.send_message")}
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </section>
          <section className="card" aria-labelledby="card-recent">
            <header className="card__head">
              <h3 id="card-recent">{t("home.recent")}</h3>
            </header>
            {(dms.data ?? []).length === 0 ? (
              <p className="muted">{t("home.no_conversations")}</p>
            ) : (
              <ul className="list">
                {(dms.data ?? []).slice(0, 5).map((conversation) => (
                  <li key={conversation.id}>
                    <Link className="list__item list__item--stack" to={`/app/dm/${conversation.id}`}>
                      <span>
                        <strong>{conversation.user.display_name}</strong>
                        {conversation.unread > 0 ? <span className="badge-count">{conversation.unread}</span> : null}
                      </span>
                      <span className="muted">{conversation.last_message?.content}</span>
                      {conversation.last_message_at ? <time className="muted" dateTime={conversation.last_message_at}>{formatRelative(conversation.last_message_at)}</time> : null}
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </section>
          <section className="card" aria-labelledby="card-servers">
            <header className="card__head">
              <h3 id="card-servers">{t("home.servers")}</h3>
            </header>
            {(servers.data ?? []).length === 0 ? (
              <p className="muted">{t("home.no_servers")}</p>
            ) : (
              <ul className="list">
                {(servers.data ?? []).slice(0, 6).map((server) => (
                  <li key={server.id}>
                    <Link className="list__item" to={`/app/server/${server.id}`}>
                      <Avatar name={server.name} url={server.icon_url} size={32} rounded={false} /> {server.name}
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </section>
          <section className="card" aria-labelledby="card-notifications">
            <header className="card__head">
              <h3 id="card-notifications">{t("home.notifications")}</h3>
            </header>
            {(notifications.data?.items ?? []).length === 0 ? (
              <p className="muted">{t("notifications.empty")}</p>
            ) : (
              <ul className="list">
                {(notifications.data?.items ?? []).slice(0, 5).map((item) => {
                  const described = describeNotification(t, item);
                  return (
                    <li key={item.id}>
                      {described.href ? (
                        <Link className={`list__item${item.read ? "" : " is-unread"}`} to={described.href}>
                          {described.text}
                        </Link>
                      ) : (
                        <span className={`list__item${item.read ? "" : " is-unread"}`}>{described.text}</span>
                      )}
                    </li>
                  );
                })}
              </ul>
            )}
          </section>
          <section className="card card--wide" aria-labelledby="card-suggestions">
            <header className="card__head">
              <h3 id="card-suggestions">{t("home.suggestions")}</h3>
            </header>
            {classShared ? (
              (suggestions.data ?? []).length === 0 ? (
                <p className="muted">{t("home.no_suggestions", { class: me.class_code })}</p>
              ) : (
                <ul className="suggestions">
                  {(suggestions.data ?? []).map((user) => (
                    <li key={user.id}>
                      <Avatar name={user.display_name} url={user.avatar_url} size={44} />
                      <div>
                        <strong>{user.display_name}</strong>
                        <span className="muted">
                          @{user.username} · {user.class_code}
                          {user.mutual_friends ? ` · ${t("home.mutual", { count: user.mutual_friends })}` : ""}
                        </span>
                      </div>
                      <button type="button" className="button button--small button--primary" onClick={() => addFriend.mutate(user.username)}>
                        {t("friends.add")}
                      </button>
                    </li>
                  ))}
                </ul>
              )
            ) : (
              <EmptyState icon="users" title={t("home.suggestions_off_title")}>
                {t("home.suggestions_off_text")} <Link to="/app/settings/account">{t("home.suggestions_off_link")}</Link>
              </EmptyState>
            )}
          </section>
        </div>
      </div>
    </>
  );
}
