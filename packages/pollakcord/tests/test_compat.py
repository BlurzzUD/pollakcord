import asyncio
import json
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pollakcord as discord
from pollakcord import app_commands
from pollakcord.ext import commands, tasks

SERVER = {"id": "5", "name": "School server", "description": "", "owner_id": "1", "my_permissions": 15, "my_role_ids": ["8"], "roles": [{"id": "2", "name": "Member", "permissions": 7, "position": 0, "is_default": True}, {"id": "8", "name": "Bot", "permissions": 15, "position": 1, "kind": "bot"}], "channels": [{"id": "3", "server_id": "5", "name": "welcome", "type": "text", "my_permissions": 15}]}
USER = {"id": "7", "username": "anna", "display_name": "Anna", "is_bot": False}
BOT = {"id": "9", "username": "helper", "display_name": "Helper", "is_bot": True}


def message(content="Hello", *, author=None, id="10"):
    return {"id": id, "channel_id": "3", "server_id": "5", "scope": "channel", "content": content, "author": author or USER, "created_at": "2026-01-01T10:00:00Z"}


async def mock_client(client):
    seen = []
    def transport(request):
        assert request.headers["Authorization"] == "Bot test-secret"
        assert "cookie" not in request.headers
        body = json.loads(request.content) if request.content else None
        path = request.url.path.removeprefix("/api/v1/bots/api/")
        seen.append((request.method, path, body, dict(request.url.params)))
        if path == "me":
            data = {"user": BOT, "owner_id": "1"}
        elif path == "servers":
            data = [{"id": "5", "name": "School server"}]
        elif path == "servers/5":
            data = SERVER
        elif path == "channels/3":
            data = SERVER["channels"][0]
        elif path == "commands":
            data = [{"id": "21", "name": row["name"]} for row in (body or {}).get("commands", [])]
        elif path == "servers/5/members/7":
            data = {"user": USER, "nickname": "Anni", "role_ids": ["2"], "joined_at": "2026-01-01T10:00:00Z"}
        elif path == "channels/3/members/7":
            data = {"user": USER, "permissions": 7}
        elif request.method == "POST" and path in ("channels/3/messages", "interactions/20/response"):
            data = message(body["content"], author=BOT, id="30")
        elif request.method == "PATCH" and path == "channels/3/messages/30":
            data = {**message(body["content"], author=BOT, id="30"), "edited_at": "2026-01-01T10:01:00Z"}
        elif path == "channels/3/messages":
            data = {"messages": [message("older", id="10"), message("newer", id="11")], "has_more": False}
        elif path == "channels/3/pins":
            data = [message("Pinned", id="11")]
        else:
            data = {"status": "ok"}
        return httpx.Response(200, json=data)
    await client._transport._http.aclose()
    client._transport._http = httpx.AsyncClient(base_url=client.origin + "/api/v1/bots/api/", transport=httpx.MockTransport(transport), follow_redirects=False, trust_env=False)
    await client.login("test-secret")
    await client._receive({"t": "ready", "d": {"user": BOT}})
    return seen


def test_ported_prefix_and_slash_ping_use_discord_style_objects_and_paths():
    async def scenario():
        bot = commands.Bot(command_prefix="!", origin="https://school.example", help_command=None)
        @bot.command()
        async def ping(ctx: commands.Context):
            assert isinstance(ctx.author, discord.Member)
            assert ctx.guild.id == 5 and ctx.channel.id == 3
            await ctx.send("Pong!")
        @bot.tree.command(name="ping", description="Ping")
        async def slash(interaction: discord.Interaction):
            assert isinstance(interaction.user, discord.Member)
            assert interaction.user.name == "anna"
            await interaction.response.send_message("Slash Pong!")
            assert interaction.response.is_done()
        seen = await mock_client(bot)
        await bot._receive({"t": "message.create", "d": message("!ping")})
        await bot._receive({"t": "interaction.create", "d": {"id": "20", "name": "ping", "channel_id": "3", "server_id": "5", "user": USER, "permissions": 7}})
        assert ("POST", "channels/3/messages", {"content": "Pong!"}, {}) in seen
        assert ("POST", "interactions/20/response", {"content": "Slash Pong!"}, {}) in seen
        assert bot.user.bot and bot.user.id == 9
        await bot.close()
    asyncio.run(scenario())


def test_member_join_handler_has_username_guild_and_channel_send():
    async def scenario():
        intents = discord.Intents.default()
        intents.members = True
        bot = commands.Bot(origin="https://school.example", intents=intents, help_command=None)
        joins = []
        @bot.event
        async def on_member_join(member):
            joins.append(member)
            await bot.get_channel(3).send(f"Welcome, {member.name}!")
        seen = await mock_client(bot)
        await bot._receive({"t": "member.joined", "d": {"server_id": "5", "user_id": "7", "member": {"user": USER, "role_ids": ["2"]}}})
        assert joins[0].guild is bot.get_guild(5)
        assert joins[0].mention == "<@7>"
        assert ("POST", "channels/3/messages", {"content": "Welcome, anna!"}, {}) in seen
        assert bot.get_guild(5).get_member(7) is joins[0]
        await bot.close()
    asyncio.run(scenario())


