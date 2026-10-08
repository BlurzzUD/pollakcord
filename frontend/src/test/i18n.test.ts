import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import de from "../i18n/locales/de.json";
import en from "../i18n/locales/en.json";
import hu from "../i18n/locales/hu.json";

type Tree = { [key: string]: string | Tree };

function flatten(tree: Tree, prefix = ""): Record<string, string> {
  const flat: Record<string, string> = {};
  for (const [key, value] of Object.entries(tree)) {
    if (typeof value === "string") {
      flat[prefix + key] = value;
    } else {
      Object.assign(flat, flatten(value, `${prefix}${key}.`));
    }
  }
  return flat;
}

const catalogs = { hu: flatten(hu as Tree), en: flatten(en as Tree), de: flatten(de as Tree) };
const placeholders = (text: string) => [...text.matchAll(/\{\{(\w+)\}\}/g)].map((match) => match[1]).sort();

function sourceFiles(directory: string, found: string[] = []): string[] {
  for (const name of readdirSync(directory)) {
    const path = join(directory, name);
    if (statSync(path).isDirectory()) {
      if (name !== "test") {
        sourceFiles(path, found);
      }
    } else if (/\.(ts|tsx)$/.test(name)) {
      found.push(path);
    }
  }
  return found;
}

function hasKey(catalog: Record<string, string>, key: string): boolean {
  return key in catalog || `${key}_one` in catalog || `${key}_other` in catalog;
}

