# Initial user-hosted bots changeset (0006)

This document records the original 0006 implementation and its validation. The 0.2 release supersedes its own-message-only, management-endpoint, gateway-event and SDK-reconnect descriptions; see [BOTS_V02_CHANGESET.md](BOTS_V02_CHANGESET.md) for the current update.

## File and API plan

The supplied media/links source archive is the baseline. New implementation lives in `models/bot.py`, `security/bots.py`, `services/bots.py`, `services/bot_commands.py`, `api/v1/bots.py`, `realtime/bots.py` and `migrations/versions/0006_bots.py`. Existing auth/session, serializers, permission evaluation, hub routing, server ownership/removal and school audience helpers have small boundary/wiring changes. The existing encrypted message service and profile image processor are reused.

Frontend additions are `BotBadge`, `BotsSection`, `BotsPanel` and `SlashAutocomplete`, with wiring in Developer settings, server settings, author/member/search views and the server composer. All new UI and error strings are present in Hungarian, English and German; Hungarian remains the default. The human WebSocket client is unchanged.

The local async SDK, example and tests live under `packages/pollakcord`. No bot code is executed by the PollákCord application.

## Human API

All paths below have the `/api/v1` prefix and require an active human cookie session. Mutations retain Origin and CSRF checks.

| Method | Path | Behavior |
| --- | --- | --- |
| GET / POST | `/me/bots` | List / create, with password for create |
| PATCH | `/me/bots/{bot_id}` | Owner-only username and display name |
| POST | `/me/bots/{bot_id}/token/reveal` | Password-gated replacement token, shown once |
| POST | `/me/bots/{bot_id}/token/regenerate` | Password-gated replacement; old token and gateway invalidated |
| DELETE | `/me/bots/{bot_id}` | Owner password plus `confirm_username` |
| POST / DELETE | `/me/bots/{bot_id}/images/{avatar or banner}` | Owner-only normal profile image processing |
| GET / POST | `/servers/{server_id}/bots` | Owner/Administrator list or install with `bot_id` and `permissions` |
| DELETE | `/servers/{server_id}/bots/{bot_id}` | Owner/Administrator removal |
| GET | `/channels/{channel_id}/bot-commands` | Installed, visible and permission-filtered command definitions |
| POST | `/channels/{channel_id}/interactions` | `command_id` and typed `options`; waits up to three seconds |

The integration GET also supplies available and default permission names for the checklist. Unknown, school, platform, Administrator and voice grants are rejected. Optional management flags use existing server permission names; this version's bot API provides no member/role moderation endpoints.

## Bot API and gateway

These routes require `Authorization: Bot <token>`, have no browser-session fallback, and reject browser Origin headers or a session cookie. Only this isolated namespace can use token authentication without a CSRF cookie. A Bot header on a human API path is rejected before routing; adding a Bot header cannot bypass human CSRF.

| Method | Path after `/api/v1/bots/api` | Behavior |
| --- | --- | --- |
| GET | `/me` | Current bot card and application ID |
| GET | `/servers` | Installed servers, ID and name only |
| GET | `/servers/{server_id}/channels` | Currently viewable server text channels |
| POST | `/channels/{channel_id}/messages` | Text-only `content`; existing content limits, encryption, embeds and slowmode |
| DELETE | `/channels/{channel_id}/messages/{message_id}` | Own message only, with current channel/send permission |
| GET / PUT | `/commands` | List / replace bot's command definitions; preserve IDs for unchanged names |
| POST | `/interactions/{interaction_id}/response` | One timely public text response for this bot's interaction |

The gateway URL is `/api/v1/bots/gateway`, authenticated by the same header. Tokens in query strings are not accepted. It emits envelopes with `t` and `d`: `ready`, `message.create`, `message.delete`, `interaction.create` and heartbeat `pong`. Send `{"op":"ping"}` every 20 seconds; idle sockets close after 45 seconds. No human gateway operations, subscriptions, DMs, school topics, friend lists or voice events are accepted.

Channel message delivery is connected to the existing outbox publication after commit. Every delivery rechecks the bot token generation, bot and owner status, install membership and current view/history permissions. Interaction delivery happens after its row commits and rechecks current view/send permission. A failed bot delivery does not fail a committed human message. Install removal stops access immediately; token replacement, bot deletion and owner suspension close the relevant sessions. Pending invocations fail clearly when a bot is replaced or deleted.

## Persistence and permissions

Revision `0006` adds `users.is_bot` with a false default and a database constraint prohibiting a bot platform role other than `user` or a school class. It adds only `bot_applications`, `bot_installs`, `bot_commands` and `bot_interactions`. Downgrade removes those tables, the constraint and the flag; it does not touch existing media, DÖK, form, class-space or message schema. Migration tests compare the resulting schema against model metadata and check upgrade/downgrade preservation of populated human/profile rows and media columns.

