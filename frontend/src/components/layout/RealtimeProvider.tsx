import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { useLocation, useNavigate } from "react-router-dom";

import type { AppNotification, Id, ServerDetail, UserCard } from "../../api/types";
import { realtime } from "../../realtime/socket";
import { useRealtimeEvent } from "../../realtime/useRealtimeEvent";
import { useAuth } from "../../store/auth";
import { useLive } from "../../store/live";
import { useUi } from "../../store/ui";
import { initVoiceController } from "../../voice/useVoice";
import { describeNotification } from "../../utils/notifications";
import { playPing } from "../../utils/sound";

const SERVER_EVENTS = ["server.joined", "server.updated", "structure.changed", "member.joined", "member.left", "member.updated", "role.changed"];

export function RealtimeProvider({ children }: { children: ReactNode }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const location = useLocation();
  const me = useAuth((state) => state.me);
  const reload = useAuth((state) => state.load);
  const push = useUi((state) => state.push);
  const path = useRef(location.pathname);
  const timers = useRef(new Map<string, number>());
  path.current = location.pathname;

  const invalidateSoon = (key: unknown[]) => {
    const id = JSON.stringify(key);
    window.clearTimeout(timers.current.get(id));
    timers.current.set(
      id,
      window.setTimeout(() => {
        timers.current.delete(id);
        void queryClient.invalidateQueries({ queryKey: key });
      }, 250),
    );
  };

  useEffect(() => {
    realtime.connect();
    const stopVoice = initVoiceController();
    const pending = timers.current;
    return () => {
      stopVoice();
      realtime.disconnect();
      pending.forEach((timer) => window.clearTimeout(timer));
    };
  }, []);

  useRealtimeEvent("socket.open", () => {
    useLive.getState().setConnected(true);
    void queryClient.invalidateQueries();
  });
  useRealtimeEvent("socket.close", () => useLive.getState().setConnected(false));
  useRealtimeEvent("unauthorized", () => void reload());

  useRealtimeEvent<{ user_id: Id; status: "online" | "offline" }>("presence.update", (event) => {
    useLive.getState().setPresence(event.user_id, event.status);
  });

  useRealtimeEvent<{ scope: "dm" | "channel"; id: Id; user_id: Id }>("typing", (event) => {
    useLive.getState().markTyping(`${event.scope}:${event.id}`, event.user_id);
  });

  useRealtimeEvent<{ scope: "dm" | "channel"; channel_id: Id | null; conversation_id: Id | null; author: UserCard | null }>("message.create", (event) => {
    const key = event.scope === "dm" ? `dm:${event.conversation_id}` : `channel:${event.channel_id}`;
    if (event.author) {
      useLive.getState().clearTyping(key, event.author.id);
    }
    if (event.scope === "dm") {
      invalidateSoon(["dms"]);
    }
  });

  useRealtimeEvent<{ server_id: Id; channel_id: Id; author_id: Id }>("channel.activity", (event) => {
    if (event.author_id === me?.id || path.current.includes(`/server/${event.server_id}/${event.channel_id}`)) {
      return;
    }
    queryClient.setQueryData<ServerDetail>(["server", event.server_id], (old) =>
      old ? { ...old, unread: { ...old.unread, [event.channel_id]: (old.unread[event.channel_id] ?? 0) + 1 } } : old,
    );
  });

  useRealtimeEvent("read.update", () => {
    invalidateSoon(["dms"]);
  });

  useRealtimeEvent("read.peer", () => undefined);

  useRealtimeEvent<AppNotification>("notification.create", (notification) => {
    invalidateSoon(["notifications"]);
    const viewing = notification.type === "dm" && path.current.endsWith(`/dm/${notification.payload.conversation_id}`);
    if (viewing) {
      return;
    }
    push("info", describeNotification(t, notification).text);
    if (me?.settings.notification_prefs.sounds) {
      playPing();
    }
  });

  for (const event of ["friend.request", "friend.added", "friend.removed"]) {
    useRealtimeEvent(event, () => {
      invalidateSoon(["friends"]);
      invalidateSoon(["friend-requests"]);
      invalidateSoon(["suggestions"]);
    });
  }

  for (const event of SERVER_EVENTS) {
    useRealtimeEvent<{ server_id?: Id }>(event, (data) => {
      invalidateSoon(["servers"]);
      if (data.server_id) {
        invalidateSoon(["server", data.server_id]);
        invalidateSoon(["members", data.server_id]);
      }
    });
  }

  useRealtimeEvent<{ server_id: Id; reason: string }>("server.removed", (event) => {
    void queryClient.invalidateQueries({ queryKey: ["servers"] });
    queryClient.removeQueries({ queryKey: ["server", event.server_id] });
    if (path.current.includes(`/server/${event.server_id}`)) {
      navigate("/app", { replace: true });
      push("info", t(`server.removed_${event.reason}`));
    }
  });

  useRealtimeEvent<{ conversation_id: Id; from: UserCard; expires_in: number }>("call.incoming", (call) => {
    useLive.getState().setIncomingCall({ conversationId: call.conversation_id, from: call.from, expiresAt: Date.now() + call.expires_in * 1000 });
    if (me?.settings.notification_prefs.sounds) {
      playPing();
    }
  });

  return <>{children}</>;
}