def test_prefix_converters_aliases_rest_boolean_checks_and_cooldowns():
    async def scenario():
        bot = commands.Bot(origin="https://school.example", help_command=None)
        results, errors = [], []
        @bot.command(aliases=["sum"])
        async def add(ctx, a: int, b: int, enabled: bool = True, *, label: str = "result"):
            results.append((a + b, enabled, label))
        @bot.command()
        @commands.has_permissions(manage_messages=True)
        async def protected(ctx):
            pytest.fail("A user without the checked permission invoked the command")
        @bot.command()
        @commands.cooldown(1, 30, commands.BucketType.user)
        async def once(ctx):
            results.append("once")
        @bot.event
        async def on_command_error(ctx, error):
            errors.append(error)
        await mock_client(bot)
        await bot._receive({"t": "message.create", "d": message('!sum 2 3 false "two words"')})
        await bot._receive({"t": "message.create", "d": message("!add nope 3")})
        await bot._receive({"t": "message.create", "d": message("!protected")})
        await bot._receive({"t": "message.create", "d": message("!once")})
        await bot._receive({"t": "message.create", "d": message("!once")})
        await bot._receive({"t": "message.create", "d": message("!once", author=BOT)})
        assert results == [(5, False, "two words"), "once"]
        assert isinstance(errors[0], commands.BadArgument)
        assert isinstance(errors[1], commands.MissingPermissions)
        assert isinstance(errors[2], commands.CommandOnCooldown)
        assert len(errors) == 3
        await bot.close()
    asyncio.run(scenario())


def test_typed_slash_options_descriptions_defaults_and_effective_permissions():
    async def scenario():
        bot = commands.Bot(origin="https://school.example", help_command=None)
        calls = []
        @bot.tree.command(description="Typed options")
        @app_commands.describe(person="Choose a person", count="How many")
        @app_commands.default_permissions(manage_messages=True)
        async def greet(interaction, person: discord.Member, count: int = 1, enabled: bool = True):
            calls.append((person.name, count, enabled))
            await interaction.response.send_message("Done")
        seen = await mock_client(bot)
        definition = next(item[2]["commands"][0] for item in seen if item[1] == "commands")
        assert definition["default_member_permissions"] == ["manage_messages"]
        assert definition["options"] == [
            {"name": "person", "description": "Choose a person", "type": "user", "required": True},
            {"name": "count", "description": "How many", "type": "int", "required": False},
            {"name": "enabled", "description": "Enabled", "type": "bool", "required": False},
        ]
        await bot._receive({"t": "interaction.create", "d": {"id": "20", "name": "greet", "options": {"person": "7", "count": 2}, "channel_id": "3", "server_id": "5", "user": USER}})
        assert calls == [("anna", 2, True)]
        await bot.close()
    asyncio.run(scenario())


def test_message_methods_reply_edit_reactions_pins_and_history_order():
    async def scenario():
        bot = discord.Client(origin="https://school.example")
        seen = await mock_client(bot)
        channel = bot.get_channel(3)
        sent = await channel.send("Original")
        assert isinstance(sent, discord.Message) and sent.author.bot
        edited = await sent.edit(content="Edited")
        assert edited.content == "Edited" and edited.edited_at
        await sent.reply("Reply")
        await sent.add_reaction("🎉")
        await sent.remove_reaction("🎉", bot.user)
        await sent.pin()
        await sent.unpin()
        assert [item.id for item in await channel.pins()] == [11]
        assert [item.id async for item in channel.history()] == [11, 10]
        assert [item.id async for item in channel.history(after=discord.Object(1))] == [10, 11]
        assert ("POST", "channels/3/messages", {"content": "Reply", "reply_to_id": "30"}, {}) in seen
        await sent.delete()
        assert sent.deleted
        await bot.close()
    asyncio.run(scenario())


def test_wait_for_and_additional_listeners_preserve_on_message_override():
    async def scenario():
        bot = commands.Bot(origin="https://school.example", help_command=None)
        called = []
        @bot.command()
        async def ping(ctx):
            called.append("command")
        @bot.event
        async def on_message(message):
            called.append("event")
            await bot.process_commands(message)
        @bot.listen("on_message")
        async def extra(message):
            called.append("listener")
        await mock_client(bot)
        waiter = asyncio.create_task(bot.wait_for("message", check=lambda message: message.author.id == 7, timeout=1))
        await asyncio.sleep(0)
        await bot._receive({"t": "message.create", "d": message("!ping")})
        assert (await waiter).content == "!ping"
        assert called == ["event", "command", "listener"]
        assert bot._waiters == {}
        with pytest.raises(asyncio.TimeoutError):
            await bot.wait_for("missing", timeout=0.001)
        assert bot._waiters == {}
        await bot.close()
    asyncio.run(scenario())


