import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/client")>();
  return { ...actual, api: { ...actual.api, get: vi.fn(), post: vi.fn(), del: vi.fn(), upload: vi.fn() } };
});

import { ApiError, api } from "../api/client";
import { loadGiphy, searchGiphy } from "../api/giphy";
import type { Attachment, MediaConfig } from "../api/types";
import { SafeLink } from "../components/SafeLink";
import { Composer } from "../components/chat/Composer";
import { GiphyPicker } from "../components/chat/GiphyPicker";
import { LinkEmbeds, MessageMedia } from "../components/chat/MessageMedia";
import { RichText } from "../components/chat/RichText";
import { ClassSpaceText } from "../components/classspace/ClassSpaceText";
import { DokText } from "../components/dok/DokText";
import { isExternalUrl, useLinkPolicy } from "../utils/links";
import { renderApp, resetLanguage, signIn } from "./helpers";

const mockApi = vi.mocked(api);
const config: MediaConfig = { public_origin: "https://chat.school.hu", max_attachment_bytes: 20_000_000, max_attachments: 10, giphy_api_key: null, giphy_rating: "pg" };
const attachment: Attachment = { id: "123", filename: "órarend.pdf", size_bytes: 1000, mime_type: "application/pdf", kind: "file", url: "/api/v1/uploads/attachments/123" };
const giphy = {
  id: "SchoolGif", title: "Happy school", rating: "pg", username: "SchoolArtist",
  images: { downsized: { url: "https://media.giphy.com/media/SchoolGif/giphy.gif?cid=keep" }, fixed_width_small: { url: "https://media1.giphy.com/media/SchoolGif/100w.gif" } },
};

beforeEach(() => {
  vi.clearAllMocks();
  resetLanguage();
  signIn();
  useLinkPolicy.setState({ publicOrigin: "https://chat.school.hu" });
  mockApi.get.mockResolvedValue(config);
  mockApi.del.mockResolvedValue({ status: "deleted" });
});

afterEach(() => {
  vi.unstubAllGlobals();
  useLinkPolicy.setState({ publicOrigin: null });
});

function composerProps() {
  return {
    placeholder: "Üzenet", disabledReason: null, maxLength: 4000, typingTarget: { scope: "channel" as const, id: "9" },
    replyTo: null, onCancelReply: vi.fn(), onSend: vi.fn().mockResolvedValue(undefined), candidates: [], mediaConfig: config,
  };
}

