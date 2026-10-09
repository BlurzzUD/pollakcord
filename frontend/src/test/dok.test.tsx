import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/client")>();
  return { ...actual, api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), del: vi.fn(), upload: vi.fn() } };
});

import { ApiError, api } from "../api/client";
import type { AppNotification, DokInbox, DokMessage, DokTarget, DokThread } from "../api/types";
import { DokComposer } from "../components/dok/DokComposer";
import { DokDismiss } from "../components/dok/DokDismiss";
import { DokMessageItem } from "../components/dok/DokMessageItem";
import { HomeSidebar } from "../components/layout/HomeSidebar";
import { NotificationsPanel } from "../components/layout/NotificationsPanel";
import { UserPanel } from "../components/layout/UserPanel";
import i18n, { setLanguage } from "../i18n";
import { DokPage } from "../pages/DokPage";
import { DokThreadPage } from "../pages/DokThreadPage";
import { useUi } from "../store/ui";
import { describeNotification } from "../utils/notifications";
import { isStaffRole } from "../utils/roles";
import { makeMe, renderApp, resetLanguage, signIn, signOut } from "./helpers";

const mocked = vi.mocked(api);

const own: DokTarget = { type: "class", class_id: "1001", code: "9A" };
const other: DokTarget = { type: "class", class_id: "1002", code: "10B" };
const school: DokTarget = { type: "school" };
const stamp = "2026-03-02T10:00:00+00:00";

const classThread: DokThread = {
  id: "500",
  scope: "class",
  class: { id: "1001", code: "9A" },
  last_message: { preview: "Holnap gyűlés", created_at: stamp },
  last_message_at: stamp,
  unread: 2,
  can_send: false,
};
const schoolThread: DokThread = { ...classThread, id: "501", scope: "school", class: null, last_message: { preview: "Iskolagyűlés", created_at: stamp }, unread: 1 };

function inbox(threads: DokThread[], send: DokInbox["send"] = { allowed: false, targets: [] }): DokInbox {
  return { threads, unread: threads.reduce((sum, thread) => sum + thread.unread, 0), send };
}

function message(overrides: Partial<DokMessage> = {}): DokMessage {
  return { id: "900", thread_id: "500", scope: "class", author_role: "dok_representative", author: null, mine: false, content: "Holnap rövidített órák.", created_at: stamp, ...overrides };
}

const realAuthor = { id: "9", username: "rep_eva", display_name: "Éva", avatar_url: null, staff: false };

function serve(responses: Record<string, unknown>) {
  mocked.get.mockImplementation(async (path: string) => {
    if (path in responses) {
      return responses[path];
    }
    throw new ApiError(404, "not_found", "x");
  });
}

function translate(key: string, options?: Record<string, unknown>): string {
  return i18n.t(key, options) as string;
}

function setVisibility(state: "visible" | "hidden") {
  Object.defineProperty(document, "visibilityState", { value: state, configurable: true });
}

beforeEach(() => {
  resetLanguage();
  signOut();
  Object.values(mocked).forEach((fn) => fn.mockReset());
  useUi.setState({ toasts: [] });
  setVisibility("visible");
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  resetLanguage();
});

describe("dismiss control", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  it("stays disabled for three seconds and then dismisses", () => {
    const onDismiss = vi.fn();
    renderApp(<DokDismiss onDismiss={onDismiss} />);
    const button = screen.getByRole("button", { name: "Elvetés" });
    expect(button).toBeDisabled();
    fireEvent.click(button);
    expect(onDismiss).not.toHaveBeenCalled();
    act(() => {
      vi.advanceTimersByTime(2750);
    });
    expect(button).toBeDisabled();
    act(() => {
      vi.advanceTimersByTime(250);
    });
    expect(button).toBeEnabled();
    fireEvent.click(button);
    expect(onDismiss).toHaveBeenCalledTimes(1);
  });

  it("does not count time while the page is hidden", () => {
    setVisibility("hidden");
    renderApp(<DokDismiss onDismiss={vi.fn()} />);
    act(() => {
      vi.advanceTimersByTime(10000);
    });
    expect(screen.getByRole("button", { name: "Elvetés" })).toBeDisabled();
    setVisibility("visible");
    act(() => {
      vi.advanceTimersByTime(3000);
    });
    expect(screen.getByRole("button", { name: "Elvetés" })).toBeEnabled();
  });

  it("stays disabled while a dismissal is in flight", () => {
    renderApp(<DokDismiss onDismiss={vi.fn()} busy />);
    act(() => {
      vi.advanceTimersByTime(5000);
    });
    expect(screen.getByRole("button", { name: "Elvetés" })).toBeDisabled();
  });
});