describe("translations", () => {
  it("provides exactly the same keys in Hungarian, English and German", () => {
    const reference = Object.keys(catalogs.hu).sort();
    expect(Object.keys(catalogs.en).sort()).toEqual(reference);
    expect(Object.keys(catalogs.de).sort()).toEqual(reference);
    expect(reference.length).toBeGreaterThan(700);
  });

  it("uses the same interpolation placeholders in every language", () => {
    for (const key of Object.keys(catalogs.hu)) {
      const expected = placeholders(catalogs.hu[key]);
      expect(placeholders(catalogs.en[key]), key).toEqual(expected);
      expect(placeholders(catalogs.de[key]), key).toEqual(expected);
    }
  });

  it("has no empty or untranslated strings", () => {
    for (const [language, catalog] of Object.entries(catalogs)) {
      for (const [key, value] of Object.entries(catalog)) {
        expect(value.trim(), `${language}:${key}`).not.toBe("");
      }
    }
    const identical = Object.keys(catalogs.hu).filter(
      (key) => catalogs.hu[key] === catalogs.en[key] && catalogs.en[key].length > 24 && catalogs.hu[key] === catalogs.de[key],
    );
    expect(identical).toEqual([]);
  });

  it("covers every static translation key used in the source", () => {
    const used = new Set<string>();
    for (const file of sourceFiles(join(__dirname, ".."))) {
      for (const match of readFileSync(file, "utf8").matchAll(/\bt\(\s*"([A-Za-z0-9_.]+)"/g)) {
        used.add(match[1]);
      }
    }
    expect(used.size).toBeGreaterThan(400);
    for (const [language, catalog] of Object.entries(catalogs)) {
      const missing = [...used].filter((key) => !hasKey(catalog, key));
      expect(missing, language).toEqual([]);
    }
  });

  it("covers every dynamically built translation key", () => {
    const expansions: Record<string, string[]> = {
      "register.subtitle_": ["kreta", "account", "security", "class"],
      "register.step_": ["kreta", "account", "security", "class"],
      "recover.subtitle_": ["choose", "kreta", "code", "security"],
      "privacy.class_visibility_": ["hidden", "friends", "shared_servers", "everyone"],
      "notifications.moderation_": ["timeout", "kick", "ban", "message_removed"],
      "server.removed_": ["kicked", "banned", "left", "deleted"],
      "report.reasons.": ["spam", "harassment", "hate", "sexual_content", "self_harm", "violence", "impersonation", "other"],
      "server.tab.": ["overview", "roles", "channels", "members", "invites", "bans", "reports", "audit"],
      "server.tab_": ["create", "join"],
      "friends.tab_": ["online", "all", "pending", "blocked", "add"],
      "moderation.status_": ["open", "resolved", "dismissed"],
      "moderation.tab_": ["reports", "users", "messages", "audit"],
      "profile.presence_": ["online", "offline"],
      "settings.": ["account", "privacy", "notifications", "appearance", "security", "developer", "avatar", "banner"],
      "appearance.mode_": ["system", "dark", "light", "custom"],
      "appearance.density_": ["cozy", "compact"],
      "appearance.preset_": ["notebook", "chalkboard", "highlighter", "midnight"],
      "appearance.token_": ["bg", "bg_alt", "bg_deep", "text", "text_muted", "accent", "accent_text", "danger", "mention", "border"],
      "voice.": ["microphone_denied", "microphone_unavailable"],
      "server.perm_group_": ["general", "text", "voice", "moderation", "advanced"],
      "notifications.pref_": ["friend_requests", "direct_messages", "mentions", "server", "calls", "moderation", "sounds"],
      "privacy.": ["friend_requests", "direct_messages", "class_visibility", "online_status", "profile_visibility", "activity_visibility", "voice_calls"],
      "audit.actions.": [
        "member_kick", "member_ban", "member_unban", "member_timeout", "member_update", "member_roles", "role_create", "role_update", "role_delete",
        "channel_create", "channel_update", "channel_delete", "channel_permissions", "category_create", "category_update", "category_delete",
        "server_update", "message_delete", "message_pin", "message_unpin", "invite_create", "invite_revoke", "voice_moderate", "report_resolve",
        "platform_identity_reveal", "platform_message_view", "platform_user_status", "platform_report_view", "account_recovery",
      ],
      "permissions.": [
        "view_channel", "send_messages", "read_message_history", "add_reactions", "connect", "speak", "mute_members", "deafen_members", "create_invite",
        "kick_members", "ban_members", "manage_messages", "manage_channels", "manage_roles", "manage_members", "manage_server", "view_audit_log", "administrator",
      ],
    };
    for (const [language, catalog] of Object.entries(catalogs)) {
      const missing: string[] = [];
      for (const [prefix, values] of Object.entries(expansions)) {
        for (const value of values) {
          if (!hasKey(catalog, `${prefix}${value}`)) {
            missing.push(`${prefix}${value}`);
          }
        }
      }
      expect(missing, language).toEqual([]);
    }
    for (const [language, catalog] of Object.entries(catalogs)) {
      for (const permission of expansions["permissions."]) {
        expect(hasKey(catalog, `permissions.${permission}_hint`), `${language}:${permission}`).toBe(true);
      }
      for (const key of ["friend_requests", "direct_messages", "class_visibility", "online_status", "profile_visibility", "activity_visibility", "voice_calls"]) {
        expect(hasKey(catalog, `privacy.${key}_hint`), `${language}:${key}`).toBe(true);
      }
    }
  });

  it("translates every privacy option offered in the settings", () => {
    const options: Record<string, string[]> = {
      friend_requests: ["everyone", "shared_servers", "nobody"],
      direct_messages: ["everyone", "shared_servers", "friends"],
      class_visibility: ["hidden", "friends", "shared_servers", "everyone"],
      online_status: ["friends", "shared_servers", "nobody"],
      profile_visibility: ["shared_context", "friends", "everyone"],
      activity_visibility: ["friends", "nobody"],
      voice_calls: ["friends", "nobody"],
    };
    for (const catalog of Object.values(catalogs)) {
      for (const [key, values] of Object.entries(options)) {
        for (const value of values) {
          expect(hasKey(catalog, `privacy.${key}_${value}`), `${key}_${value}`).toBe(true);
        }
      }
    }
  });

  it("includes a translation for every backend error code", () => {
    const backend = JSON.parse(
      readFileSync(join(__dirname, "../../../backend/app/locales/hu.json"), "utf8"),
    ) as { errors: Record<string, string> };
    for (const [language, catalog] of Object.entries(catalogs)) {
      const missing = Object.keys(backend.errors).filter((code) => !(`errors.${code}` in catalog));
      expect(missing, language).toEqual([]);
    }
  });

  it("greets the user in each language", () => {
    expect(catalogs.hu["home.greeting"]).toBe("Üdv, {{name}}!");
    expect(catalogs.en["home.greeting"]).toBe("Hello, {{name}}!");
    expect(catalogs.de["home.greeting"]).toBe("Hallo, {{name}}!");
    expect(catalogs.hu["class.prompt"]).toBe("Szeretnéd megjeleníteni az osztályodat a profilodon?");
    expect(catalogs.hu["kreta.are_you"]).toBe("Te vagy {{name}}?");
  });
});
