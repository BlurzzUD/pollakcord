# Discord-style bot library 0.2

## File and API plan

This update builds on the completed 0006 bot source. Additive bot-only resource routes live in `backend/app/api/v1/bot_resources.py`, with scoped payload/permission helpers in `services/bot_resources.py`. They call the existing server/channel operations after bot-specific scope, hierarchy and permission checks. Existing bot authentication and install ceilings are retained. The original human routes, media quotas and school APIs are not broadened for bot credentials.

`realtime/bots.py` adds optional extended gateway event subscriptions, preserving the original gateway's default event set. `services/bot_commands.py` adds bounded reply references and supplies the slash invoker's minimal member card/effective channel permission bitset. `services/messages.py` adds encrypted own-message text replacement and nullable edit serialization, using the same content cleaning, key/AAD, blind index, encrypted media preview and sanitizer helpers. Existing attachment storage and quota behavior is unchanged.

Migration `0007_bot_message_edits.py` follows `0006` and adds only nullable `messages.edited_at`. The downgrade drops only that column. The frontend message timeline handles `message.update` within its existing scope and preserves viewer-specific reactions; the message item shows the edit marker in Hungarian, English and German. Existing browser WebSocket/authentication behavior is retained.

The package now publishes as `pollakcord` version `0.2.0`. `compat.py`, `objects.py`, `app_commands.py`, `ext/commands.py`, `ext/tasks.py` and `utils.py` provide the supported discord.py-style interface. The low-level `Bot(origin, token)` interface remains available. `examples/discord_style.py` demonstrates both pings and a new-member welcome. [COMPATIBILITY.md](packages/pollakcord/COMPATIBILITY.md) lists the supported surface and differences explicitly.

## Additional REST routes

All paths below are relative to `/api/v1/bots/api`. They require the existing separate Bot-token authentication, active human owner and active installation. All IDs/cursors are bounded positive 64-bit values and bodies reject unknown fields. Normal browser cookie/Origin/CSRF behavior is unchanged.

| Method | Path | Guard and behavior |
| --- | --- | --- |
| GET / PATCH | `/servers/{server_id}` | Installed server snapshot / name and description with Manage Server; never ownership transfer |
| GET | `/servers/{server_id}/audit-logs` | View Audit Log, scoped server action allowlist, IDs/timestamp/action only; no details, identities, form/report contents or voice activity |
| GET | `/servers/{server_id}/bans` | Ban Members, up to 200 existing server bans |
| GET | `/channels/{channel_id}` | Currently visible installed server text channel, effective bot permissions |
| GET | `/servers/{server_id}/members` | At least one visible text channel, up to 100 members per page, only public card and server membership metadata |
| GET | `/servers/{server_id}/members/{user_id}` | Same installed/viewable server, current membership; no global user lookup |
| GET | `/channels/{channel_id}/members/{user_id}` | Both bot and target can view this text channel; minimal member plus effective channel permissions for checks |
| GET | `/channels/{channel_id}/messages` | View plus Read History, bounded cursor pagination through existing encrypted message service |
| GET / PATCH | `/channels/{channel_id}/messages/{message_id}` | Read a live scoped message / edit own live message with current Send Messages permission |
| PUT / DELETE | `/channels/{channel_id}/messages/{message_id}/reactions` | Existing fixed emoji set; add needs Add Reactions, read access required; remove only bot's own reaction |
| GET | `/channels/{channel_id}/pins` | View plus Read History |
| PUT / DELETE | `/channels/{channel_id}/pins/{message_id}` | Existing Manage Messages permission and pin limits |
| PATCH | `/servers/{server_id}/members/{user_id}` | Existing Manage Members/Manage Roles, stronger bot target guard, hierarchy, no new grants outside the install ceiling |
| PUT / DELETE | `/servers/{server_id}/members/{user_id}/roles/{role_id}` | Scoped atomic add/remove, custom grantable role below the bot, no self/bot target |
| DELETE | `/servers/{server_id}/members/{user_id}` | Kick Members and stronger target/hierarchy guard |
| PUT / DELETE | `/servers/{server_id}/bans/{user_id}` | Ban Members; banning requires a current member and stronger target/hierarchy guard |
| GET / POST | `/servers/{server_id}/roles` | Installed server roles / Manage Roles, only grantable flags below bot's top role |
| PATCH / DELETE | `/servers/{server_id}/roles/{role_id}` | Manage Roles, only a custom role below bot's role; no modifying managed/default/built-in roles |
| POST | `/servers/{server_id}/channels` | Manage Channels, create text channels only |
| PATCH / DELETE | `/channels/{channel_id}` | Manage Channels and current visibility, text channels only |
| GET / POST | `/servers/{server_id}/invites` | Create Invite, existing server invite policy and creator scoping |
| DELETE | `/servers/{server_id}/invites/{code}` | Existing creator/Manage Server checks |

The original send endpoint additionally accepts optional `reply_to_id`, checked by the existing same-channel live-reply validator. Bot message deletion now permits other authors only with checked Manage Messages and the stronger target guard. Default installs remain own-delete only. Current-bot info adds the owner ID for local `is_owner` command checks; it never returns owner identity/profile information.

