import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/client")>();
  return { ...actual, api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), del: vi.fn(), upload: vi.fn() } };
});

import { ApiError, api } from "../api/client";
import { useClassSpace } from "../api/hooks";
import type { ClassSpaceMembers, ClassSpaceMessage, ClassSpaceState, UserCard } from "../api/types";
import { ClassSpaceMembersDialog } from "../components/classspace/ClassSpaceMembersDialog";
import { ClassSpaceMessageItem } from "../components/classspace/ClassSpaceMessageItem";
import { ClassSpacePrompt } from "../components/classspace/ClassSpacePrompt";
import { ClassSpaceSetting } from "../components/classspace/ClassSpaceSetting";
import { HomeSidebar } from "../components/layout/HomeSidebar";
import de from "../i18n/locales/de.json";
import en from "../i18n/locales/en.json";
import hu from "../i18n/locales/hu.json";
import i18n, { setLanguage } from "../i18n";
import { ClassSpacePage } from "../pages/ClassSpacePage";
import { useClassSpaceUi } from "../store/classSpace";
import { useUi } from "../store/ui";
import { makeMe, renderApp, resetLanguage, signIn, signOut } from "./helpers";

const mocked = vi.mocked(api);

const stamp = "2026-03-02T10:00:00+00:00";
const school = { id: "1001", code: "9A" };
const anna: UserCard = { id: "2", username: "anna_t", display_name: "Anna", avatar_url: null, staff: false };
const eva: UserCard = { id: "1", username: "eva_k", display_name: "Éva", avatar_url: null, staff: false };

function state(overrides: Partial<ClassSpaceState> = {}): ClassSpaceState {
  return { class: school, member: true, prompt_required: false, show_username: true, alias: "a3f9c1", members: 3, unread: 0, ...overrides };
}

const required = state({ member: false, prompt_required: true, show_username: null, alias: null, members: null });

function entry(overrides: Partial<ClassSpaceMessage> = {}): ClassSpaceMessage {
  return { id: "20", class_id: "1001", author: anna, alias: null, mine: false, content: "Holnap dolgozat lesz.", created_at: stamp, ...overrides };
}

function history(messages: ClassSpaceMessage[]) {
  return { messages, has_more: false, last_read_message_id: null };
}

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

function Probe() {
  const space = useClassSpace();
  return <p>{space.isSuccess ? "loaded" : "loading"}</p>;
}

function setVisibility(value: "visible" | "hidden") {
  Object.defineProperty(document, "visibilityState", { value, configurable: true });
}

beforeEach(() => {
  resetLanguage();
  signOut();
  Object.values(mocked).forEach((fn) => fn.mockReset());
  useUi.setState({ toasts: [] });
  useClassSpaceUi.setState({ dismissedFor: null });
  setVisibility("visible");
});

afterEach(() => {
  cleanup();
  resetLanguage();
});