describe("notifications panel", () => {
  const dokNotification = (overrides: Partial<AppNotification> = {}): AppNotification => ({
    id: "77",
    type: "dok_message",
    read: false,
    created_at: stamp,
    payload: { thread_id: "500", dok_message_id: "900", scope: "class", class_code: "9A", author_role: "dok_representative", preview: "Holnap rövidített órák lesznek" },
    ...overrides,
  });
  const friend: AppNotification = { id: "78", type: "friend_request", read: false, created_at: stamp, payload: { user: { id: "2", username: "anna_t", display_name: "Anna", avatar_url: null, staff: false } } };
  const readSchool = dokNotification({ id: "79", read: true, payload: { thread_id: "501", dok_message_id: "901", scope: "school", class_code: null, author_role: "dok_president" } });

  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    signIn();
    mocked.get.mockResolvedValue({ items: [dokNotification(), friend, readSchool], unread: 2 });
    mocked.post.mockResolvedValue({});
  });

  it("offers dismissal only for unread DÖK notifications and only after three seconds", async () => {
    renderApp(<NotificationsPanel onClose={vi.fn()} />);
    expect(await screen.findByText(/DÖK képviselő \(9A\)/)).toBeInTheDocument();
    expect(screen.getByText("Új DÖK-üzenet: DÖK elnök (Iskola).")).toBeInTheDocument();
    const buttons = screen.getAllByRole("button", { name: "Elvetés" });
    expect(buttons).toHaveLength(1);
    expect(buttons[0]).toBeDisabled();
    expect(mocked.post).not.toHaveBeenCalled();
    act(() => {
      vi.advanceTimersByTime(3000);
    });
    expect(buttons[0]).toBeEnabled();
    fireEvent.click(buttons[0]);
    await waitFor(() => expect(mocked.post).toHaveBeenCalledWith("/notifications/read", { ids: ["77"] }));
  });

  it("never shows a username for a DÖK notification", async () => {
    renderApp(<NotificationsPanel onClose={vi.fn()} />);
    await screen.findByText(/DÖK képviselő \(9A\)/);
    expect(document.body.textContent).not.toContain("rep_eva");
  });
});

describe("DÖK notification text", () => {
  const make = (payload: Record<string, unknown>): AppNotification => ({ id: "1", type: "dok_message", payload, read: false, created_at: stamp });

  it("names the role and place, links to the thread and falls back without a preview", () => {
    const base = { thread_id: "500", dok_message_id: "9", scope: "class", class_code: "9A", author_role: "dok_representative" };
    const withPreview = describeNotification(translate, make({ ...base, preview: "Gyűlés" }));
    expect(withPreview.text).toBe("DÖK képviselő (9A): „Gyűlés”");
    expect(withPreview.href).toBe("/app/dok/500");
    const bare = describeNotification(translate, make({ ...base, scope: "school", class_code: null, author_role: "dok_president" }));
    expect(bare.text).toBe("Új DÖK-üzenet: DÖK elnök (Iskola).");
  });
});

describe("message bubbles", () => {
  it("show only the role label to ordinary recipients", () => {
    renderApp(<DokMessageItem message={message()} />);
    expect(screen.getByText("DÖK képviselő")).toBeInTheDocument();
    expect(screen.queryByText(/Valódi küldő/)).not.toBeInTheDocument();
    expect(document.body.textContent).not.toContain("rep_eva");
  });

  it("label presidents and follow the interface language", async () => {
    await act(async () => {
      setLanguage("en");
    });
    renderApp(<DokMessageItem message={message({ author_role: "dok_president" })} />);
    expect(screen.getByText("DÖK president")).toBeInTheDocument();
  });

  it("reveal the real author only when the server provides it", () => {
    renderApp(<DokMessageItem message={message({ author: realAuthor })} />);
    expect(screen.getByText("DÖK képviselő")).toBeInTheDocument();
    expect(screen.getByText(/Valódi küldő: Éva \(@rep_eva\)/)).toBeInTheDocument();
  });

  it("mark the author's own messages without repeating the name", () => {
    renderApp(<DokMessageItem message={message({ mine: true, author: realAuthor })} />);
    expect(screen.getByText("Te küldted")).toBeInTheDocument();
    expect(screen.queryByText(/Valódi küldő/)).not.toBeInTheDocument();
  });

  it("render content as inert text without mention buttons", () => {
    renderApp(<DokMessageItem message={message({ content: "<@123> <b>félkövér</b> https://example.com/a" })} />);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(document.querySelector("b")).toBeNull();
    expect(screen.getByText("<@123>")).toBeInTheDocument();
    const link = screen.getByRole("link", { name: "https://example.com/a" });
    expect(link.getAttribute("rel")).toContain("noopener");
  });
});