describe("external link warnings", () => {
  it("compares parsed origins including scheme and port", () => {
    expect(isExternalUrl("https://chat.school.hu/app", config.public_origin)).toBe(false);
    for (const url of ["http://chat.school.hu/app", "https://chat.school.hu:8443/app", "https://chat.school.hu.evil.com", "https://chat.school.hu@evil.com"] ) {
      expect(isExternalUrl(url, config.public_origin)).toBe(true);
    }
  });

  it.each(["chat", "dok", "class-space"])("warns before activating %s links and supports cancel, keyboard, and focus trapping", async (scope) => {
    const user = userEvent.setup();
    const content = "https://example.com/test";
    render(scope === "chat" ? <RichText content={content} names={{}} /> : scope === "dok" ? <DokText content={content} /> : <ClassSpaceText content={content} />);
    const link = screen.getByRole("link", { name: content });
    expect(fireEvent.click(link, { ctrlKey: true })).toBe(false);
    const dialog = screen.getByRole("dialog", { name: "Külső webhely megnyitása" });
    const cancel = within(dialog).getByRole("button", { name: "Mégse" });
    expect(cancel).toHaveFocus();
    expect(dialog).toHaveTextContent("adathalászatot");
    const continuation = within(dialog).getByRole("link", { name: "Folytatás új lapon" });
    expect(continuation).toHaveAttribute("href", content);
    expect(continuation).toHaveAttribute("target", "_blank");
    expect(continuation).toHaveAttribute("rel", "noopener noreferrer");
    continuation.focus();
    await user.tab();
    expect(within(dialog).getByRole("button", { name: "Bezárás" })).toHaveFocus();
    await user.click(cancel);
    expect(screen.queryByRole("dialog")).toBeNull();
    link.focus();
    await user.keyboard("{Enter}");
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(link).toHaveFocus();
  });

  it("leaves same-origin links normal and blocks middle-click bypasses", () => {
    render(<><SafeLink href="https://chat.school.hu/app">App</SafeLink><SafeLink href="https://example.com">External</SafeLink></>);
    const local = screen.getByRole("link", { name: "App" });
    expect(fireEvent.click(local)).toBe(true);
    expect(screen.queryByRole("dialog")).toBeNull();
    fireEvent(screen.getByRole("link", { name: "External" }), new MouseEvent("auxclick", { button: 1, bubbles: true, cancelable: true }));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("uses the same warning for embed cards and never loads arbitrary remote preview images", () => {
    const { container } = render(<LinkEmbeds embeds={[{ url: "https://example.com", title: "School news", host: "example.com", image: "http://127.0.0.1/private" }]} />);
    expect(container.querySelector("img")).toBeNull();
    fireEvent.click(screen.getByRole("link", { name: /School news/ }));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });
});

describe("file composers and attachments", () => {
  it("shows no Giphy entry point without a configured key", () => {
    render(<Composer {...composerProps()} />);
    expect(screen.getByRole("button", { name: "Fájl csatolása" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "GIF keresése a GIPHY-n" })).toBeNull();
  });

  it("uploads with scope and progress, sends an attachment-only message, and clears the draft", async () => {
    const props = composerProps();
    mockApi.upload.mockImplementation(async (_path, _file, options) => {
      options?.onProgress?.(75);
      return attachment;
    });
    const { container } = render(<Composer {...props} />);
    fireEvent.change(container.querySelector('input[type="file"]')!, { target: { files: [new File(["pdf"], attachment.filename)] } });
    await screen.findByText(/órarend.pdf · 1.0 kB/);
    expect(mockApi.upload).toHaveBeenCalledWith("/uploads/attachments", expect.any(File), expect.objectContaining({ query: { scope: "channel", scope_id: "9" }, signal: expect.any(AbortSignal), onProgress: expect.any(Function) }));
    await userEvent.click(screen.getByRole("button", { name: "Küldés" }));
    expect(props.onSend).toHaveBeenCalledWith("", null, { attachmentIds: ["123"], giphyId: null });
    await waitFor(() => expect(screen.queryByText(/órarend.pdf ·/)).toBeNull());
    expect(mockApi.del).not.toHaveBeenCalled();
  });

  it("rejects oversized files before upload and respects disabled send permissions", async () => {
    const props = composerProps();
    const { container, rerender } = render(<Composer {...props} mediaConfig={{ ...config, max_attachment_bytes: 2 }} />);
    fireEvent.change(container.querySelector('input[type="file"]')!, { target: { files: [new File(["big"], "file.txt")] } });
    expect(await screen.findByRole("alert")).toHaveTextContent("A fájl túl nagy");
    expect(mockApi.upload).not.toHaveBeenCalled();
    rerender(<Composer {...props} disabledReason="Nincs jogosultságod" />);
    expect(screen.getByRole("button", { name: "Fájl csatolása" })).toBeDisabled();
  });

  it("keeps attachments after send failure and removes pending uploads on discard", async () => {
    const props = composerProps();
    props.onSend.mockRejectedValue(new ApiError(403, "forbidden", "forbidden"));
    mockApi.upload.mockResolvedValue(attachment);
    const { container } = render(<Composer {...props} />);
    fireEvent.change(container.querySelector('input[type="file"]')!, { target: { files: [new File(["pdf"], attachment.filename)] } });
    await screen.findByText(/órarend.pdf ·/);
    await userEvent.click(screen.getByRole("button", { name: "Küldés" }));
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.getByText(/órarend.pdf ·/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "órarend.pdf eltávolítása" }));
    expect(mockApi.del).toHaveBeenCalledWith("/uploads/attachments/123");
  });

  it("renders file metadata and safe previews only through authenticated application URLs", () => {
    const { container } = render(<MessageMedia attachments={[attachment, { ...attachment, id: "124", filename: "video.mp4", mime_type: "video/mp4", kind: "video", url: "/api/v1/uploads/attachments/124" }, { ...attachment, id: "125", kind: "image", url: "https://evil.com/image" }]} />);
    expect(screen.getByText(attachment.filename)).toBeInTheDocument();
    expect(screen.getByText(/1.0 kB · application\/pdf/)).toBeInTheDocument();
    expect(container.querySelector("video")).toHaveAttribute("src", "/api/v1/uploads/attachments/124?inline=true");
    expect(container.querySelector("img")).toBeNull();
  });
});

describe("GIPHY official API", () => {
  it("uses direct requests with pg filtering, no cookies, and unmodified media URLs", async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify({ data: [giphy] }), { status: 200 }));
    vi.stubGlobal("fetch", fetcher);
    const found = await searchGiphy("browser-key", "iskola", "hu");
    const [url, options] = fetcher.mock.calls[0];
    expect(url.origin).toBe("https://api.giphy.com");
    expect(url.searchParams.get("rating")).toBe("pg");
    expect(url.searchParams.get("q")).toBe("iskola");
    expect(options).toMatchObject({ credentials: "omit", cache: "no-store", referrerPolicy: "no-referrer" });
    expect(found[0].image).toBe(giphy.images.downsized.url);
    expect(await searchGiphy("", "iskola", "hu")).toEqual([]);
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it("rejects adult ratings and forged media hosts and resolves saved IDs with a rating filter", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ data: [{ ...giphy, rating: "r" }, { ...giphy, images: { downsized: { url: "https://evil.com/x.gif" } } }] }), { status: 200 })));
    expect(await loadGiphy("browser-key", "SchoolGif")).toBeNull();
    expect(new URL(vi.mocked(fetch).mock.calls[0][0].toString()).searchParams.get("ids")).toBe("SchoolGif");
  });

  it("searches, attributes, and inserts a chosen GIF", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ data: [giphy] }), { status: 200 })));
    const choose = vi.fn();
    render(<GiphyPicker apiKey="browser-key" onChoose={choose} onClose={vi.fn()} />);
    await userEvent.type(screen.getByLabelText("GIF keresőkifejezés"), "iskola");
    await userEvent.click(screen.getByRole("button", { name: "Keresés" }));
    await userEvent.click(await screen.findByRole("button", { name: "Happy school GIF beszúrása" }));
    expect(choose).toHaveBeenCalledWith("SchoolGif");
    expect(screen.getByText("Powered by GIPHY")).toBeInTheDocument();
  });

  it("keeps a failed Giphy lookup graceful and displays a localized error", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("offline")));
    renderApp(<GiphyPicker apiKey="browser-key" onChoose={vi.fn()} onClose={vi.fn()} />);
    await userEvent.type(screen.getByLabelText("GIF keresőkifejezés"), "iskola");
    await userEvent.click(screen.getByRole("button", { name: "Keresés" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("A GIPHY most nem érhető el");
  });
});
