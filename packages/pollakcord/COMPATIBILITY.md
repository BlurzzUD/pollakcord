# Moving a discord.py bot to PollákCord

This is a compatibility layer for supported PollákCord capabilities, not a claim of complete Discord feature or protocol parity. The API shapes follow the official [discord.py quickstart](https://discordpy.readthedocs.io/en/stable/quickstart.html), [commands guide](https://discordpy.readthedocs.io/en/stable/ext/commands/commands.html) and [interaction reference](https://discordpy.readthedocs.io/en/stable/interactions/api.html). PollákCord's own backend remains authoritative for all permissions and limits.

## The small port

For a bot that uses supported features, start with these changes:

| Existing code | PollákCord code |
| --- | --- |
| `import discord` | `import pollakcord as discord` |
| `from discord.ext import commands, tasks` | `from pollakcord.ext import commands, tasks` |
| `from discord import app_commands` | `from pollakcord import app_commands` |
| `commands.Bot(command_prefix="!", intents=intents)` | Add `origin="https://your-pollakcord.example"` or set `POLLAKCORD_ORIGIN` |
| `bot.run(DISCORD_TOKEN)` | Use a PollákCord bot token instead |
| Discord server, channel, user and role IDs | Replace with actual PollákCord IDs |

You can retain decorators and handlers such as:

```python
@bot.event
async def on_member_join(member):
    channel = bot.get_channel(WELCOME_CHANNEL_ID)
    if channel is not None and channel.guild.id == member.guild.id:
        await channel.send(f"Welcome, {member.mention}!")


@bot.command()
async def add(ctx, first: int, second: int):
    await ctx.send(first + second)


@bot.tree.command(name="ping", description="Ping the bot")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message("Pong!")
```

Enable `intents.members = True` for welcome events. `Intents` selects supported SDK events; it cannot bypass an install grant, channel overwrite, timeout or school privacy boundary. PollákCord does not reproduce Discord's privileged-intent review system.

## Supported compatibility surface

| Area | Available interface |
| --- | --- |
| Startup | `Client`, `commands.Bot`, `run(token)`, `await start(token)`, `login`, async context manager, `close`, `setup_hook`, `on_ready`, `on_disconnect`, `is_ready`, `is_closed`, `wait_until_ready`, `latency` |
| Events | `@bot.event`, `@bot.listen`, `add_listener`, `remove_listener`, `dispatch`, `wait_for` with a check and timeout |
| Lookups | `guilds`, `get_guild`, `fetch_guild`, async `fetch_guilds`, `get_channel`, `fetch_channel`, cached `get_user`, `Guild.get_member`, `fetch_member`, async `fetch_members`, `fetch_channels`, `fetch_roles` |
| Models | Integer `.id`, user `.name`, `.display_name`, `.mention`, `.bot`; member `.guild`, `.nick`, `.roles`, `.top_role`, `.joined_at`, `.timed_out_until`, `.guild_permissions`; text channel `.name`, `.topic`, `.mention`, `.slowmode_delay`; role `.permissions`, `.position`, `.is_default()` |
| Messages | `channel.send`, `fetch_message`, async `history`, `get_partial_message`, `Message.reply`, `edit(content=...)`, `delete(delay=...)`, `add_reaction`, own `remove_reaction`, `pin`, `unpin`, channel `pins`, optional `delete_after` on sends |
| Prefix commands | `@bot.command`, `@commands.command`, aliases, integer/float/boolean/string and user/member/channel/role converters, quoted arguments, a keyword-only rest argument, defaults, optional arguments, custom `Converter`, `get_context`, `process_commands`, `Context.send/reply` |
| Prefix checks | `check`, `guild_only`, `is_owner`, `has_permissions`, `bot_has_permissions`, `has_role`, bounded local `cooldown` with default/user/member/guild/channel buckets, command-specific `.error`, `on_command_error` |
| Cogs/extensions | Async `add_cog`, `remove_cog`, command and slash decorators on cogs, `Cog.listener`, `cog_load`, `cog_unload`, async `load_extension` with `setup(bot)` |
| Slash commands | `bot.tree.command`, `app_commands.command`, `describe`, `default_permissions`, `check`, `guild_only`, `checks.has_permissions`, tree `sync/get_command/get_commands/add_command/remove_command/clear_commands/error`, typed string/int/bool/User/Member/TextChannel arguments |
| Interactions | `.user`, `.guild`, `.channel`, `.permissions`, `.response.send_message`, `.response.is_done`, `.respond`, `.original_response`, `.edit_original_response`, `.delete_original_response` |
| Moderation | `Member.kick`, `ban(reason=...)`, `timeout(datetime/timedelta/None)`, `edit(nick=...)`, `Guild.kick/ban/unban`, async `Guild.bans` (up to 200) |
| Server settings/audit | `Guild.edit(name=..., description=...)`, async `Guild.audit_logs`; entries expose IDs, native action strings and timestamps only |
| Roles/channels | `Guild.create_role`, `Role.edit/delete`, `Member.add_roles/remove_roles`, `Guild.create_text_channel`, `TextChannel.edit/delete`, bot's effective `permissions_for(guild.me)` |
| Invites | `TextChannel.create_invite`, `Guild.invites`, `Invite.delete`, `.url`, `.code`, `.uses`, `.max_uses`, `.expires_at` |
| Utilities/tasks | `utils.get`, `find`, `utcnow`, `escape_markdown`, `escape_mentions`; `@tasks.loop(seconds/minutes/hours/count)`, `start`, `stop`, `cancel`, `is_running`, `get_task`, `before_loop`, `after_loop`, `error`, `change_interval` |

Prefix callbacks behave like `discord.py`: overriding `on_message` replaces automatic command processing, so call `await bot.process_commands(message)` in that override. Use a listener to observe messages without replacing the default handler. Human-facing SDK help text is developer-controlled text in the user-hosted process.

## Events and cache behavior

`on_message`, cached `on_message_delete`/`on_message_edit`, `on_raw_message_delete`/`on_raw_message_edit`, `on_member_join`/`on_member_remove`, cached `on_member_update`, `on_raw_member_update`, `on_raw_reaction_add`/`on_raw_reaction_remove`, cached `on_reaction_add`/`on_reaction_remove`, `on_guild_channel_pins_update`, `on_guild_channel_create/update/delete`, `on_guild_role_create/update/delete` and `on_guild_update` are supported. Raw payload IDs are integers. Raw reaction `.emoji` is a supported Unicode string. A cached reaction callback can receive a minimal user with an ID and no cached username; fetch a current member within the server when needed. Pin events do not include a last-pin timestamp, so that callback's second argument is `None`.

Initial readiness populates visible servers, text channels and roles, not a full member list. `Guild.members` is a partial cache; use `fetch_members` when necessary. Message caches are bounded, and delete/edit rich events require a cached original. Raw events are available without the original. A message author may be a partial member without role information; fetch that member or use the permission-check decorators for current authorization. `Member.guild_permissions` does not compute channel overwrites; `has_permissions` queries effective channel permissions from the server.

Channel and role changes refresh the visible channel cache and prune cached messages whose channels become inaccessible. Visibility loss can produce `on_guild_channel_delete` in this SDK even when the underlying channel still exists. All mutating REST operations independently recheck the current backend state. Previously obtained Python objects are snapshots and do not authorize later actions.

Connections automatically retry transient failures with exponential backoff and jitter, capped around one minute. Revoked/disabled/invalid credentials and explicit gateway denials stop reconnecting. A new connection rebuilds the caches; there is no replay queue, sequence resume or exactly-once delivery across reconnects. Member joins while offline are missed. The original low-level `Bot.run()` retains its one-shot behavior for existing programs.

## Deliberate differences

Commands are registered for the application and available only in installed servers. `tree.sync(guild=...)`, command groups/subcommands, dynamic slash option autocomplete, choices, hybrid commands and user/message context commands are not implemented. At most 25 slash commands with 10 options each are supported; float slash options are unsupported. Prefix command groups and the full discord.py converter/error/hook catalogue are also unsupported. `CommandTree` automatically syncs once through the default `setup_hook`, which differs from discord.py's explicit sync requirement.

Slash replies must be public and arrive within three seconds. `ephemeral=True` and `response.defer()` raise `UnsupportedFeature` without publishing anything. There are no follow-up interaction webhooks. Editing/deleting a successful public original response uses the bot's normal own-message API and permission checks.

Permission bit values are PollákCord's values. Do not paste Discord permission integers; use named flags. Aliases include `manage_guild` → `manage_server`, `moderate_members` → `manage_members`, `read_messages` → `view_channel`, and `create_instant_invite` → `create_invite`. Unsupported flags are rejected. Bots cannot obtain Administrator, voice or school/platform powers. Roles default below the bot, and bots cannot grant permissions they lack. Human server owners can reposition the managed bot role through the existing role UI; the install permission ceiling still applies.

Timeouts round up to whole minutes and are limited to 28 days. Invite expiration rounds up to whole hours. Reactions are limited to the platform's existing fixed set. Bans require a current server member, and bots cannot moderate other bots, their human owner, the server owner, or equal/higher roles. Bot role edits are restricted to custom roles below the bot. The generic SDK `reason` argument is available for bans; other moderation reason arguments are unsupported. No server ownership transfers, global user lookup or identity/profile enrichment are exposed.

The SDK surfaces HTTP 429 errors instead of retrying writes automatically. Rate limits are PollákCord's stricter bot/owner limits, not Discord buckets. `.status` and `.code` on `HTTPException`, `Forbidden` and `NotFound` are available; Discord-specific response/text/code semantics and exception subclasses are not reproduced. `on_error` receives the event name and exception type name, keeping credentials out of default logs.

Voice, DMs, arbitrary embeds, uploads, buttons/selects/modals, threads/forums, webhooks, presence, custom emoji management, full extension unload/reload lifecycle and Discord-only products are outside this release. Unknown arguments are rejected instead of silently ignored. Third-party extensions that import `discord` internally need their own port; changing your main script's import does not redirect those imports. Never monkeypatch the installed `discord` module to bypass those differences.

The host application must run this matching backend and migration `0007`; publishing only the new SDK does not add server capabilities. Keep DÖK, class spaces, form results, identities, platform staff tools and all human media policy outside bot access.