Applications have exactly one human owner. Tokens contain 48 cryptographically random bytes and use the same SHA-256 hash family as session tokens; no token plaintext or recoverable copy is stored. There are no bot credentials, E-Kréta identities or browser sessions. Deleted bots retain an inactive user tombstone so encrypted author attribution and permanent BOT badges on existing messages survive.

Each installation adds a server membership and a low-position managed role containing the checked flags. The normal permission evaluator additionally caps bot effective permissions at that install's explicit grant. Default-role inheritance and later role/overwrite changes cannot add unchecked powers. Category/channel/member overwrites still decide visibility within that ceiling. Existing hierarchy comparisons protect the server owner and equal/higher roles. Bots cannot become server owners; their REST interface cannot kick, ban, reveal identities or modify roles. Generic human kick/ban removal of a bot also requires server ownership or Administrator.

DÖK and form notification audiences explicitly exclude bot accounts, and class-space participation rejects them. Human-to-bot friend requests are a no-op and human-to-bot DMs are denied. Bots cannot authenticate against any school-private, upload, friend, identity or platform staff endpoint.

Interactions store IDs, status and deadlines, without command argument values or message plaintext. Message bodies use the existing encrypted content, search index and media metadata service. Each interaction revalidates installation, the bot's send permission, the invoker's channel access and that exact command's permission before responding. Duplicate or expired responses cannot create messages. Completed/expired interactions older than one day are pruned during later invocations.

Audit actions are `bot.create`, `bot.token_regenerate`, `bot.delete`, `bot.install` and `bot.remove`, containing actor/server/bot IDs only. Tokens, passwords, option values and message bodies are never written to those audit details. Browser token state is temporary and excluded from persistent/query storage; closing the one-time dialog discards it.

## Limits and intentionally deferred behavior

| Resource | Per bot | Per human owner |
| --- | --- | --- |
| Owned bots | — | 3 active applications |
| Gateway sessions | 1 | 3 |
| Gateway connection attempts | 6 / minute | 12 / minute |
| REST requests | 120 / minute | 240 / minute |
| Sends, including interaction replies | 8 / 10 seconds | 16 / 10 seconds |
| Command registration | 3 / minute | 6 / minute |
| Token replacement | 3 / 10 minutes | 6 / 10 minutes |
| Create | — | 5 / hour |
| Password step-up | — | 10 / 10 minutes plus existing account lockout |

There are also IP and gateway-frame limits. The deployment remains one worker with in-memory connections, interaction waiters and rate limits. No Redis, sharding or bot process hosting is introduced.

Messages are text-only. Bot attachments, voice, ephemeral/deferred responses, components, marketplace and PyPI publishing are deferred. Owner-managed bot avatars/banners reuse existing image sanitization without changing human attachment policy. The SDK stops on disconnect and can be restarted with backoff by a user-managed process supervisor.

## Validation

The final broad backend/SDK run exercised 389 tests: 388 passed and one class-space test encountered a transient `sqlite3.OperationalError: disk I/O error` in the existing direct SQLite count helper. That exact test passed in an isolated rerun without code changes. This includes all 14 new bot backend tests, the populated bot migration test, all 4 SDK tests, 52 existing media tests, 23 DÖK tests and 25 forms tests. The existing exact form-result user-card assertion now includes the required `is_bot: false` field.

The pre-existing `test_child_process_does_not_inherit_server_secrets` test is excluded from the broad run because this execution environment has no `/proc/<pid>/environ`; an unfiltered run reproduced its `FileNotFoundError`. The supplied README already records the same limitation. The test and the E-Kréta subprocess code are unchanged. Run it on a normal Linux environment with `/proc` mounted.

All 203 frontend tests passed with one worker and a 20-second test timeout. The focused 10 bot frontend tests passed again after the final keyboard adjustment. The TypeScript/Vite production build and no-comments scanner passed. The existing backend comment/docstring check and the new SDK source hygiene check passed. The Python package built successfully as a wheel.

A separate live smoke test ran the actual FastAPI app under Uvicorn and the actual Python SDK over local HTTP and WebSocket connections. It verified gateway `ready`, command registration, `/ping` invocation, a public bot response and human message event delivery, then shut down the client and server.

Reproduce the main checks from the source root after installing the supplied backend dev requirements and frontend dependencies:

```sh
python -m pytest -c backend/pytest.ini backend/tests packages/pollakcord/tests -q --tb=short -k 'not test_child_process_does_not_inherit_server_secrets'
python -m pytest -c backend/pytest.ini backend/tests/test_class_spaces.py::test_non_members_get_a_plain_404_everywhere -q
npm --prefix frontend test -- --maxWorkers=1 --testTimeout=20000
npm --prefix frontend run build
npm --prefix frontend run check:comments
python -m pip wheel --no-deps ./packages/pollakcord
```

The original message, attachment, upload and embed implementation files and revisions 0001–0005 are byte-for-byte unchanged. No bot attachment quota, human media quota change, Redis service, voice bot path or user-code execution service was added.
