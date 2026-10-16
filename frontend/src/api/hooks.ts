import { useInfiniteQuery, useQuery } from "@tanstack/react-query";

import { useAuth } from "../store/auth";
import { canCreateForms } from "../utils/roles";
import { useLinkPolicy } from "../utils/links";
import { api } from "./client";
import type {
  AppNotification,
  ClassSpaceHistoryPage,
  ClassSpaceMembers,
  ClassSpaceState,
  Conversation,
  DokHistoryPage,
  DokInbox,
  FormDetail,
  FormList,
  FormResults,
  FriendRequestEntry,
  Member,
  Meta,
  MediaConfig,
  ServerDetail,
  ServerSummary,
  UserCard,
} from "./types";

export function useMeta() {
  return useQuery({ queryKey: ["meta"], queryFn: async () => {
    const meta = await api.get<Meta>("/meta");
    if (meta.public_origin) {
      useLinkPolicy.getState().setPublicOrigin(meta.public_origin);
    }
    return meta;
  }, staleTime: Infinity });
}

export function useMediaConfig() {
  const me = useAuth((state) => state.me);
  return useQuery({
    queryKey: ["media-config", me?.id, me?.platform_role], enabled: Boolean(me), retry: false,
    queryFn: async () => {
      const config = await api.get<MediaConfig>("/uploads/config");
      useLinkPolicy.getState().setPublicOrigin(config.public_origin);
      return config;
    },
  });
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

export const classSpaceStateKey = (classCode: string | null | undefined) => ["class-space", "state", classCode ?? null];

export function useClassSpace() {
  const classCode = useAuth((state) => state.me?.class_code);
  return useQuery({
    queryKey: classSpaceStateKey(classCode),
    queryFn: () => api.get<ClassSpaceState>("/class-spaces/me"),
    enabled: Boolean(classCode),
  });
}

export function useClassSpaceMembers(classId: string | undefined) {
  return useQuery({
    queryKey: ["class-space", "members", classId],
    queryFn: () => api.get<ClassSpaceMembers>(`/class-spaces/${classId}/members`),
    enabled: Boolean(classId),
    retry: false,
  });
}

export function useClassSpaceMessages(classId: string | undefined) {
  return useInfiniteQuery({
    queryKey: ["class-space", "messages", classId],
    enabled: Boolean(classId),
    retry: false,
    initialPageParam: undefined as string | undefined,
    queryFn: ({ pageParam }) => api.get<ClassSpaceHistoryPage>(`/class-spaces/${classId}/messages`, { limit: 50, before: pageParam }),
    getNextPageParam: (last) => (last.has_more ? last.messages[0]?.id : undefined),
  });
}

export function useForms() {
  const classCode = useAuth((state) => state.me?.class_code);
  const role = useAuth((state) => state.me?.platform_role);
  return useQuery({
    queryKey: ["forms", "list", classCode ?? null, role ?? null],
    queryFn: () => api.get<FormList>("/forms"),
    enabled: Boolean(classCode) || canCreateForms(role),
    refetchOnWindowFocus: true,
  });
}

export function useForm(formId: string | undefined) {
  return useQuery({
    queryKey: ["forms", "detail", formId],
    queryFn: () => api.get<FormDetail>(`/forms/${formId}`),
    enabled: Boolean(formId),
    retry: false,
  });
}

export function useFormResults(formId: string | undefined, allowed: boolean) {
  return useInfiniteQuery({
    queryKey: ["forms", "results", formId],
    enabled: Boolean(formId) && allowed,
    retry: false,
    refetchOnWindowFocus: true,
    initialPageParam: undefined as string | undefined,
    queryFn: ({ pageParam }) => api.get<FormResults>(`/forms/${formId}/responses`, { limit: 50, before: pageParam }),
    getNextPageParam: (last) => (last.has_more ? last.responses[last.responses.length - 1]?.id : undefined),
  });
}
