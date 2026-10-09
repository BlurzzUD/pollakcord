import type { AppNotification } from "../api/types";
import { placeLabel, roleLabel } from "./dok";

type Translate = (key: string, options?: Record<string, unknown>) => string;

export function describeNotification(t: Translate, notification: AppNotification): { text: string; href: string | null } {
  const p = notification.payload;
  const name = (p.user?.display_name as string | undefined) ?? "";
  switch (notification.type) {
    case "friend_request":
      return { text: t("notifications.friend_request", { name }), href: "/app/friends" };
    case "friend_accepted":
      return { text: t("notifications.friend_accepted", { name }), href: "/app/friends" };
    case "dm":
      return { text: t("notifications.dm", { name }), href: `/app/dm/${p.conversation_id}` };
    case "mention":
      return { text: t("notifications.mention", { name, channel: p.channel_name, server: p.server_name }), href: `/app/server/${p.server_id}/${p.channel_id}` };
    case "server":
      return { text: t("notifications.server_invite", { name, server: p.server_name }), href: `/invite/${p.invite_code}` };
    case "call_incoming":
      return { text: t("notifications.call_incoming", { name }), href: `/app/dm/${p.conversation_id}` };
    case "call_missed":
      return { text: t("notifications.call_missed", { name }), href: `/app/dm/${p.conversation_id}` };
    case "moderation":
      return {
        text: t(`notifications.moderation_${String(p.kind)}`, { server: p.server_name, minutes: p.minutes, channel: p.channel_name }),
        href: null,
      };
    case "dok_message": {
      const label = roleLabel(t, p.author_role);
      const place = placeLabel(t, p.scope, p.class_code);
      const preview = typeof p.preview === "string" ? p.preview : "";
      return {
        text: preview ? t("notifications.dok_message_preview", { label, place, preview }) : t("notifications.dok_message", { label, place }),
        href: `/app/dok/${p.thread_id}`,
      };
    }
  }
}
