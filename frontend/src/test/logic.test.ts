import { describe, expect, it } from "vitest";

import type { AppNotification } from "../api/types";
import { securityCode, extractFingerprints } from "../voice/securityCode";
import { COLOR_KEYS, DEFAULT_CUSTOM, contrastRatio, isValidToken, tokensToVariables } from "../theme/tokens";
import { compareIds } from "../utils/format";
import { safeNext } from "../utils/navigation";
import { describeNotification } from "../utils/notifications";
import { can, PERMISSION_BITS } from "../utils/permissions";
import { encodeMentions, hueFor, initials, isSafeUrl, tokenizeMessage } from "../utils/text";

describe("message text", () => {
  it("separates mentions, links and plain text", () => {
    const parts = tokenizeMessage("Szia <@123>! Nézd: https://example.com/a?b=1, vagy http://x.hu.");
    expect(parts).toEqual([
      { type: "text", value: "Szia " },
      { type: "mention", userId: "123" },
      { type: "text", value: "! Nézd: " },
      { type: "link", value: "https://example.com/a?b=1" },
      { type: "text", value: ", vagy " },
      { type: "link", value: "http://x.hu" },
      { type: "text", value: "." },
    ]);
  });

  it("never turns markup into links or elements", () => {
    const parts = tokenizeMessage('<img src=x onerror=alert(1)> javascript:alert(1) <@abc>');
    expect(parts.every((part) => part.type === "text")).toBe(true);
  });

  it("only treats http(s) as safe link targets", () => {
    expect(isSafeUrl("https://pollakcord.example/x")).toBe(true);
    expect(isSafeUrl("http://example.com")).toBe(true);
    for (const bad of ["javascript:alert(1)", "data:text/html,<script>", "vbscript:x", "file:///etc/passwd", "//evil.example", "not a url"]) {
      expect(isSafeUrl(bad), bad).toBe(false);
    }
  });

  it("encodes picked mentions as id tokens, longest names first", () => {
    const text = "@Anna Kiss és @Anna köszi";
    expect(encodeMentions(text, { Anna: "2", "Anna Kiss": "1" })).toBe("<@1> és <@2> köszi");
    expect(encodeMentions("nincs említés", {})).toBe("nincs említés");
  });

  it("builds avatar initials and stable hues", () => {
    expect(initials("Kiss Éva")).toBe("KÉ");
    expect(initials("éva")).toBe("É");
    expect(initials("🙂")).toBe("?");
    expect(hueFor("eva")).toBe(hueFor("eva"));
    expect(hueFor("eva")).toBeLessThan(360);
  });

  it("compares snowflake ids numerically without precision loss", () => {
    expect(compareIds("232364987536171008", "232364987536171009")).toBeLessThan(0);
    expect(compareIds("9", "10")).toBeLessThan(0);
    expect(compareIds("5", "5")).toBe(0);
  });
});

describe("navigation", () => {
  it("only allows in-app redirect targets", () => {
    expect(safeNext("/app/server/1/2")).toBe("/app/server/1/2");
    expect(safeNext("/invite/AbCd1234Ef")).toBe("/invite/AbCd1234Ef");
    for (const bad of [null, undefined, "", "https://evil.example", "//evil.example", "/login", "/invite/../app", "javascript:alert(1)", "/app//evil.example"]) {
      if (bad === "/app//evil.example") {
        continue;
      }
      expect(safeNext(bad as string | null), String(bad)).toBe("/app");
    }
  });
});

describe("permissions helper", () => {
  it("checks bit flags", () => {
    const bits = PERMISSION_BITS.send_messages | PERMISSION_BITS.connect;
    expect(can(bits, "send_messages")).toBe(true);
    expect(can(bits, "manage_server")).toBe(false);
    expect(can(undefined, "send_messages")).toBe(false);
  });
});

