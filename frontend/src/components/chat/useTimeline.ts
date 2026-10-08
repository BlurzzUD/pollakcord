import { useCallback, useEffect, useRef, useState } from "react";

import { api } from "../../api/client";
import type { HistoryPage, Id, Message } from "../../api/types";
import { realtime } from "../../realtime/socket";
import { useRealtimeEvent } from "../../realtime/useRealtimeEvent";
import { useAuth } from "../../store/auth";

export type Scope = "dm" | "channel";

interface ReactionEvent {
  message_id: Id;
  emoji: string;
  user_id: Id;
  present: boolean;
  channel_id?: Id;
  conversation_id?: Id;
}

export function useTimeline(scope: Scope, id: Id, onRead: () => void) {
  const base = scope === "dm" ? `/dms/${id}` : `/channels/${id}`;
  const meId = useAuth((state) => state.me?.id);
  const [messages, setMessages] = useState<Message[]>([]);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [error, setError] = useState<unknown>(null);
  const [hasMore, setHasMore] = useState(false);
  const [lastRead, setLastRead] = useState<Id | null>(null);
  const [loadingOlder, setLoadingOlder] = useState(false);
  const latestId = useRef<Id | null>(null);

  useEffect(() => {
    let cancelled = false;
    setMessages([]);
    setStatus("loading");
    setError(null);
    setLastRead(null);
    if (scope === "channel") {
      realtime.subscribeChannel(id);
    }
    api
      .get<HistoryPage>(`${base}/messages`, { limit: 50 })
      .then((page) => {
        if (cancelled) {
          return;
        }
        setMessages(page.messages);
        setHasMore(page.has_more);
        setLastRead(page.last_read_message_id);
        setStatus("ready");
      })
      .catch((failure: unknown) => {
        if (!cancelled) {
          setError(failure);
          setStatus("error");
        }
      });
    return () => {
      cancelled = true;
      if (scope === "channel") {
        realtime.unsubscribeChannel(id);
      }
    };
  }, [base, id, scope]);

  useEffect(() => {
    latestId.current = messages.at(-1)?.id ?? null;
  }, [messages]);

  const belongs = useCallback(
    (data: { channel_id?: Id | null; conversation_id?: Id | null }) => (scope === "dm" ? data.conversation_id === id : data.channel_id === id),
    [scope, id],
  );

  useRealtimeEvent<Message>("message.create", (message) => {
    if (!belongs(message)) {
      return;
    }
    setMessages((current) => (current.some((m) => m.id === message.id) ? current : [...current, message]));
    onRead();
  });

  useRealtimeEvent<{ id: Id; channel_id?: Id; conversation_id?: Id }>("message.delete", (event) => {
    if (!belongs(event)) {
      return;
    }
    setMessages((current) =>
      current.map((m) =>
        m.id === event.id ? { ...m, deleted: true, content: null, reactions: [], pinned: false } : m.reply_to?.id === event.id ? { ...m, reply_to: { ...m.reply_to, deleted: true, preview: null } } : m,
      ),
    );
  });

  useRealtimeEvent<ReactionEvent>("reaction.update", (event) => {
    if (!belongs(event)) {
      return;
    }
    setMessages((current) =>
      current.map((m) => {
        if (m.id !== event.message_id) {
          return m;
        }
        const existing = m.reactions.find((r) => r.emoji === event.emoji);
        const mine = event.user_id === meId;
        let reactions = m.reactions;
        if (existing) {
          const count = existing.count + (event.present ? 1 : -1);
          reactions = m.reactions
            .map((r) => (r.emoji === event.emoji ? { ...r, count, me: mine ? event.present : r.me } : r))
            .filter((r) => r.count > 0);
        } else if (event.present) {
          reactions = [...m.reactions, { emoji: event.emoji, count: 1, me: mine }];
        }
        return { ...m, reactions };
      }),
    );
  });

  useRealtimeEvent<{ id: Id; channel_id: Id; pinned: boolean }>("message.pin", (event) => {
    if (scope === "channel" && event.channel_id === id) {
      setMessages((current) => current.map((m) => (m.id === event.id ? { ...m, pinned: event.pinned } : m)));
    }
  });

  const loadOlder = useCallback(async () => {
    const first = messages[0];
    if (!first || loadingOlder) {
      return;
    }
    setLoadingOlder(true);
    try {
      const page = await api.get<HistoryPage>(`${base}/messages`, { limit: 50, before: first.id });
      setMessages((current) => [...page.messages, ...current]);
      setHasMore(page.has_more);
    } finally {
      setLoadingOlder(false);
    }
  }, [base, messages, loadingOlder]);

  const send = useCallback(
    async (content: string, replyTo: Id | null) => {
      const message = await api.post<Message>(`${base}/messages`, { content, reply_to_id: replyTo });
      setMessages((current) => (current.some((m) => m.id === message.id) ? current : [...current, message]));
    },
    [base],
  );

  const remove = useCallback((messageId: Id) => api.del(`${base}/messages/${messageId}`), [base]);

  const react = useCallback(
    (messageId: Id, emoji: string, present: boolean) =>
      present ? api.put(`${base}/messages/${messageId}/reactions`, { emoji }) : api.del(`${base}/messages/${messageId}/reactions`, undefined, { emoji }),
    [base],
  );

  const markRead = useCallback(async () => {
    const last = latestId.current;
    if (last) {
      await api.post(`${base}/read`, { message_id: last });
      setLastRead(last);
    }
  }, [base]);

  return { messages, status, error, hasMore, lastRead, loadingOlder, loadOlder, send, remove, react, markRead, base };
}