def test_cogs_prefix_slash_listeners_and_removal():
    class Greetings(commands.Cog):
        def __init__(self):
            self.events = []
        @commands.command()
        async def hello(self, ctx):
            await ctx.send("Hello from a cog")
        @app_commands.command(description="Cog slash")
        async def hi(self, interaction):
            await interaction.response.send_message("Hi from a cog")
        @commands.Cog.listener()
        async def on_message(self, message):
            self.events.append(message.content)
    async def scenario():
        bot = commands.Bot(origin="https://school.example", help_command=None)
        cog = Greetings()
        await bot.add_cog(cog)
        seen = await mock_client(bot)
        await bot._receive({"t": "message.create", "d": message("!hello")})
        await bot._receive({"t": "interaction.create", "d": {"id": "20", "name": "hi", "channel_id": "3", "server_id": "5", "user": USER}})
        assert cog.events == ["!hello"]
        assert any(item[2] == {"content": "Hello from a cog"} for item in seen)
        assert any(item[2] == {"content": "Hi from a cog"} for item in seen)
        assert await bot.remove_cog("Greetings") is cog
        assert bot.get_command("hello") is None and bot.tree.get_command("hi") is None
        await bot.close()
    asyncio.run(scenario())


def test_task_loop_lifecycle_and_independent_cog_instances():
    class Timer:
        def __init__(self):
            self.values = []
        @tasks.loop(seconds=0, count=2)
        async def tick(self):
            self.values.append("tick")
        @tick.before_loop
        async def before(self):
            self.values.append("before")
        @tick.after_loop
        async def after(self):
            self.values.append("after")
    async def scenario():
        first, second = Timer(), Timer()
        assert first.tick is not second.tick
        await first.tick.start()
        assert first.values == ["before", "tick", "tick", "after"]
        assert second.values == [] and first.tick.current_loop == 2
        assert not first.tick.is_running() and not first.tick.failed()
    asyncio.run(scenario())


def test_cache_is_bounded_and_channel_revocation_prunes_cached_messages():
    async def scenario():
        bot = discord.Client(origin="https://school.example", max_messages=1)
        removed = []
        @bot.event
        async def on_guild_channel_delete(channel):
            removed.append(channel.id)
        await mock_client(bot)
        await bot._receive({"t": "message.create", "d": message(id="10")})
        await bot._receive({"t": "message.create", "d": message(id="11")})
        assert [item.id for item in bot.cached_messages] == [11]
        await bot._receive({"t": "structure.changed", "d": {"server_id": "5", "channels": []}})
        assert removed == [3] and bot.cached_messages == [] and bot.get_channel(3) is None
        await bot.close()
    asyncio.run(scenario())


def test_explicit_unsupported_operations_do_not_silently_publish_or_elevate():
    with pytest.raises(discord.UnsupportedFeature):
        discord.Permissions(manage_webhooks=True)
    with pytest.raises(discord.UnsupportedFeature):
        discord.Intents(voice_states=True)
    async def scenario():
        bot = discord.Client(origin="https://school.example")
        seen = await mock_client(bot)
        interaction = discord.Interaction(bot, {"id": "20", "name": "ping", "server_id": "5", "channel_id": "3", "user": USER})
        before = len(seen)
        with pytest.raises(discord.UnsupportedFeature):
            await interaction.response.send_message("Private", ephemeral=True)
        with pytest.raises(discord.UnsupportedFeature):
            await interaction.response.defer()
        with pytest.raises(discord.UnsupportedFeature):
            await bot.tree.sync(guild=discord.Object(5))
        with pytest.raises(discord.UnsupportedFeature):
            await bot.fetch_user(7)
        assert len(seen) == before and not interaction.response.is_done()
        await interaction.response.send_message("Public")
        with pytest.raises(RuntimeError):
            await interaction.response.send_message("Duplicate")
        await bot.close()
    asyncio.run(scenario())


def test_raw_and_cached_edit_delete_reaction_and_pin_events():
    async def scenario():
        bot = discord.Client(origin="https://school.example")
        seen = []
        @bot.event
        async def on_message_edit(before, after):
            seen.append(("edit", before.content, after.content))
        @bot.event
        async def on_message_delete(message):
            seen.append(("delete", message.id))
        @bot.event
        async def on_reaction_add(reaction, user):
            seen.append(("reaction", str(reaction), user.id))
        @bot.event
        async def on_guild_channel_pins_update(channel, last_pin):
            seen.append(("pin", channel.id, last_pin))
        await mock_client(bot)
        await bot._receive({"t": "message.create", "d": message("Before")})
        await bot._receive({"t": "message.update", "d": message("After")})
        await bot._receive({"t": "reaction.update", "d": {"message_id": "10", "channel_id": "3", "server_id": "5", "user_id": "7", "emoji": "🎉", "present": True}})
        await bot._receive({"t": "message.pin", "d": {"id": "10", "channel_id": "3", "server_id": "5", "pinned": True}})
        await bot._receive({"t": "message.delete", "d": {"id": "10", "channel_id": "3", "server_id": "5"}})
        assert seen == [("edit", "Before", "After"), ("reaction", "🎉", 7), ("pin", 3, None), ("delete", 10)]
        assert bot.cached_messages == []
        await bot.close()
    asyncio.run(scenario())