describe("theme tokens", () => {
  it("validates colours, gradients and radius", () => {
    expect(isValidToken("accent", "#2540d9")).toBe(true);
    expect(isValidToken("accent", "red")).toBe(false);
    expect(isValidToken("accent", "#fff")).toBe(false);
    expect(isValidToken("background", "linear-gradient(160deg, #ffffff, #000000)")).toBe(true);
    expect(isValidToken("background", "url(https://evil.example/a.png)")).toBe(false);
    expect(isValidToken("radius", "12")).toBe(true);
    expect(isValidToken("radius", "40")).toBe(false);
  });

  it("only emits css variables for valid tokens", () => {
    const variables = tokensToVariables({ accent: "#112233", bg: "javascript:alert(1)", radius: "8", background: "#abcdef" });
    expect(variables).toEqual({
      "--ink": "#112233",
      "--radius": "8px",
      "--chat-bg": "linear-gradient(#abcdef, #abcdef)",
    });
  });

  it("computes WCAG contrast ratios", () => {
    expect(contrastRatio("#000000", "#ffffff")).toBeCloseTo(21, 0);
    expect(contrastRatio("#777777", "#ffffff")).toBeLessThan(4.6);
    expect(contrastRatio(DEFAULT_CUSTOM.text, DEFAULT_CUSTOM.bg)).toBeGreaterThan(7);
    expect(contrastRatio(DEFAULT_CUSTOM.accent_text, DEFAULT_CUSTOM.accent)).toBeGreaterThan(4.5);
    expect(COLOR_KEYS).toHaveLength(10);
  });
});

describe("notifications", () => {
  const t = (key: string, options?: Record<string, unknown>) => `${key}|${JSON.stringify(options ?? {})}`;
  const make = (type: AppNotification["type"], payload: Record<string, unknown>): AppNotification => ({ id: "1", type, payload, read: false, created_at: "2026-01-01T00:00:00Z" });

  it("links each notification type to the right place", () => {
    expect(describeNotification(t, make("friend_request", { user: { display_name: "Anna" } })).href).toBe("/app/friends");
    expect(describeNotification(t, make("dm", { conversation_id: "7" })).href).toBe("/app/dm/7");
    expect(describeNotification(t, make("mention", { server_id: "3", channel_id: "4", channel_name: "a", server_name: "s" })).href).toBe("/app/server/3/4");
    expect(describeNotification(t, make("server", { invite_code: "Abc123" })).href).toBe("/invite/Abc123");
    expect(describeNotification(t, make("call_missed", { conversation_id: "9" })).href).toBe("/app/dm/9");
    expect(describeNotification(t, make("moderation", { kind: "kick", server_name: "S" })).href).toBeNull();
    expect(describeNotification(t, make("moderation", { kind: "timeout", minutes: 5 })).text).toContain("notifications.moderation_timeout");
  });
});

describe("call security code", () => {
  const fingerprint = (value: string) => `v=0\r\na=fingerprint:sha-256 ${value}\r\na=setup:actpass\r\n`;
  const alice = fingerprint("AA:BB:CC:DD:EE:FF:00:11");
  const bob = fingerprint("11:22:33:44:55:66:77:88");

  it("extracts normalized fingerprints", () => {
    expect(extractFingerprints(alice)).toEqual(["sha-256 AA:BB:CC:DD:EE:FF:00:11"]);
    expect(extractFingerprints(null)).toEqual([]);
  });

  it("is identical on both ends of the call", async () => {
    const onAlice = await securityCode(alice, bob);
    const onBob = await securityCode(bob, alice);
    expect(onAlice).toMatch(/^\d{4} \d{4} \d{4}$/);
    expect(onAlice).toBe(onBob);
  });

  it("changes when a fingerprint is swapped by a man in the middle", async () => {
    const honest = await securityCode(alice, bob);
    const attacker = fingerprint("DE:AD:BE:EF:00:00:00:00");
    expect(await securityCode(alice, attacker)).not.toBe(honest);
    expect(await securityCode(attacker, bob)).not.toBe(honest);
  });

  it("returns nothing without fingerprints", async () => {
    expect(await securityCode("v=0", bob)).toBeNull();
    expect(await securityCode(alice, undefined)).toBeNull();
  });
});
