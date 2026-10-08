import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";

import { api } from "../../api/client";
import type { Channel, Message, ServerSummary, UserCard } from "../../api/types";
import { useUi } from "../../store/ui";
import { Avatar } from "../Avatar";
import { EmptyState } from "../EmptyState";
import { errorMessage } from "../ErrorText";
import { Modal } from "../Modal";

interface SearchResult {
  friends: UserCard[];
  users: UserCard[];
  servers: ServerSummary[];
  channels: (Channel & { server_name: string })[];
  messages: { message: Message; where: { server_id?: string; server_name?: string; channel_id?: string; channel_name?: string; conversation_id?: string; user?: UserCard } }[];
}

export function SearchDialog({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const push = useUi((state) => state.push);
  const openProfile = useUi((state) => state.openProfile);
  const [text, setText] = useState("");
  const [debounced, setDebounced] = useState("");

  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(text.trim()), 300);
    return () => window.clearTimeout(timer);
  }, [text]);

  const results = useQuery({
    queryKey: ["search", debounced],
    queryFn: () => api.get<SearchResult>("/search", { q: debounced }),
    enabled: debounced.length >= 2,
  });
  const addFriend = useMutation({
    mutationFn: (username: string) => api.post("/friends/requests", { username }),
    onSuccess: () => {
      push("success", t("friends.request_sent"));
      void queryClient.invalidateQueries({ queryKey: ["friend-requests"] });
    },
    onError: (failure) => push("error", errorMessage(t, failure)),
  });
  const go = (path: string) => {
    onClose();
    navigate(path);
  };
  const data = results.data;
  const empty = data && !data.friends.length && !data.users.length && !data.servers.length && !data.channels.length && !data.messages.length;

  return (
    <Modal title={t("search.title")} onClose={onClose} wide>
      <div className="field">
        <label htmlFor="search-input">{t("search.label")}</label>
        <input id="search-input" type="search" value={text} onChange={(event) => setText(event.target.value)} placeholder={t("search.placeholder")} autoComplete="off" data-autofocus />
        <p className="field__hint">{t("search.hint")}</p>
      </div>
      {debounced.length < 2 ? null : results.isLoading ? <p role="status">{t("common.loading")}</p> : null}
      {empty ? <EmptyState icon="search" title={t("search.no_results")} /> : null}
      {data?.friends.length ? (
        <section aria-label={t("search.friends")}>
          <h3>{t("search.friends")}</h3>
          <ul className="list">
            {data.friends.map((user) => (
              <li key={user.id}>
                <button type="button" className="list__item" onClick={() => { onClose(); openProfile(user.id); }}>
                  <Avatar name={user.display_name} url={user.avatar_url} size={28} /> {user.display_name} <span className="muted">@{user.username}</span>
                </button>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
      {data?.users.length ? (
        <section aria-label={t("search.users")}>
          <h3>{t("search.users")}</h3>
          <ul className="list">
            {data.users.map((user) => (
              <li key={user.id} className="list__row">
                <button type="button" className="list__item" onClick={() => { onClose(); openProfile(user.id); }}>
                  <Avatar name={user.display_name} url={user.avatar_url} size={28} /> {user.display_name} <span className="muted">@{user.username}</span>
                </button>
                <button type="button" className="button button--small" onClick={() => addFriend.mutate(user.username)}>
                  {t("friends.add")}
                </button>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
      {data?.servers.length ? (
        <section aria-label={t("search.servers")}>
          <h3>{t("search.servers")}</h3>
          <ul className="list">
            {data.servers.map((server) => (
              <li key={server.id}>
                <button type="button" className="list__item" onClick={() => go(`/app/server/${server.id}`)}>
                  <Avatar name={server.name} url={server.icon_url} size={28} rounded={false} /> {server.name}
                </button>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
      {data?.channels.length ? (
        <section aria-label={t("search.channels")}>
          <h3>{t("search.channels")}</h3>
          <ul className="list">
            {data.channels.map((channel) => (
              <li key={channel.id}>
                <button type="button" className="list__item" onClick={() => go(`/app/server/${channel.server_id}/${channel.id}`)}>
                  {channel.type === "text" ? "# " : ""}
                  {channel.name} <span className="muted">{channel.server_name}</span>
                </button>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
      {data?.messages.length ? (
        <section aria-label={t("search.messages")}>
          <h3>{t("search.messages")}</h3>
          <ul className="list">
            {data.messages.map(({ message, where }) => (
              <li key={message.id}>
                <button
                  type="button"
                  className="list__item list__item--stack"
                  onClick={() => go(where.conversation_id ? `/app/dm/${where.conversation_id}` : `/app/server/${where.server_id}/${where.channel_id}`)}
                >
                  <span className="muted">
                    {where.conversation_id ? where.user?.display_name : `${where.server_name} · #${where.channel_name}`} — {message.author?.display_name}
                  </span>
                  <span>{message.content}</span>
                </button>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </Modal>
  );
}
