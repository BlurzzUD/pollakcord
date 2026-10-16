import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

const handlers = vi.hoisted(() => new Map<string, (data: any) => void>());
vi.mock("../api/client", () => ({ api: { get: vi.fn() } }));
vi.mock("../realtime/socket", () => ({ realtime: { subscribeChannel: vi.fn(), unsubscribeChannel: vi.fn() } }));
vi.mock("../realtime/useRealtimeEvent", () => ({ useRealtimeEvent: (event: string, handler: (data: any) => void) => handlers.set(event, handler) }));

import { api } from "../api/client";
import type { Message } from "../api/types";
import { useTimeline } from "../components/chat/useTimeline";

const original: Message = { id: "11", scope: "channel", channel_id: "3", conversation_id: null, author: null, content: "Original", deleted: false, created_at: "2026-01-01T10:00:00Z", reply_to: null, pinned: false, reactions: [{ emoji: "🎉", count: 1, me: true }], attachments: [], embeds: [] };

beforeEach(() => {
  handlers.clear();
  vi.mocked(api.get).mockResolvedValue({ messages: [original], has_more: false, last_read_message_id: null });
});

it("updates edited bot text while preserving the viewer's reaction and scope", async () => {
  const { result } = renderHook(() => useTimeline("channel", "3", vi.fn()));
  await waitFor(() => expect(result.current.messages).toHaveLength(1));
  act(() => handlers.get("message.update")?.({ ...original, channel_id: "99", content: "Another channel" }));
  expect(result.current.messages[0].content).toBe("Original");
  act(() => handlers.get("message.update")?.({ ...original, content: "Edited", edited_at: "2026-01-01T10:01:00Z", reactions: [] }));
  expect(result.current.messages[0].content).toBe("Edited");
  expect(result.current.messages[0].edited_at).toBe("2026-01-01T10:01:00Z");
  expect(result.current.messages[0].reactions).toEqual(original.reactions);
});

it("does not restore a deleted message when a late edit arrives", async () => {
  const { result } = renderHook(() => useTimeline("channel", "3", vi.fn()));
  await waitFor(() => expect(result.current.messages).toHaveLength(1));
  act(() => handlers.get("message.delete")?.({ id: "11", channel_id: "3" }));
  act(() => handlers.get("message.update")?.({ ...original, content: "Late edit" }));
  expect(result.current.messages[0].deleted).toBe(true);
  expect(result.current.messages[0].content).toBeNull();
});
