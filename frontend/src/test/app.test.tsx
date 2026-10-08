import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/client")>();
  return { ...actual, api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), del: vi.fn(), upload: vi.fn() } };
});

import { ApiError, api } from "../api/client";
import type { Message } from "../api/types";
import { Composer } from "../components/chat/Composer";
import { MessageItem } from "../components/chat/MessageItem";
import { CopyId } from "../components/CopyId";
import { Modal } from "../components/Modal";
import { setLanguage } from "../i18n";
import { LandingPage } from "../pages/auth/LandingPage";
import { KretaVerifier } from "../pages/auth/KretaVerifier";
import { LoginPage } from "../pages/auth/LoginPage";
import { useAuth } from "../store/auth";
import { useUi } from "../store/ui";
import { ThemeProvider } from "../theme/ThemeProvider";
import { makeMe, renderApp, resetLanguage, signIn, signOut } from "./helpers";

const mocked = vi.mocked(api);

beforeEach(() => {
  resetLanguage();
  signOut();
  Object.values(mocked).forEach((fn) => fn.mockReset());
  useUi.setState({ toasts: [] });
});

afterEach(() => {
  resetLanguage();
});

describe("landing page", () => {
  it("is Hungarian by default and offers sign in and registration", () => {
    renderApp(<LandingPage />);
    expect(screen.getByRole("link", { name: "Bejelentkezés" })).toHaveAttribute("href", "/login");
    expect(screen.getByRole("link", { name: "Regisztráció" })).toHaveAttribute("href", "/register");
    expect(document.documentElement.lang).toBe("hu");
  });

  it("switches the whole page between Hungarian, English and German", async () => {
    renderApp(<LandingPage />);
    await act(async () => setLanguage("en"));
    expect(screen.getByRole("link", { name: "Sign in" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Register" })).toBeInTheDocument();
    await act(async () => setLanguage("de"));
    expect(screen.getByRole("link", { name: "Anmelden" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Registrieren" })).toBeInTheDocument();
    expect(document.documentElement.lang).toBe("de");
  });

  it("lets the visitor change language with an accessible selector", async () => {
    const user = userEvent.setup();
    renderApp(<LandingPage />);
    await user.selectOptions(screen.getByLabelText("Nyelv"), "en");
    expect(screen.getByRole("link", { name: "Sign in" })).toBeInTheDocument();
  });
});

describe("E-Kréta verification", () => {
  async function submitCredentials(user: ReturnType<typeof userEvent.setup>) {
    await user.type(screen.getByLabelText("E-Kréta felhasználónév"), "diak1");
    await user.type(screen.getByLabelText("E-Kréta jelszó"), "titkos-jelszo");
    await user.click(screen.getByRole("button", { name: "Azonosítás az E-Krétával" }));
  }

  it("asks “Te vagy …?” and continues only after the person confirms", async () => {
    const user = userEvent.setup();
    const onConfirmed = vi.fn();
    mocked.post.mockResolvedValueOnce({ status: "identified", full_name: "Kiss Éva", resume: false });
    renderApp(<KretaVerifier intent="register" onConfirmed={onConfirmed} />);
    await submitCredentials(user);
    expect(await screen.findByText("Te vagy Kiss Éva?")).toBeInTheDocument();
    expect(mocked.post).toHaveBeenCalledWith("/auth/kreta/start", { intent: "register", username: "diak1", password: "titkos-jelszo" });
    expect(onConfirmed).not.toHaveBeenCalled();
    mocked.post.mockResolvedValueOnce({ status: "confirmed" });
    await user.click(screen.getByRole("button", { name: "Igen" }));
    await waitFor(() => expect(onConfirmed).toHaveBeenCalledOnce());
    expect(mocked.post).toHaveBeenLastCalledWith("/auth/kreta/confirm", { confirmed: true });
    expect(screen.queryByText(/Kiss Éva/)).not.toBeInTheDocument();
  });

  it("restarts with empty fields when the person answers “Nem”", async () => {
    const user = userEvent.setup();
    const onConfirmed = vi.fn();
    mocked.post.mockResolvedValueOnce({ status: "identified", full_name: "Nagy Péter", resume: false });
    renderApp(<KretaVerifier intent="register" onConfirmed={onConfirmed} />);
    await submitCredentials(user);
    await screen.findByText("Te vagy Nagy Péter?");
    mocked.post.mockResolvedValueOnce({ status: "cancelled" });
    await user.click(screen.getByRole("button", { name: "Nem" }));
    expect(await screen.findByLabelText("E-Kréta jelszó")).toHaveValue("");
    expect(mocked.post).toHaveBeenLastCalledWith("/auth/kreta/confirm", { confirmed: false });
    expect(onConfirmed).not.toHaveBeenCalled();
    expect(screen.queryByText(/Nagy Péter/)).not.toBeInTheDocument();
  });

  it("shows a two-factor input when E-Kréta asks for it", async () => {
    const user = userEvent.setup();
    mocked.post.mockResolvedValueOnce({ status: "two_factor_required" });
    renderApp(<KretaVerifier intent="register" onConfirmed={vi.fn()} />);
    await submitCredentials(user);
    const code = await screen.findByLabelText("E-Kréta kétlépcsős kód");
    await user.type(code, "12a3456");
    expect(code).toHaveValue("123456");
    mocked.post.mockResolvedValueOnce({ status: "identified", full_name: "Tóth Anna", resume: false });
    await user.click(screen.getByRole("button", { name: "Tovább" }));
    expect(await screen.findByText("Te vagy Tóth Anna?")).toBeInTheDocument();
    expect(mocked.post).toHaveBeenLastCalledWith("/auth/kreta/two-factor", { code: "123456" });
  });

  it("shows translated, accessible errors and never keeps the password", async () => {
    const user = userEvent.setup();
    mocked.post.mockRejectedValueOnce(new ApiError(401, "kreta_invalid_credentials", "x"));
    renderApp(<KretaVerifier intent="register" onConfirmed={vi.fn()} />);
    await submitCredentials(user);
    expect(await screen.findByRole("alert")).toHaveTextContent("Hibás E-Kréta felhasználónév vagy jelszó.");
  });
});

describe("login", () => {
  it("identifies the sign-in method first and greets the person by display name", async () => {
    const user = userEvent.setup();
    mocked.post.mockResolvedValueOnce({ method: "totp" });
    renderApp(<LoginPage />, "/login");
    await user.type(screen.getByLabelText("Felhasználónév"), "eva_k");
    await user.click(screen.getByRole("button", { name: "Tovább" }));
    const code = await screen.findByLabelText("Hitelesítő kód");
    expect(code).toHaveAttribute("autocomplete", "one-time-code");
    mocked.post.mockResolvedValueOnce({ user: makeMe() });
    await user.type(code, "123456");
    await user.click(screen.getByRole("button", { name: "Bejelentkezés" }));
    await waitFor(() => expect(useAuth.getState().status).toBe("authenticated"));
    expect(mocked.post).toHaveBeenLastCalledWith("/auth/login", { username: "eva_k", secret: "123456" });
    expect(useUi.getState().toasts.at(-1)?.message).toBe("Üdv, Éva!");
  });

  it("shows the password field for password accounts and a localized error for bad credentials", async () => {
    const user = userEvent.setup();
    mocked.post.mockResolvedValueOnce({ method: "password" });
    renderApp(<LoginPage />, "/login");
    await user.type(screen.getByLabelText("Felhasználónév"), "eva_k");
    await user.click(screen.getByRole("button", { name: "Tovább" }));
    const password = await screen.findByLabelText("Jelszó");
    expect(password).toHaveAttribute("type", "password");
    mocked.post.mockRejectedValueOnce(new ApiError(401, "invalid_credentials", "x"));
    await user.type(password, "rossz-jelszo");
    await user.click(screen.getByRole("button", { name: "Bejelentkezés" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Hibás felhasználónév vagy jelszó/kód.");
    expect(screen.getByLabelText("Jelszó")).toHaveValue("");
    expect(useAuth.getState().status).toBe("anonymous");
  });
});

describe("composer", () => {
  it("suggests members after @ and sends mention tokens instead of names", async () => {
    const user = userEvent.setup();
    const onSend = vi.fn().mockResolvedValue(undefined);
    render(
      <Composer
        placeholder="Üzenet"
        disabledReason={null}
        maxLength={4000}
        typingTarget={{ scope: "channel", id: "9" }}
        replyTo={null}
        onCancelReply={() => undefined}
        onSend={onSend}
        candidates={[{ id: "5", name: "Anna", avatarUrl: null }, { id: "6", name: "Bence", avatarUrl: null }]}
      />,
    );
    const box = screen.getByRole("textbox");
    await user.type(box, "Szia @An");
    expect(screen.getByRole("option", { name: /Anna/ })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: /Bence/ })).not.toBeInTheDocument();
    await user.keyboard("{Enter}");
    expect(box).toHaveValue("Szia @Anna ");
    await user.type(box, "ok");
    await user.click(screen.getByRole("button", { name: "Küldés" }));
    expect(onSend).toHaveBeenCalledWith("Szia <@5> ok", null);
  });

  it("explains why sending is impossible and blocks input", () => {
    render(
      <Composer placeholder="Üzenet" disabledReason="Időkorlátozás alatt állsz." maxLength={10} typingTarget={{ scope: "dm", id: "1" }} replyTo={null} onCancelReply={() => undefined} onSend={vi.fn()} candidates={[]} />,
    );
    expect(screen.getByRole("textbox")).toBeDisabled();
    expect(screen.getByPlaceholderText("Időkorlátozás alatt állsz.")).toBeInTheDocument();
  });
});

describe("messages", () => {
  const base: Message = {
    id: "10",
    scope: "channel",
    channel_id: "1",
    conversation_id: null,
    author: { id: "2", username: "anna_t", display_name: "Anna", avatar_url: null, staff: false },
    content: "",
    deleted: false,
    created_at: "2026-01-01T10:00:00+00:00",
    reply_to: null,
    pinned: false,
    reactions: [],
  };
  const props = {
    compact: false,
    names: { "2": "Anna", "3": "Bence" },
    reactions: ["👍"],
    canReact: true,
    canDelete: false,
    canPin: false,
    canReport: true,
    onReply: vi.fn(),
    onReact: vi.fn(),
    onDelete: vi.fn(),
    onPin: vi.fn(),
    onReport: vi.fn(),
  };

  it("renders message content as inert text, never as markup", () => {
    signIn();
    const hostile = '<img src=x onerror="alert(1)"><script>alert(1)</script> https://example.com/x javascript:alert(1)';
    const { container } = render(<MessageItem {...props} message={{ ...base, content: hostile }} />);
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("script")).toBeNull();
    const links = container.querySelectorAll("a");
    expect(links).toHaveLength(1);
    expect(links[0]).toHaveAttribute("href", "https://example.com/x");
    expect(links[0]).toHaveAttribute("rel", expect.stringContaining("noopener"));
    expect(container.textContent).toContain("<script>alert(1)</script>");
  });

  it("shows mention tokens as names and highlights mentions of the viewer", () => {
    signIn(makeMe({ id: "3" }));
    const { container } = render(<MessageItem {...props} message={{ ...base, content: "Szia <@3>, és <@999>" }} />);
    expect(screen.getByRole("button", { name: "@Bence" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "@ismeretlen" })).toBeInTheDocument();
    expect(container.querySelector(".message--mention")).not.toBeNull();
  });

  it("offers delete only for own messages or moderators and report only for others", () => {
    signIn(makeMe({ id: "2" }));
    const own = render(<MessageItem {...props} message={{ ...base, content: "enyém" }} />);
    expect(within(own.container).queryByRole("button", { name: "Üzenet jelentése" })).toBeNull();
    expect(within(own.container).getByRole("button", { name: "Üzenet törlése" })).toBeInTheDocument();
    own.unmount();
    signIn(makeMe({ id: "9" }));
    const other = render(<MessageItem {...props} message={{ ...base, content: "másé" }} />);
    expect(within(other.container).getByRole("button", { name: "Üzenet jelentése" })).toBeInTheDocument();
    expect(within(other.container).queryByRole("button", { name: "Üzenet törlése" })).toBeNull();
  });

  it("shows a placeholder for deleted messages", () => {
    signIn();
    render(<MessageItem {...props} message={{ ...base, deleted: true, content: null }} />);
    expect(screen.getByText("Ez az üzenet törölve lett.")).toBeInTheDocument();
  });
});

describe("accessibility primitives", () => {
  it("modal is labelled, traps focus, and closes on Escape", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(
      <Modal title="Teszt ablak" onClose={onClose}>
        <button type="button">Első</button>
        <button type="button">Második</button>
      </Modal>,
    );
    const dialog = screen.getByRole("dialog", { name: "Teszt ablak" });
    expect(dialog).toHaveAttribute("aria-modal", "true");
    const buttons = within(dialog).getAllByRole("button");
    expect(dialog.contains(document.activeElement)).toBe(true);
    buttons.at(-1)?.focus();
    await user.tab();
    expect(dialog.contains(document.activeElement)).toBe(true);
    await user.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalled();
  });

  it("developer mode reveals technical ids with copy buttons and nothing otherwise", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    signIn(makeMe({}, { developer_mode: false }));
    const { rerender } = render(<CopyId value="12345" label="Felhasználói azonosító" />);
    expect(screen.queryByText("12345")).not.toBeInTheDocument();
    act(() => signIn(makeMe({}, { developer_mode: true })));
    rerender(<CopyId value="12345" label="Felhasználói azonosító" />);
    const chip = screen.getByRole("button", { name: "Felhasználói azonosító másolása" });
    fireEvent.click(chip);
    await waitFor(() => expect(writeText).toHaveBeenCalledWith("12345"));
  });
});

describe("theme provider", () => {
  function renderTheme() {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    return render(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <ThemeProvider>
            <p>tartalom</p>
          </ThemeProvider>
        </MemoryRouter>
      </QueryClientProvider>,
    );
  }

  it("applies light, dark and system themes", async () => {
    signIn(makeMe({}, { theme_mode: "dark" }));
    renderTheme();
    expect(document.documentElement.dataset.theme).toBe("dark");
    act(() => signIn(makeMe({}, { theme_mode: "light" })));
    await waitFor(() => expect(document.documentElement.dataset.theme).toBe("light"));
    act(() => signIn(makeMe({}, { theme_mode: "system" })));
    await waitFor(() => expect(document.documentElement.dataset.themeMode).toBe("system"));
  });

  it("injects sanitized custom css as text and removes it again", async () => {
    const css = ".user-css-scope .message {\n  color: #123456;\n}";
    signIn(makeMe({}, { custom_css: css }));
    renderTheme();
    const style = document.getElementById("user-custom-css");
    expect(style?.tagName).toBe("STYLE");
    expect(style?.textContent).toBe(css);
    act(() => signIn(makeMe({}, { custom_css: "" })));
    await waitFor(() => expect(document.getElementById("user-custom-css")).toBeNull());
  });

  it("applies chat appearance preferences", () => {
    signIn(makeMe({}, { chat_appearance: { density: "compact", font_scale: 120, show_timestamps: false } }));
    renderTheme();
    expect(document.documentElement.dataset.density).toBe("compact");
    expect(document.documentElement.style.getPropertyValue("--chat-scale")).toBe("1.2");
    expect(document.documentElement.dataset.timestamps).toBe("false");
  });
});
