import { useInfiniteQuery, useQuery } from "@tanstack/react-query";

import { api } from "./client";
import type {
  AppNotification,
  Conversation,
  DokHistoryPage,
  DokInbox,
  FriendRequestEntry,
  Member,
  Meta,
  ServerDetail,
  ServerSummary,
  UserCard,
} from "./types";

export function useMeta() {
  return useQuery({ queryKey: ["meta"], queryFn: () => api.get<Meta>("/meta"), staleTime: Infinity });
}

export function useServers() {
  return useQuery({ queryKey: ["servers"], queryFn: () => api.get<ServerSummary[]>("/servers") });
}

export function useServer(serverId: string | undefined) {
  return useQuery({ queryKey: ["server", serverId], queryFn: () => api.get<ServerDetail>(`/servers/${serverId}`), enabled: Boolean(serverId), retry: false });
}

export function useMembers(serverId: string | undefined) {
  return useQuery({
    queryKey: ["members", serverId],
    queryFn: () => api.get<{ members: Member[]; has_more: boolean }>(`/servers/${serverId}/members`, { limit: 500 }),
    enabled: Boolean(serverId),
  });
}

export function useDms() {
  return useQuery({ queryKey: ["dms"], queryFn: () => api.get<Conversation[]>("/dms") });
}

export function useFriends() {
  return useQuery({ queryKey: ["friends"], queryFn: () => api.get<UserCard[]>("/friends") });
}

export function useFriendRequests() {
  return useQuery({
    queryKey: ["friend-requests"],
    queryFn: () => api.get<{ incoming: FriendRequestEntry[]; outgoing: FriendRequestEntry[] }>("/friends/requests"),
  });
}

export function useSuggestions() {
  return useQuery({ queryKey: ["suggestions"], queryFn: () => api.get<UserCard[]>("/friends/suggestions") });
}

export function useNotifications() {
  return useQuery({
    queryKey: ["notifications"],
    queryFn: () => api.get<{ items: AppNotification[]; unread: number }>("/notifications"),
  });
}

export function useDokInbox() {
  return useQuery({ queryKey: ["dok", "inbox"], queryFn: () => api.get<DokInbox>("/dok/inbox") });
}

export function useDokMessages(threadId: string | undefined) {
  return useInfiniteQuery({
    queryKey: ["dok", "messages", threadId],
    enabled: Boolean(threadId),
    retry: false,
    initialPageParam: undefined as string | undefined,
    queryFn: ({ pageParam }) => api.get<DokHistoryPage>(`/dok/threads/${threadId}/messages`, { limit: 50, before: pageParam }),
    getNextPageParam: (last) => (last.has_more ? last.messages[0]?.id : undefined),
  });
}
