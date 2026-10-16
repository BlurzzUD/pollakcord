# PollákCord Python library 0.2

Run your bot on your own computer or VPS with Python 3.11 or newer. PollákCord never runs your Python code. This release adds a familiar `discord.py`-style interface for PollákCord's supported features. It is not a full replacement for Discord or its API; see [COMPATIBILITY.md](COMPATIBILITY.md) for the exact surface and differences.

## Install and run on Windows

Apply the server's `0007` migration and deploy the updated backend/frontend first. From the extracted project root:

```bat
python -m pip uninstall pollakcord-bot
python -m pip install ./packages/pollakcord
set "POLLAKCORD_ORIGIN=https://chat.bsnr.xyz"
set "POLLAKCORD_BOT_TOKEN=your-bot-token"
set "POLLAKCORD_WELCOME_CHANNEL_ID=your-welcome-channel-id"
python packages\pollakcord\examples\discord_style.py
```

Uninstalling the earlier distribution avoids two distributions providing the same `pollakcord` import. If your command prompt is already in `packages\pollakcord\examples`, install with `python -m pip install ..` and run `python discord_style.py` there. Environment variable names go inside `os.environ[...]`; their values belong in the `set` commands.

The distribution is now named `pollakcord`, version `0.2.0`. Once its owner publishes it under that available PyPI name, `python -m pip install pollakcord` can install it from PyPI. No upload or publication is performed by this source change.

## Discord-style ping

```python
import os

import pollakcord as discord
from pollakcord.ext import commands

bot = commands.Bot(
    command_prefix="!",
    origin=os.environ["POLLAKCORD_ORIGIN"],
    intents=discord.Intents.default(),
)


@bot.command()
async def ping(ctx):
    await ctx.send("Pong!")


@bot.tree.command(name="ping", description="Check whether the bot is running")
async def slash_ping(interaction: discord.Interaction):
    await interaction.response.send_message("Pong!")


bot.run(os.environ["POLLAKCORD_BOT_TOKEN"])
```

`commands.Bot.run(token)` is synchronous, like `discord.py`; use `await bot.start(token)` inside an existing async application. `Client`, `@bot.event`, `@bot.listen`, `setup_hook`, `wait_for`, prefix commands with converters/checks/cooldowns, command cogs, async extension setup, slash trees and interval task loops are included. The default `setup_hook` syncs registered slash commands once; if you override it, call `await self.tree.sync()` yourself. Do not sync on every reconnect.

The complete [Discord-style example](examples/discord_style.py) also welcomes new members by username. Enable `intents.members`, set the welcome channel ID, and keep the bot running. Events that occur while the bot is offline are not replayed. A join handler can also assign a custom role when the install explicitly grants Manage Roles and the target role is below the bot's role.

## Create and install

Create up to three bots under Settings → Developer → Bots using your owner password. Copy the token once and store it in environment variables or a secret manager. A server owner or Administrator installs the bot by pasting its bot ID into Server settings → Integrations · Bots and checking the allowed permissions. View channel, read history and send messages default on; optional management permissions default off. Bots always display a BOT badge.

Tokens must never appear in committed source, examples, screenshots or logs. Both token reveal and regenerate replace the token, invalidate the old hash and disconnect the gateway. A suspended owner disables all their bots. Invalid/revoked credentials are terminal; update the token and restart. Temporary network disconnects reconnect with bounded exponential backoff and rebuild the visible server/channel cache. This is reconnection, not gateway session resumption: events during a gap are lost, and `on_ready` can fire again. One gateway per bot and three per owner are allowed.

## Supported server features

The library exposes typed `User`, `Member`, `Guild`, `Role`, `TextChannel`, `Message`, `Reaction` and `Interaction` objects with integer IDs. Server and text-channel lookup, scoped member lookup/listing, message history, replies, own-message edits, deletion, fixed-set reactions, pins, custom roles, role assignment, nicknames, timeouts, kicks, bans/unbans, text-channel management, server invites, server name/description updates and ID-only server audit reads use the isolated bot API. Every operation rechecks current install permissions and visibility. Moderation additionally protects server owners, bot owners, bots and equal/higher roles. Bots cannot change their managed role, default/built-in roles, ownership or their install ceiling.

The inherited limits remain: 25 slash commands, 10 options each, string/int/bool/channel/user options, one public response within three seconds, 8 sends per 10 seconds per bot and 16 per owner, 3 command registrations per minute per bot and 6 per owner, and 120 REST requests per minute per bot and 240 per owner. Management is limited to 10 actions per minute per bot and 20 per owner, reactions to 20/40 per minute, and invites to 5/10 per minute. The SDK raises `HTTPException`/`BotHTTPError` with safe `.status` and `.code`; it never retries a message send automatically. Observe these limits in background loops and batch jobs.

Gateway events include messages/create/delete/edit, member join/remove/update, raw reaction add/remove, cached reaction events, pin updates and visible channel/role/server updates. Extended events are opt-in through the gateway and subscribed automatically by the new library according to the supplied `Intents`. Intents are SDK delivery preferences, not permission grants. `Intents.default()` enables supported guild/message/reaction/content events; `members` must be enabled explicitly. Presence and voice intents are unsupported.

## Existing 0.1 programs

The low-level `from pollakcord import Bot` still accepts `Bot(origin, token)`, `@bot.slash`, raw dictionary `@bot.on_message`, `await interaction.respond(...)`, and `asyncio.run(bot.run())`. Its default disconnect behavior is unchanged; `await bot.start(reconnect=True)` opts into reconnection. The legacy raw message handler skips bot authors. The new `Client`/`commands.Bot` event interface receives bot messages too; prefix command processing ignores bot authors automatically.

## Boundaries

Messages remain text-only for bot sends. File uploads, voice/music bots, DMs/friendships, components/buttons/selects/modals, custom embeds, ephemeral/deferred replies, interaction follow-up webhooks, threads/forums, presence, custom emoji management, full gateway replay/resume, marketplace and Discord monetization are unsupported. Explicit unsupported operations raise `UnsupportedFeature` or `TypeError`; private replies are never silently sent publicly. Attachments and embeds returned by message REST reads are raw metadata, not `discord.py` model objects or bot upload/download support. Human 20 MB/250 MB media policy is unchanged.

DÖK, class spaces, form results, identity reveal and platform staff powers are permanently outside bot access. REST uses `Authorization: Bot <token>` at `/api/v1/bots/api/`, and the gateway is `/api/v1/bots/gateway`. No browser sessions, cookies, credential-bearing URLs, redirects or proxy environment authentication are used. HTTPS is required outside local development.
