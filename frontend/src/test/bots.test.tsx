import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/client")>();
  return { ...actual, request: vi.fn(), api: { ...actual.api, get: vi.fn(), post: vi.fn(), patch: vi.fn(), del: vi.fn(), upload: vi.fn() } };
});

import { ApiError, api, request } from "../api/client";
import type { BotApplication, BotCommand, ServerDetail } from "../api/types";
import { BotBadge } from "../components/BotBadge";
import { Composer } from "../components/chat/Composer";
import { BotsSection } from "../pages/settings/BotsSection";
import { ServerSettings } from "../pages/server/ServerSettings";
import { BotsPanel } from "../pages/server/panels/BotsPanel";
import { PERMISSION_BITS } from "../utils/permissions";
import { makeMe, renderApp, resetLanguage, signIn } from "./helpers";

const mocked = vi.mocked(api);
const bot: BotApplication = {
  bot_id: "2001", created_at: "2026-01-01T10:00:00Z", install_code: "2001",
  user: { ...makeMe({ id: "2001", username: "helper_bot", display_name: "Helper", is_bot: true }), presence: null, last_seen_at: null, mutual_friends: null, relation: null },
};
const command: BotCommand = { id: "4001", bot_id: bot.bot_id, name: "ping", description: "Ping the bot", options: [], default_member_permissions: 0, bot: bot.user };
const server = { id: "7", name: "Server", is_owner: true, my_permissions: 262143, roles: [], channels: [], categories: [], moderation_settings: {}, owner_id: "1001" } as unknown as ServerDetail;

beforeEach(() => {
  vi.resetAllMocks();
  resetLanguage();
  signIn();
  mocked.get.mockResolvedValue([]);
});

function composerProps(scope: "channel" | "dm" = "channel") {
  return { placeholder: "Üzenet", disabledReason: null, maxLength: 4000, typingTarget: { scope, id: "9" }, replyTo: null, onCancelReply: vi.fn(), onSend: vi.fn().mockResolvedValue(undefined), candidates: [] };
}

describe("bot identity and developer management", () => {
  it("always displays the bot badge without developer mode", () => {
    const { rerender } = render(<BotBadge isBot />);
    expect(screen.getByLabelText("BOT")).toBeInTheDocument();
    rerender(<BotBadge isBot={false} />);
    expect(screen.queryByText("BOT")).toBeNull();
  });

  it("creates with an owner password and discards the one-time token on close", async () => {
    mocked.get.mockResolvedValue([]);
    mocked.post.mockResolvedValue({ ...bot, token: "one-time-secret" });
    renderApp(<BotsSection />);
    await waitFor(() => expect(screen.getByRole("button", { name: "Bot létrehozása" })).toBeEnabled());
    await userEvent.click(screen.getByRole("button", { name: "Bot létrehozása" }));
    const dialog = screen.getByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText("Bot felhasználóneve"), { target: { value: "helper_bot" } });
    fireEvent.change(within(dialog).getByLabelText("Bot megjelenített neve"), { target: { value: "Helper" } });
    fireEvent.change(within(dialog).getByLabelText("Tulajdonosi jelszó"), { target: { value: "owner-password" } });
    await userEvent.click(within(dialog).getByRole("button", { name: "Bot létrehozása" }));
    expect(mocked.post).toHaveBeenCalledWith("/me/bots", { username: "helper_bot", display_name: "Helper", password: "owner-password" });
    expect(await screen.findByDisplayValue("one-time-secret")).toBeInTheDocument();
    expect(screen.queryByDisplayValue("owner-password")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Elmentettem, bezárás" }));
    expect(screen.queryByDisplayValue("one-time-secret")).toBeNull();
  });

  it("edits profiles and requires password plus exact username before deletion", async () => {
    mocked.get.mockResolvedValue([bot]);
    mocked.patch.mockResolvedValue(bot);
    mocked.del.mockResolvedValue({ status: "deleted" });
    renderApp(<BotsSection />);
    await userEvent.click(await screen.findByRole("button", { name: "Botprofil szerkesztése" }));
    let dialog = screen.getByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText("Bot megjelenített neve"), { target: { value: "New helper" } });
    await userEvent.click(within(dialog).getByRole("button", { name: "Botprofil szerkesztése" }));
    await waitFor(() => expect(mocked.patch).toHaveBeenCalledWith("/me/bots/2001", { username: "helper_bot", display_name: "New helper" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    await userEvent.click(screen.getByRole("button", { name: "Bot törlése" }));
    dialog = screen.getByRole("dialog");
    const remove = within(dialog).getByRole("button", { name: "Bot törlése" });
    expect(remove).toBeDisabled();
    fireEvent.change(within(dialog).getByLabelText("Írd be a törléshez: helper_bot"), { target: { value: "helper_bot" } });
    fireEvent.change(within(dialog).getByLabelText("Tulajdonosi jelszó"), { target: { value: "password" } });
    await userEvent.click(remove);
    await waitFor(() => expect(mocked.del).toHaveBeenCalledWith("/me/bots/2001", { password: "password", confirm_username: "helper_bot" }));
  });

  it("explains reveal rotation and shows localized password errors without revealing a token", async () => {
    mocked.get.mockResolvedValue([bot]);
    mocked.post.mockRejectedValue(new ApiError(401, "invalid_credentials", "invalid"));
    renderApp(<BotsSection />);
    await userEvent.click(await screen.findByRole("button", { name: "Új token megjelenítése" }));
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByText(/új tokent hoz létre/)).toBeInTheDocument();
    fireEvent.change(within(dialog).getByLabelText("Tulajdonosi jelszó"), { target: { value: "wrong" } });
    await userEvent.click(within(dialog).getByRole("button", { name: "Új token megjelenítése" }));
    expect(mocked.post).toHaveBeenCalledWith("/me/bots/2001/token/reveal", { password: "wrong" });
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.queryByLabelText("Bottoken")).toBeNull();
  });

  it("blocks a fourth bot and hides developer bots for bot identities", async () => {
    mocked.get.mockResolvedValue([bot, { ...bot, bot_id: "2" }, { ...bot, bot_id: "3" }]);
    const result = renderApp(<BotsSection />);
    await screen.findAllByText("Helper");
    expect(screen.getByRole("button", { name: "Bot létrehozása" })).toBeDisabled();
    result.unmount();
    mocked.get.mockClear();
    signIn(makeMe({ is_bot: true }));
    renderApp(<BotsSection />);
    expect(screen.queryByText("Botok")).toBeNull();
    expect(mocked.get).not.toHaveBeenCalled();
  });
});