describe("composer", () => {
  beforeEach(() => {
    mocked.get.mockResolvedValue({ limits: { message_max_length: 4000, voice_max_participants: 8 } });
  });

  it("locks representatives to their own class and tells them moderators can see who sent", () => {
    signIn(makeMe({ platform_role: "dok_representative", class_code: "9A" }));
    renderApp(<DokComposer targets={[own]} onSent={vi.fn()} />);
    expect(screen.getByText("Címzett: 9A osztály")).toBeInTheDocument();
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
    expect(screen.getByText(/moderátorok és az adminisztrátorok látják/)).toBeInTheDocument();
  });

  it("lets presidents choose the school or any class and defaults to their own class", () => {
    signIn(makeMe({ platform_role: "dok_president", class_code: "10B" }));
    renderApp(<DokComposer targets={[school, own, other]} onSent={vi.fn()} />);
    const select = screen.getByRole("combobox", { name: "Címzett" });
    expect(within(select).getAllByRole("option").map((option) => option.textContent)).toEqual(["Az egész iskola", "9A osztály", "10B osztály"]);
    expect(select).toHaveValue("class:1002");
  });

  it("never defaults to the whole school", () => {
    signIn(makeMe({ platform_role: "dok_president", class_code: null }));
    renderApp(<DokComposer targets={[school, own, other]} onSent={vi.fn()} />);
    expect(screen.getByRole("combobox", { name: "Címzett" })).toHaveValue("class:1001");
  });

  it("posts the class target and reports the sent message", async () => {
    signIn(makeMe({ platform_role: "dok_representative", class_code: "9A" }));
    const sent = message({ id: "901", mine: true });
    mocked.post.mockResolvedValue(sent);
    const onSent = vi.fn();
    renderApp(<DokComposer targets={[own]} onSent={onSent} />);
    const input = screen.getByLabelText("DÖK-üzenet szövege");
    fireEvent.change(input, { target: { value: "Holnap gyűlés" } });
    fireEvent.click(screen.getByRole("button", { name: "Küldés" }));
    await waitFor(() => expect(mocked.post).toHaveBeenCalledWith("/dok/messages", { content: "Holnap gyűlés", target: { type: "class", class_id: "1001" } }));
    await waitFor(() => expect(onSent).toHaveBeenCalledWith(sent));
    expect(input).toHaveValue("");
  });

  it("sends on Enter and keeps Shift+Enter for new lines", async () => {
    signIn(makeMe({ platform_role: "dok_representative", class_code: "9A" }));
    mocked.post.mockResolvedValue(message());
    renderApp(<DokComposer targets={[own]} onSent={vi.fn()} />);
    const input = screen.getByLabelText("DÖK-üzenet szövege");
    fireEvent.change(input, { target: { value: "Sor" } });
    fireEvent.keyDown(input, { key: "Enter", shiftKey: true });
    expect(mocked.post).not.toHaveBeenCalled();
    fireEvent.keyDown(input, { key: "Enter" });
    await waitFor(() => expect(mocked.post).toHaveBeenCalledTimes(1));
  });

  it("does not send empty messages", () => {
    signIn(makeMe({ platform_role: "dok_representative", class_code: "9A" }));
    renderApp(<DokComposer targets={[own]} onSent={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("DÖK-üzenet szövege"), { target: { value: "   " } });
    expect(screen.getByRole("button", { name: "Küldés" })).toBeDisabled();
  });

  it("asks for confirmation before anything goes to the whole school", async () => {
    signIn(makeMe({ platform_role: "dok_president" }));
    mocked.post.mockResolvedValue(message({ scope: "school", author_role: "dok_president" }));
    renderApp(<DokComposer targets={[school, own]} preferred="school" onSent={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("DÖK-üzenet szövege"), { target: { value: "Mindenkinek" } });
    fireEvent.click(screen.getByRole("button", { name: "Küldés" }));
    expect(mocked.post).not.toHaveBeenCalled();
    const dialog = await screen.findByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Mégse" }));
    expect(mocked.post).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Küldés" }));
    const again = await screen.findByRole("dialog");
    fireEvent.click(within(again).getByRole("button", { name: "Küldés az egész iskolának" }));
    await waitFor(() => expect(mocked.post).toHaveBeenCalledWith("/dok/messages", { content: "Mindenkinek", target: { type: "school" } }));
  });

  it("shows the translated server refusal", async () => {
    signIn(makeMe({ platform_role: "dok_representative", class_code: "9A" }));
    mocked.post.mockRejectedValue(new ApiError(403, "dok_target_forbidden", "x"));
    renderApp(<DokComposer targets={[own]} onSent={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("DÖK-üzenet szövege"), { target: { value: "Szia" } });
    fireEvent.click(screen.getByRole("button", { name: "Küldés" }));
    expect(await screen.findByText("DÖK-képviselőként csak a saját osztályodnak küldhetsz üzenetet.")).toBeInTheDocument();
  });
});

describe("thread page", () => {
  const meta = { limits: { message_max_length: 4000, voice_max_participants: 8 } };
  const page = (messages: DokMessage[]) => ({ messages, has_more: false, last_read_message_id: null });

  function renderThread(route: string) {
    return renderApp(
      <Routes>
        <Route path="/app/dok/:threadId" element={<DokThreadPage />} />
      </Routes>,
      route,
    );
  }

  it("shows role labels and no composer to ordinary recipients, then marks the thread read", async () => {
    signIn(makeMe({ class_code: "9A" }));
    serve({ "/dok/inbox": inbox([classThread]), "/dok/threads/500/messages": page([message()]) });
    mocked.post.mockResolvedValue({ status: "ok" });
    renderThread("/app/dok/500");
    expect(await screen.findByText("Holnap rövidített órák.")).toBeInTheDocument();
    expect(screen.getByText("DÖK képviselő")).toBeInTheDocument();
    expect(screen.getByText("9A osztály")).toBeInTheDocument();
    expect(screen.queryByLabelText("DÖK-üzenet szövege")).not.toBeInTheDocument();
    expect(document.body.textContent).not.toContain("rep_eva");
    await waitFor(() => expect(mocked.post).toHaveBeenCalledWith("/dok/threads/500/read", { message_id: "900" }), { timeout: 3000 });
  });

  it("does not mark anything read when nothing is unread", async () => {
    signIn(makeMe({ class_code: "9A" }));
    serve({ "/dok/inbox": inbox([{ ...classThread, unread: 0 }]), "/dok/threads/500/messages": page([message()]) });
    renderThread("/app/dok/500");
    await screen.findByText("Holnap rövidített órák.");
    await new Promise((resolve) => setTimeout(resolve, 700));
    expect(mocked.post).not.toHaveBeenCalled();
  });

  it("offers the composer to a representative only on a thread they can send to", async () => {
    signIn(makeMe({ platform_role: "dok_representative", class_code: "9A" }));
    const send = { allowed: true, targets: [own] };
    serve({
      "/meta": meta,
      "/dok/inbox": inbox([{ ...classThread, can_send: true, unread: 0 }, { ...schoolThread, can_send: false, unread: 0 }], send),
      "/dok/threads/500/messages": page([message({ mine: true, author: realAuthor })]),
      "/dok/threads/501/messages": page([message({ id: "901", thread_id: "501", scope: "school", author_role: "dok_president" })]),
    });
    const first = renderThread("/app/dok/500");
    expect(await screen.findByLabelText("DÖK-üzenet szövege")).toBeInTheDocument();
    first.unmount();
    renderThread("/app/dok/501");
    expect(await screen.findByText("DÖK elnök")).toBeInTheDocument();
    expect(screen.queryByLabelText("DÖK-üzenet szövege")).not.toBeInTheDocument();
  });

  it("shows the real author to a viewer when the server supplies it", async () => {
    signIn(makeMe({ platform_role: "school_moderator" }));
    serve({ "/dok/inbox": inbox([{ ...classThread, unread: 0 }]), "/dok/threads/500/messages": page([message({ author: realAuthor })]) });
    renderThread("/app/dok/500");
    expect(await screen.findByText(/Valódi küldő: Éva \(@rep_eva\)/)).toBeInTheDocument();
  });

  it("explains that a thread outside the inbox is unavailable without hinting at it", async () => {
    signIn();
    serve({ "/dok/inbox": inbox([]) });
    renderThread("/app/dok/999");
    expect((await screen.findAllByText("Ez a DÖK-beszélgetés nem érhető el.")).length).toBeGreaterThan(0);
    expect(mocked.get).not.toHaveBeenCalledWith("/dok/threads/999/messages", expect.anything());
  });
});

describe("DÖK page", () => {
  it("explains how to receive DÖK messages when the user has no class", async () => {
    signIn(makeMe({ class_code: null }));
    serve({ "/dok/inbox": inbox([]) });
    renderApp(<DokPage />, "/app/dok");
    expect(await screen.findByText(/Állítsd be az osztályodat/)).toBeInTheDocument();
    expect(screen.queryByLabelText("DÖK-üzenet szövege")).not.toBeInTheDocument();
    expect(screen.getByText("Még nem érkezett DÖK-üzenet.")).toBeInTheDocument();
  });

  it("opens the thread after a sender posts from the landing page", async () => {
    signIn(makeMe({ platform_role: "dok_representative", class_code: "9A" }));
    serve({ "/meta": { limits: { message_max_length: 4000, voice_max_participants: 8 } }, "/dok/inbox": inbox([], { allowed: true, targets: [own] }) });
    mocked.post.mockResolvedValue(message({ thread_id: "500", mine: true }));
    renderApp(
      <Routes>
        <Route path="/app/dok" element={<DokPage />} />
        <Route path="/app/dok/:threadId" element={<p>thread view</p>} />
      </Routes>,
      "/app/dok",
    );
    fireEvent.change(await screen.findByLabelText("DÖK-üzenet szövege"), { target: { value: "Szia osztály" } });
    fireEvent.click(screen.getByRole("button", { name: "Küldés" }));
    expect(await screen.findByText("thread view")).toBeInTheDocument();
  });
});

describe("sidebar", () => {
  it("lists DÖK threads with unread counts next to friends and direct messages", async () => {
    signIn(makeMe({ class_code: "9A" }));
    serve({ "/dms": [], "/friends/requests": { incoming: [], outgoing: [] }, "/dok/inbox": inbox([classThread, schoolThread]) });
    renderApp(<HomeSidebar />, "/app");
    const entry = await screen.findByRole("link", { name: /^DÖK\s*3$/ });
    expect(entry).toHaveAttribute("href", "/app/dok");
    const classLink = screen.getByRole("link", { name: /9A osztály/ });
    expect(classLink).toHaveAttribute("href", "/app/dok/500");
    expect(within(classLink).getByText("2")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Iskola/ })).toHaveAttribute("href", "/app/dok/501");
  });

  it("keeps the DÖK entry but hides the thread list when there are no threads", async () => {
    signIn();
    serve({ "/dms": [], "/friends/requests": { incoming: [], outgoing: [] }, "/dok/inbox": inbox([]) });
    renderApp(<HomeSidebar />, "/app");
    expect(await screen.findByRole("link", { name: "DÖK" })).toBeInTheDocument();
    expect(screen.queryByText("DÖK-üzenetek")).not.toBeInTheDocument();
  });
});

describe("platform roles in the interface", () => {
  it.each([
    ["user", false],
    ["dok_representative", false],
    ["dok_president", false],
    ["school_moderator", true],
    ["school_admin", true],
  ] as const)("treats %s as staff: %s", async (role, staff) => {
    expect(isStaffRole(role)).toBe(staff);
    serve({ "/notifications": { items: [], unread: 0 } });
    signIn(makeMe({ platform_role: role }));
    renderApp(<UserPanel />);
    const link = screen.queryByRole("link", { name: "Iskolai moderáció" });
    if (staff) {
      expect(link).toBeInTheDocument();
    } else {
      expect(link).not.toBeInTheDocument();
    }
  });
});