## Gateway and events

The original gateway still emits `ready`, messages/create/delete and interactions by default. The new SDK sends `{"op":"subscribe","events":[...]}` after ready. Allowed additional events are `member.joined`, `member.left`, `member.updated`, `message.update`, `reaction.update`, `message.pin`, `structure.changed`, `role.changed` and `server.updated`. Unknown subscriptions/operations are rejected. Heartbeat, per-bot/owner/IP rates and connection caps are unchanged.

Member events come from existing post-commit server join/leave/update publications. Failed joins and already-member invite accepts do not emit a fresh join. Payloads are reconstructed from a public card and that server's membership metadata; no school identity, class, friends, presence, profile bio or forms are included. An active installed bot must currently see a text channel to receive member events. Channel events require current view/history; structural snapshots contain only currently visible server text channels. Role/own-membership changes refresh the visibility cache. DMs, DÖK/class-space topics, staff and form events are never subscribed or forwarded.

The SDK reconnects transient failures with backoff/jitter and refreshes caches. Invalid/revoked credentials are terminal. There is no event replay, multi-worker gateway or session resumption; offline welcome events are missed. Rich edit/delete/reaction events use the bounded message cache, with raw forms available where implemented. No user bot code runs on PollákCord.

## Permission and security summary

Install/removal still requires a human server owner or Administrator; checked flags are an absolute permission ceiling. Defaults remain View Channel, Read History and Send Messages. Administrator, voice and school/platform powers remain excluded. Bots cannot change their installation, managed/default/built-in role, server ownership, or grant a permission they lack. Custom role positioning and member changes reuse the existing hierarchy. Moderation additionally denies other bots, the bot's human owner, server owner, self and equal/higher members. Existing server owners can reposition the managed bot role without bypassing its ceiling.

All new resource endpoints require token auth exclusively, retaining owner suspension, revocation serialization, REST and gateway caps. Text-only bot messages preserve the existing human content limits, slowmode, mentions validation, encryption, link preview protections and external-link warning behavior. Edits re-encrypt text and update the blind index/mentions; they preserve attachment storage and human file policy. Lifecycle auditing remains ID-only. Existing server operations audit their corresponding server actions, without message bodies or tokens. Bot-facing audit reads omit all details.

Management/member mutations share stricter bot/owner limits: 10/20 actions per minute; reactions 20/40 per minute; invites 5/10 per minute; edits 8/16 per 10 seconds. Existing send, REST, registration, ownership, token and gateway limits are unchanged. Bodies cannot smuggle attachment IDs, voice channel types, ownership transfer or platform fields into these routes.

School-private access restrictions, bot token hashing, password gates, browser session/CSRF separation and the single-worker architecture remain in place. No bot attachment policy, Redis service or deployment/publishing automation is added.

## Compatibility and limits

Common supported scripts can change imports, supply the origin/token, and replace Discord IDs. This is feature-level compatibility through the PollákCord library, not Discord protocol emulation. Unsupported features are documented and rejected instead of simulated. Voice, DMs, components, ephemeral/deferred replies, webhooks, custom embeds, bot uploads, threads, presence and Discord-specific products are not part of this release. Publishing to PyPI remains manual. The matching backend and `0007` migration must be deployed before the new SDK is used.

## Validation

The final full backend/SDK run passed 413 tests, with the existing `/proc/<pid>/environ`-dependent subprocess test excluded because this sandbox lacks that file. The new resource tests cover welcome events exactly once for successful live joins, membership/visibility/install denials, minimal public member payloads, encrypted/reindexed own-message edits, reply scopes, reactions/pins, moderation hierarchy/grants, role assignment, text channel/invite management, and populated migration upgrade/downgrade. The run includes 11 new backend resource/migration tests and 17 SDK tests, including cache refresh, server metadata/audit permissions, SDK reconnect and terminal revocation. The moderation test passed again after the final unban target guard was added.

All 205 frontend tests passed, including late edit/deletion ordering and retaining viewer-specific reactions. The TypeScript/Vite production build passed. Source comment/docstring checks cover backend, frontend and the SDK. A `pollakcord-0.2.0-py3-none-any.whl` built successfully.

A live Uvicorn + real HTTP/WebSocket integration test passed slash `/ping`, prefix `!ping`, new-member username welcome, encrypted message edit, reaction/pin, custom role assignment/removal, timeout/remove-timeout, server-owner moderation denial and automatic reconnect after a server-side transient close. Test fixtures/tokens/databases are excluded from the source archive.

Reproduce from the source root with dependencies installed:

```sh
python -m pytest -c backend/pytest.ini backend/tests packages/pollakcord/tests -q -k 'not test_child_process_does_not_inherit_server_secrets'
npm --prefix frontend test -- --maxWorkers=1 --testTimeout=20000
npm --prefix frontend run build
npm --prefix frontend run check:comments
python -m pip wheel --no-deps ./packages/pollakcord
```