describe("server integrations", () => {
  it("gates the integration panel and tab on the real Administrator flag", () => {
    const regular = { ...server, is_owner: false, my_permissions: PERMISSION_BITS.manage_server };
    const result = renderApp(<BotsPanel server={regular} />);
    expect(mocked.get).not.toHaveBeenCalled();
    expect(screen.queryByText("Integrációk · Botok")).toBeNull();
    result.unmount();
    renderApp(<ServerSettings server={regular} onClose={vi.fn()} />);
    expect(screen.queryByRole("tab", { name: "Integrációk · Botok" })).toBeNull();
  });

  it("defaults to view, history and send and submits only the checked grants", async () => {
    mocked.get.mockResolvedValue({ bots: [], available_permissions: ["view_channel", "read_message_history", "send_messages", "kick_members", "ban_members", "manage_roles"], default_permissions: ["view_channel", "read_message_history", "send_messages"] });
    mocked.post.mockResolvedValue({ status: "installed" });
    renderApp(<BotsPanel server={{ ...server, is_owner: false, my_permissions: PERMISSION_BITS.administrator }} />);
    await screen.findByRole("checkbox", { name: "Tagok kirúgása" });
    const checks = screen.getAllByRole("checkbox");
    expect(checks.map((check) => (check as HTMLInputElement).checked)).toEqual([true, true, true, false, false, false]);
    fireEvent.change(screen.getByLabelText("Telepítési kód (botazonosító)"), { target: { value: "2001" } });
    await userEvent.click(checks[2]);
    await userEvent.click(screen.getByRole("button", { name: "Bot telepítésének megerősítése" }));
    expect(mocked.post).toHaveBeenCalledWith("/servers/7/bots", { bot_id: "2001", permissions: ["view_channel", "read_message_history"] });
  });
});

describe("server-only slash composer", () => {
  it("loads this channel's installed commands and invokes from keyboard without sending slash text", async () => {
    mocked.get.mockResolvedValue([command]);
    vi.mocked(request).mockResolvedValue({ id: "88" });
    const props = composerProps();
    render(<Composer {...props} />);
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "/pi", selectionStart: 3 } });
    await screen.findByRole("option");
    expect(mocked.get).toHaveBeenCalledWith("/channels/9/bot-commands", undefined, expect.any(AbortSignal));
    fireEvent.keyDown(screen.getByRole("textbox"), { key: "Enter" });
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByLabelText("BOT")).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Parancs futtatása" }));
    await waitFor(() => expect(request).toHaveBeenCalledWith("/channels/9/interactions", expect.objectContaining({ method: "POST", body: { command_id: "4001", options: {} } })));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(screen.getByRole("textbox")).toHaveValue("");
    expect(props.onSend).not.toHaveBeenCalled();
  });

  it("never queries bot commands for DMs", () => {
    render(<Composer {...composerProps("dm")} />);
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "/ping" } });
    expect(mocked.get).not.toHaveBeenCalled();
    expect(screen.queryByRole("listbox")).toBeNull();
  });

  it("renders timeout errors and clears the pending state", async () => {
    mocked.get.mockResolvedValue([command]);
    vi.mocked(request).mockRejectedValue(new ApiError(504, "bot_interaction_timeout", "timeout"));
    render(<Composer {...composerProps()} />);
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "/" } });
    await userEvent.click(within(await screen.findByRole("option")).getByRole("button"));
    await userEvent.click(screen.getByRole("button", { name: "Parancs futtatása" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("három másodpercen belül");
    expect(screen.getByRole("button", { name: "Parancs futtatása" })).toBeEnabled();
    expect(screen.queryByRole("status")).toBeNull();
  });
});
