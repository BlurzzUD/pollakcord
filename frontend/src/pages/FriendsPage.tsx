import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";

import { api } from "../api/client";
import { useFriendRequests, useFriends } from "../api/hooks";
import type { Conversation, UserCard } from "../api/types";
import { Avatar } from "../components/Avatar";
import { EmptyState } from "../components/EmptyState";
import { ErrorText, errorMessage } from "../components/ErrorText";
import { TextField } from "../components/Field";
import { PageHeader } from "../components/PageHeader";
import { useQuery } from "@tanstack/react-query";
import { useLive } from "../store/live";
import { useUi } from "../store/ui";

type Tab = "online" | "all" | "pending" | "blocked" | "add";
const TABS: Tab[] = ["online", "all", "pending", "blocked", "add"];

export function FriendsPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const push = useUi((state) => state.push);
  const openProfile = useUi((state) => state.openProfile);
  const presence = useLive((state) => state.presence);
  const [tab, setTab] = useState<Tab>("online");
  const [username, setUsername] = useState("");
  const friends = useFriends();
  const requests = useFriendRequests();
  const blocked = useQuery({ queryKey: ["blocks"], queryFn: () => api.get<UserCard[]>("/blocks") });

  const refresh = () => {
    for (const key of ["friends", "friend-requests", "blocks", "suggestions"]) {
      void queryClient.invalidateQueries({ queryKey: [key] });
    }
  };
  const run = useMutation({
    mutationFn: (action: () => Promise<unknown>) => action(),
    onSuccess: refresh,
    onError: (failure) => push("error", errorMessage(t, failure)),
  });
  const startDm = useMutation({
    mutationFn: (userId: string) => api.post<Conversation>("/dms", { user_id: userId }),
    onSuccess: (conversation) => navigate(`/app/dm/${conversation.id}`),
    onError: (failure) => push("error", errorMessage(t, failure)),
  });
  const add = useMutation({
    mutationFn: () => api.post<{ status: string }>("/friends/requests", { username: username.trim().replace(/^@/, "") }),
    onSuccess: (result) => {
      push("success", result.status === "accepted" ? t("friends.now_friends") : t("friends.request_sent"));
      setUsername("");
      refresh();
    },
  });

  const status = (user: UserCard) => presence[user.id] ?? user.presence;
  const list = (friends.data ?? []).filter((friend) => tab !== "online" || status(friend) === "online");
  const incoming = requests.data?.incoming ?? [];
  const outgoing = requests.data?.outgoing ?? [];

  return (
    <>
      <PageHeader title={t("nav.friends")} />
      <div className="page">
        <div className="tabs" role="tablist" aria-label={t("friends.tabs")}>
          {TABS.map((value) => (
            <button key={value} type="button" role="tab" aria-selected={tab === value} className={tab === value ? "is-active" : ""} onClick={() => setTab(value)}>
              {t(`friends.tab_${value}`)}
              {value === "pending" && incoming.length > 0 ? <span className="badge-count">{incoming.length}</span> : null}
            </button>
          ))}
        </div>
        {tab === "add" ? (
          <form
            className="inline-form"
            onSubmit={(event) => {
              event.preventDefault();
              add.mutate();
            }}
          >
            <TextField label={t("friends.add_by_username")} hint={t("friends.add_hint")} value={username} onChange={(event) => setUsername(event.target.value)} autoCapitalize="none" spellCheck={false} />
            <button type="submit" className="button button--primary" disabled={add.isPending || !username.trim()}>
              {t("friends.send_request")}
            </button>
            <ErrorText error={add.error} />
          </form>
        ) : null}
        {tab === "online" || tab === "all" ? (
          list.length === 0 ? (
            <EmptyState icon="users" title={tab === "online" ? t("friends.none_online") : t("friends.none")} />
          ) : (
            <ul className="people">
              {list.map((friend) => (
                <li key={friend.id}>
                  <button type="button" className="people__main" onClick={() => openProfile(friend.id)}>
                    <Avatar name={friend.display_name} url={friend.avatar_url} size={44} presence={status(friend)} />
                    <span>
                      <strong>{friend.display_name}</strong>
                      <span className="muted">@{friend.username}</span>
                    </span>
                  </button>
                  <button type="button" className="button button--small" onClick={() => startDm.mutate(friend.id)}>
                    {t("profile.send_message")}
                  </button>
                  <button type="button" className="button button--small button--ghost" onClick={() => run.mutate(() => api.del(`/friends/${friend.id}`))}>
                    {t("friends.remove")}
                  </button>
                </li>
              ))}
            </ul>
          )
        ) : null}
        {tab === "pending" ? (
          <>
            <h2>{t("friends.incoming")}</h2>
            {incoming.length === 0 ? <p className="muted">{t("friends.no_incoming")}</p> : null}
            <ul className="people">
              {incoming.map((entry) => (
                <li key={entry.id}>
                  <button type="button" className="people__main" onClick={() => openProfile(entry.user.id)}>
                    <Avatar name={entry.user.display_name} url={entry.user.avatar_url} size={44} />
                    <span>
                      <strong>{entry.user.display_name}</strong>
                      <span className="muted">@{entry.user.username}</span>
                    </span>
                  </button>
                  <button type="button" className="button button--small button--primary" onClick={() => run.mutate(() => api.post(`/friends/requests/${entry.id}/accept`))}>
                    {t("friends.accept")}
                  </button>
                  <button type="button" className="button button--small button--ghost" onClick={() => run.mutate(() => api.post(`/friends/requests/${entry.id}/decline`))}>
                    {t("friends.decline")}
                  </button>
                </li>
              ))}
            </ul>
            <h2>{t("friends.outgoing")}</h2>
            {outgoing.length === 0 ? <p className="muted">{t("friends.no_outgoing")}</p> : null}
            <ul className="people">
              {outgoing.map((entry) => (
                <li key={entry.id}>
                  <span className="people__main">
                    <Avatar name={entry.user.display_name} url={entry.user.avatar_url} size={44} />
                    <span>
                      <strong>{entry.user.display_name}</strong>
                      <span className="muted">@{entry.user.username}</span>
                    </span>
                  </span>
                  <button type="button" className="button button--small button--ghost" onClick={() => run.mutate(() => api.del(`/friends/requests/${entry.id}`))}>
                    {t("friends.cancel_request")}
                  </button>
                </li>
              ))}
            </ul>
          </>
        ) : null}
        {tab === "blocked" ? (
          (blocked.data ?? []).length === 0 ? (
            <EmptyState icon="block" title={t("friends.none_blocked")} />
          ) : (
            <ul className="people">
              {(blocked.data ?? []).map((user) => (
                <li key={user.id}>
                  <span className="people__main">
                    <Avatar name={user.display_name} url={user.avatar_url} size={44} />
                    <span>
                      <strong>{user.display_name}</strong>
                      <span className="muted">@{user.username}</span>
                    </span>
                  </span>
                  <button type="button" className="button button--small" onClick={() => run.mutate(() => api.del(`/blocks/${user.id}`))}>
                    {t("friends.unblock")}
                  </button>
                </li>
              ))}
            </ul>
          )
        ) : null}
      </div>
    </>
  );
}