describe("class space prompt", () => {
  it("appears for a user with a class who has not answered yet", async () => {
    signIn(makeMe({ class_code: "9A" }));
    serve({ "/class-spaces/me": required });
    renderApp(<ClassSpacePrompt />, "/app");
    const dialog = await screen.findByRole("dialog", { name: "Osztálytér – 9A" });
    expect(within(dialog).getByText("Megjelenjen a felhasználóneved az osztálytársaid előtt ebben a térben?")).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Igen, látszódjon a nevem" })).toBeInTheDocument();
    const preferred = within(dialog).getByRole("button", { name: "Nem, rejtve maradok" });
    await waitFor(() => expect(preferred).toHaveFocus());
  });

  it("does not appear once the question has been answered", async () => {
    signIn(makeMe({ class_code: "9A" }));
    serve({ "/class-spaces/me": state() });
    renderApp(
      <>
        <Probe />
        <ClassSpacePrompt />
      </>,
      "/app",
    );
    await screen.findByText("loaded");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("never asks users without a class and does not even query the server", () => {
    signIn(makeMe());
    renderApp(<ClassSpacePrompt />, "/app");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(mocked.get).not.toHaveBeenCalled();
  });

  it.each([
    ["Igen, látszódjon a nevem", true],
    ["Nem, rejtve maradok", false],
  ])("answering “%s” sends the choice and dismisses the prompt", async (label, shows) => {
    signIn(makeMe({ class_code: "9A" }));
    serve({ "/class-spaces/me": required });
    mocked.put.mockResolvedValue(state({ show_username: shows }));
    renderApp(<ClassSpacePrompt />, "/app");
    fireEvent.click(await screen.findByRole("button", { name: label }));
    await waitFor(() => expect(mocked.put).toHaveBeenCalledWith("/class-spaces/me/visibility", { show_username: shows }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(mocked.put).toHaveBeenCalledTimes(1);
  });

  it("keeps the prompt open and explains the problem when saving fails", async () => {
    signIn(makeMe({ class_code: "9A" }));
    serve({ "/class-spaces/me": required });
    mocked.put.mockRejectedValue(new ApiError(429, "rate_limited", "x"));
    renderApp(<ClassSpacePrompt />, "/app");
    fireEvent.click(await screen.findByRole("button", { name: "Nem, rejtve maradok" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(translate("errors.rate_limited"));
    expect(screen.getByRole("dialog", { name: "Osztálytér – 9A" })).toBeInTheDocument();
  });

  it("can be postponed for this visit without answering", async () => {
    signIn(makeMe({ class_code: "9A" }));
    serve({ "/class-spaces/me": required });
    renderApp(<ClassSpacePrompt />, "/app");
    fireEvent.click(await screen.findByRole("button", { name: "Később" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(mocked.put).not.toHaveBeenCalled();
    expect(useClassSpaceUi.getState().dismissedFor).toBe("1001");
  });

  it("closes on Escape without answering", async () => {
    signIn(makeMe({ class_code: "9A" }));
    serve({ "/class-spaces/me": required });
    renderApp(<ClassSpacePrompt />, "/app");
    const dialog = await screen.findByRole("dialog", { name: "Osztálytér – 9A" });
    fireEvent.keyDown(dialog, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(mocked.put).not.toHaveBeenCalled();
  });

  it("asks again for a different class even after it was postponed for the old one", async () => {
    useClassSpaceUi.setState({ dismissedFor: "1001" });
    signIn(makeMe({ class_code: "10B" }));
    serve({ "/class-spaces/me": { ...required, class: { id: "1002", code: "10B" } } });
    renderApp(<ClassSpacePrompt />, "/app");
    expect(await screen.findByRole("dialog", { name: "Osztálytér – 10B" })).toBeInTheDocument();
  });

  it("is available in English and German", async () => {
    await act(async () => {
      setLanguage("en");
    });
    signIn(makeMe({ class_code: "9A" }));
    serve({ "/class-spaces/me": required });
    const view = renderApp(<ClassSpacePrompt />, "/app");
    expect(await screen.findByRole("dialog", { name: "Class space – 9A" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Yes, show my name" })).toBeInTheDocument();
    view.unmount();
    await act(async () => {
      setLanguage("de");
    });
    renderApp(<ClassSpacePrompt />, "/app");
    expect(await screen.findByRole("dialog", { name: "Klassenraum – 9A" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Ja, meinen Namen zeigen" })).toBeInTheDocument();
  });
});

describe("message authors", () => {
  const handlers = { onDelete: vi.fn(), onReport: vi.fn() };

  it("shows the display name of a classmate who shares their username", () => {
    render(<ClassSpaceMessageItem message={entry()} {...handlers} />);
    expect(screen.getByText("Anna")).toBeInTheDocument();
    expect(screen.queryByText(/Osztálytárs/)).not.toBeInTheDocument();
  });

  it("shows only the classmate label and a short id when the username is hidden", () => {
    const { container } = render(<ClassSpaceMessageItem message={entry({ author: null, alias: "a3f9c1" })} {...handlers} />);
    expect(screen.getByText("Osztálytárs #a3f9c1")).toBeInTheDocument();
    expect(screen.getByRole("article", { name: /Osztálytárs #a3f9c1/ })).toBeInTheDocument();
    expect(container.textContent).not.toContain("anna_t");
    expect(container.querySelector("img")).toBeNull();
  });

  it("shows the plain label when a once-visible message is hidden again", () => {
    render(<ClassSpaceMessageItem message={entry({ author: null, alias: null })} {...handlers} />);
    expect(screen.getByText("Osztálytárs")).toBeInTheDocument();
    expect(screen.queryByText(/#/)).not.toBeInTheDocument();
  });

  it("labels the viewer’s own messages and offers delete only for them", () => {
    render(<ClassSpaceMessageItem message={entry({ author: eva, mine: true })} {...handlers} />);
    expect(screen.getByText("Te")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Üzenet törlése" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Üzenet jelentése" })).not.toBeInTheDocument();
  });

  it("offers reporting only for other people’s messages and passes the message on", () => {
    const onReport = vi.fn();
    const message = entry({ author: null, alias: "a3f9c1" });
    render(<ClassSpaceMessageItem message={message} onDelete={vi.fn()} onReport={onReport} />);
    expect(screen.queryByRole("button", { name: "Üzenet törlése" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Üzenet jelentése" }));
    expect(onReport).toHaveBeenCalledWith(message);
  });

  it("renders message content as inert text, never as markup", () => {
    const hostile = '<img src=x onerror="alert(1)"><script>alert(1)</script> https://example.com/x javascript:alert(1)';
    const { container } = render(<ClassSpaceMessageItem message={entry({ content: hostile })} {...handlers} />);
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("script")).toBeNull();
    const links = container.querySelectorAll("a");
    expect(links).toHaveLength(1);
    expect(links[0]).toHaveAttribute("href", "https://example.com/x");
    expect(links[0]).toHaveAttribute("rel", expect.stringContaining("noopener"));
    expect(container.textContent).toContain("<script>alert(1)</script>");
  });

  it("does not turn mention tokens into names", () => {
    const { container } = render(<ClassSpaceMessageItem message={entry({ content: "Szia <@2>" })} {...handlers} />);
    expect(container.textContent).toContain("Szia <@2>");
    expect(screen.queryByRole("button", { name: "@Anna" })).not.toBeInTheDocument();
  });

  it.each([
    ["en", "Classmate #a3f9c1", "You"],
    ["de", "Mitschüler #a3f9c1", "Du"],
    ["hu", "Osztálytárs #a3f9c1", "Te"],
  ] as const)("uses the %s labels", async (language, hidden, you) => {
    await act(async () => {
      setLanguage(language);
    });
    const view = render(<ClassSpaceMessageItem message={entry({ author: null, alias: "a3f9c1" })} {...handlers} />);
    expect(screen.getByText(hidden)).toBeInTheDocument();
    view.unmount();
    render(<ClassSpaceMessageItem message={entry({ author: eva, mine: true })} {...handlers} />);
    expect(screen.getByText(you)).toBeInTheDocument();
  });
});

describe("member list", () => {
  const listing: ClassSpaceMembers = {
    class: school,
    members: [
      { user: eva, mine: true, show_username: false },
      { user: anna, mine: false, show_username: true },
    ],
    hidden_count: 2,
    total: 4,
  };

  it("lists classmates who share their username and only counts the hidden ones", async () => {
    signIn(makeMe({ class_code: "9A" }));
    serve({ "/class-spaces/1001/members": listing });
    renderApp(<ClassSpaceMembersDialog classId="1001" code="9A" onClose={vi.fn()} />);
    const dialog = await screen.findByRole("dialog", { name: "Az osztálytér tagjai (9A)" });
    expect(await within(dialog).findByText("@anna_t")).toBeInTheDocument();
    expect(within(dialog).getByText("2 további osztálytárs rejtett névvel")).toBeInTheDocument();
    expect(within(dialog).getAllByRole("listitem")).toHaveLength(2);
    expect(dialog.textContent).not.toContain("Osztálytárs #");
  });

  it("tells the viewer when their own name is hidden from the others", async () => {
    signIn(makeMe({ class_code: "9A" }));
    serve({ "/class-spaces/1001/members": listing });
    renderApp(<ClassSpaceMembersDialog classId="1001" code="9A" onClose={vi.fn()} />);
    const dialog = await screen.findByRole("dialog", { name: "Az osztálytér tagjai (9A)" });
    expect(await within(dialog).findByText("A neved mások előtt rejtve van.")).toBeInTheDocument();
    expect(within(dialog).getByText("Te")).toBeInTheDocument();
  });

  it("omits the hidden counter when everybody shares their username", async () => {
    signIn(makeMe({ class_code: "9A" }));
    serve({ "/class-spaces/1001/members": { ...listing, hidden_count: 0, total: 2 } });
    renderApp(<ClassSpaceMembersDialog classId="1001" code="9A" onClose={vi.fn()} />);
    await screen.findByText("@anna_t");
    expect(screen.queryByText(/rejtett névvel/)).not.toBeInTheDocument();
  });

  it("closes from the footer button", async () => {
    const onClose = vi.fn();
    signIn(makeMe({ class_code: "9A" }));
    serve({ "/class-spaces/1001/members": listing });
    renderApp(<ClassSpaceMembersDialog classId="1001" code="9A" onClose={onClose} />);
    const dialog = await screen.findByRole("dialog");
    fireEvent.click(within(dialog).getAllByRole("button", { name: "Bezárás" }).at(-1) as HTMLElement);
    expect(onClose).toHaveBeenCalled();
  });
});

describe("class space page", () => {
  it("explains how to join when the user has no class", () => {
    signIn(makeMe());
    renderApp(<ClassSpacePage />, "/app/class-space");
    expect(screen.getByText("Még nincs osztályod megadva")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Osztály beállítása" })).toHaveAttribute("href", "/app/settings/account");
    expect(mocked.get).not.toHaveBeenCalled();
  });

  it("asks for the visibility answer before showing the space and can reopen the prompt", async () => {
    useClassSpaceUi.setState({ dismissedFor: "1001" });
    signIn(makeMe({ class_code: "9A" }));
    serve({ "/class-spaces/me": required });
    renderApp(<ClassSpacePage />, "/app/class-space");
    expect(await screen.findByText("Csatlakozz az osztályod teréhez")).toBeInTheDocument();
    expect(screen.queryByRole("log")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Válaszolok" }));
    expect(useClassSpaceUi.getState().dismissedFor).toBeNull();
  });

  it("shows the conversation and the visibility banner to members who share their username", async () => {
    signIn(makeMe({ class_code: "9A" }));
    serve({ "/class-spaces/me": state(), "/class-spaces/1001/messages": history([entry()]) });
    renderApp(<ClassSpacePage />, "/app/class-space");
    expect(await screen.findByRole("heading", { name: "Osztálytér – 9A" })).toBeInTheDocument();
    expect(await screen.findByText("Holnap dolgozat lesz.")).toBeInTheDocument();
    expect(screen.getByText("Anna")).toBeInTheDocument();
    expect(screen.getByText("A felhasználóneved látható az osztálytársaid számára.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Tagok: 3" })).toBeInTheDocument();
  });

  it("tells hidden members how the others see them and never shows peer usernames", async () => {
    signIn(makeMe({ class_code: "9A" }));
    serve({
      "/class-spaces/me": state({ show_username: false }),
      "/class-spaces/1001/messages": history([entry({ author: null, alias: "77aa10", content: "Ki hozza a jegyzetet?" })]),
    });
    renderApp(<ClassSpacePage />, "/app/class-space");
    expect(await screen.findByText("Ki hozza a jegyzetet?")).toBeInTheDocument();
    expect(screen.getByText("Osztálytárs #77aa10")).toBeInTheDocument();
    expect(screen.getByText("Az osztálytársaid „Osztálytárs #a3f9c1” címkével látnak; a felhasználóneved rejtve van.")).toBeInTheDocument();
    expect(document.body.textContent).not.toContain("anna_t");
  });

  it("shows a friendly empty state for a space without messages", async () => {
    signIn(makeMe({ class_code: "9A" }));
    serve({ "/class-spaces/me": state(), "/class-spaces/1001/messages": history([]) });
    renderApp(<ClassSpacePage />, "/app/class-space");
    expect(await screen.findByText("Még nincs üzenet. Írj elsőként az osztályodnak!")).toBeInTheDocument();
  });

  it("reports an unavailable space when the class is gone or the request fails", async () => {
    signIn(makeMe({ class_code: "9A" }));
    serve({ "/class-spaces/me": state({ class: null, member: false, prompt_required: false, show_username: null, alias: null, members: null }) });
    const view = renderApp(<ClassSpacePage />, "/app/class-space");
    expect(await screen.findByText("Az osztálytér most nem érhető el.")).toBeInTheDocument();
    view.unmount();
    serve({});
    renderApp(<ClassSpacePage />, "/app/class-space");
    expect(await screen.findByText("Az osztálytér most nem érhető el.")).toBeInTheDocument();
  });

  it("marks the newest message as read shortly after opening the space", async () => {
    signIn(makeMe({ class_code: "9A" }));
    serve({
      "/class-spaces/me": state({ unread: 2 }),
      "/class-spaces/1001/messages": history([entry({ id: "20" }), entry({ id: "21", content: "Második üzenet" })]),
    });
    mocked.post.mockResolvedValue({ status: "ok" });
    renderApp(<ClassSpacePage />, "/app/class-space");
    await screen.findByText("Második üzenet");
    await waitFor(() => expect(mocked.post).toHaveBeenCalledWith("/class-spaces/1001/read", { message_id: "21" }), { timeout: 3000 });
  });

  it("does not mark anything as read while the page is hidden", async () => {
    setVisibility("hidden");
    signIn(makeMe({ class_code: "9A" }));
    serve({ "/class-spaces/me": state({ unread: 2 }), "/class-spaces/1001/messages": history([entry({ id: "20" })]) });
    renderApp(<ClassSpacePage />, "/app/class-space");
    await screen.findByText("Holnap dolgozat lesz.");
    await new Promise((resolve) => setTimeout(resolve, 700));
    expect(mocked.post).not.toHaveBeenCalled();
  });

  it("does not mark anything as read when nothing is unread", async () => {
    signIn(makeMe({ class_code: "9A" }));
    serve({ "/class-spaces/me": state({ unread: 0 }), "/class-spaces/1001/messages": history([entry({ id: "20" })]) });
    renderApp(<ClassSpacePage />, "/app/class-space");
    await screen.findByText("Holnap dolgozat lesz.");
    await new Promise((resolve) => setTimeout(resolve, 700));
    expect(mocked.post).not.toHaveBeenCalled();
  });

  it("sends a message with Enter and clears the box", async () => {
    signIn(makeMe({ class_code: "9A" }));
    serve({ "/class-spaces/me": state(), "/class-spaces/1001/messages": history([]) });
    mocked.post.mockResolvedValue(entry({ mine: true, author: eva, content: "Sziasztok" }));
    renderApp(<ClassSpacePage />, "/app/class-space");
    const box = await screen.findByRole("textbox", { name: "Üzenet az osztálynak" });
    fireEvent.change(box, { target: { value: "Sziasztok" } });
    fireEvent.keyDown(box, { key: "Enter" });
    await waitFor(() => expect(mocked.post).toHaveBeenCalledWith("/class-spaces/1001/messages", { content: "Sziasztok" }));
    await waitFor(() => expect(box).toHaveValue(""));
  });

  it("keeps Shift+Enter for new lines and ignores empty messages", async () => {
    signIn(makeMe({ class_code: "9A" }));
    serve({ "/class-spaces/me": state(), "/class-spaces/1001/messages": history([]) });
    renderApp(<ClassSpacePage />, "/app/class-space");
    const box = await screen.findByRole("textbox", { name: "Üzenet az osztálynak" });
    fireEvent.keyDown(box, { key: "Enter" });
    fireEvent.change(box, { target: { value: "sor" } });
    fireEvent.keyDown(box, { key: "Enter", shiftKey: true });
    expect(mocked.post).not.toHaveBeenCalled();
  });

  it("deletes an own message after confirmation", async () => {
    signIn(makeMe({ class_code: "9A" }));
    serve({ "/class-spaces/me": state(), "/class-spaces/1001/messages": history([entry({ id: "30", author: eva, mine: true, content: "Elírtam" })]) });
    mocked.del.mockResolvedValue({ status: "deleted" });
    renderApp(<ClassSpacePage />, "/app/class-space");
    await screen.findByText("Elírtam");
    fireEvent.click(screen.getByRole("button", { name: "Üzenet törlése" }));
    const dialog = await screen.findByRole("dialog");
    expect(mocked.del).not.toHaveBeenCalled();
    fireEvent.click(within(dialog).getByRole("button", { name: "Üzenet törlése" }));
    await waitFor(() => expect(mocked.del).toHaveBeenCalledWith("/class-spaces/1001/messages/30"));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("reports another member’s message to the school moderators", async () => {
    signIn(makeMe({ class_code: "9A" }));
    serve({ "/class-spaces/me": state(), "/class-spaces/1001/messages": history([entry({ id: "31", author: null, alias: "77aa10", content: "Bántó üzenet" })]) });
    mocked.post.mockResolvedValue({ report: { id: "5" } });
    renderApp(<ClassSpacePage />, "/app/class-space");
    await screen.findByText("Bántó üzenet");
    fireEvent.click(screen.getByRole("button", { name: "Üzenet jelentése" }));
    const dialog = await screen.findByRole("dialog", { name: "Üzenet jelentése" });
    expect(within(dialog).queryByRole("switch")).not.toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: "Jelentés küldése" }));
    await waitFor(() =>
      expect(mocked.post).toHaveBeenCalledWith("/class-spaces/1001/messages/31/report", { reason: "harassment", details: "", escalate: false }),
    );
  });

  it("opens the member list from the header", async () => {
    signIn(makeMe({ class_code: "9A" }));
    serve({
      "/class-spaces/me": state(),
      "/class-spaces/1001/messages": history([]),
      "/class-spaces/1001/members": { class: school, members: [{ user: anna, mine: false, show_username: true }], hidden_count: 1, total: 2 },
    });
    renderApp(<ClassSpacePage />, "/app/class-space");
    fireEvent.click(await screen.findByRole("button", { name: "Tagok: 3" }));
    const dialog = await screen.findByRole("dialog", { name: "Az osztálytér tagjai (9A)" });
    expect(await within(dialog).findByText("@anna_t")).toBeInTheDocument();
    expect(mocked.get).toHaveBeenCalledWith("/class-spaces/1001/members");
  });
});

describe("class space setting", () => {
  it("shows the current choice and saves a change", async () => {
    signIn(makeMe({ class_code: "9A" }));
    serve({ "/class-spaces/me": state({ show_username: true }) });
    mocked.put.mockResolvedValue(state({ show_username: false }));
    renderApp(<ClassSpaceSetting />);
    const select = await screen.findByRole("combobox", { name: "Felhasználónevem megjelenítése az osztálytérben" });
    expect(select).toHaveValue("show");
    expect(screen.queryByRole("option", { name: "Még nem döntöttem" })).not.toBeInTheDocument();
    fireEvent.change(select, { target: { value: "hide" } });
    await waitFor(() => expect(mocked.put).toHaveBeenCalledWith("/class-spaces/me/visibility", { show_username: false }));
    await waitFor(() => expect(select).toHaveValue("hide"));
    await waitFor(() => expect(useUi.getState().toasts).toHaveLength(1));
  });

  it("offers an undecided option until the user answers and then joins on the first choice", async () => {
    signIn(makeMe({ class_code: "9A" }));
    serve({ "/class-spaces/me": required });
    mocked.put.mockResolvedValue(state({ show_username: true }));
    renderApp(<ClassSpaceSetting />);
    const select = await screen.findByRole("combobox", { name: "Felhasználónevem megjelenítése az osztálytérben" });
    expect(select).toHaveValue("");
    expect(screen.getByRole("option", { name: "Még nem döntöttem" })).toBeInTheDocument();
    fireEvent.change(select, { target: { value: "show" } });
    await waitFor(() => expect(mocked.put).toHaveBeenCalledWith("/class-spaces/me/visibility", { show_username: true }));
    await waitFor(() => expect(select).toHaveValue("show"));
    expect(screen.queryByRole("option", { name: "Még nem döntöttem" })).not.toBeInTheDocument();
  });

  it("shows the server error when saving fails and keeps the old choice", async () => {
    signIn(makeMe({ class_code: "9A" }));
    serve({ "/class-spaces/me": state({ show_username: true }) });
    mocked.put.mockRejectedValue(new ApiError(429, "rate_limited", "x"));
    renderApp(<ClassSpaceSetting />);
    const select = await screen.findByRole("combobox", { name: "Felhasználónevem megjelenítése az osztálytérben" });
    fireEvent.change(select, { target: { value: "hide" } });
    expect(await screen.findByRole("alert")).toHaveTextContent(translate("errors.rate_limited"));
    expect(select).toHaveValue("show");
  });

  it("asks users without a class to set one first and does not query the server", () => {
    signIn(makeMe());
    renderApp(<ClassSpaceSetting />);
    expect(screen.getByText("Az osztálytér beállításához előbb add meg az osztályodat.")).toBeInTheDocument();
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
    expect(mocked.get).not.toHaveBeenCalled();
  });
});

describe("home sidebar entry", () => {
  const home = {
    "/dms": [],
    "/friends/requests": { incoming: [], outgoing: [] },
    "/dok/inbox": { threads: [], unread: 0, send: { allowed: false, targets: [] } },
  };

  it("links to the class space and shows the unread count", async () => {
    signIn(makeMe({ class_code: "9A" }));
    serve({ ...home, "/class-spaces/me": state({ unread: 4 }) });
    renderApp(<HomeSidebar />, "/app");
    const link = await screen.findByRole("link", { name: /^Osztálytér\s*4$/ });
    expect(link).toHaveAttribute("href", "/app/class-space");
  });

  it("keeps the entry for users without a class without asking the server about it", async () => {
    signIn(makeMe());
    serve(home);
    renderApp(<HomeSidebar />, "/app");
    const link = await screen.findByRole("link", { name: "Osztálytér" });
    expect(link).toHaveAttribute("href", "/app/class-space");
    expect(mocked.get).not.toHaveBeenCalledWith("/class-spaces/me");
  });
});

describe("class space translations", () => {
  it("provides every class space string in Hungarian, English and German", () => {
    const keys = Object.keys(hu.classSpace).sort();
    expect(keys.length).toBeGreaterThan(30);
    expect(Object.keys(en.classSpace).sort()).toEqual(keys);
    expect(Object.keys(de.classSpace).sort()).toEqual(keys);
    expect([hu.nav.class_space, en.nav.class_space, de.nav.class_space]).toEqual(["Osztálytér", "Class space", "Klassenraum"]);
  });

  it("uses translated labels for the privacy-preserving author name", () => {
    expect(hu.classSpace.anonymous).toBe("Osztálytárs");
    expect(en.classSpace.anonymous).toBe("Classmate");
    expect(de.classSpace.anonymous).toBe("Mitschüler");
    for (const catalog of [hu, en, de]) {
      expect(catalog.classSpace.anonymous_alias).toContain("{{alias}}");
    }
  });

  it("explains in every language that the class is self-declared", () => {
    expect(hu.classSpace.prompt_note).toContain("nem ellenőrzi");
    expect(en.classSpace.prompt_note).toContain("does not verify");
    expect(de.classSpace.prompt_note).toContain("überprüft sie nicht");
  });
});
