from __future__ import annotations

import copy
import inspect
import re
import shlex
import time
from collections import OrderedDict
from enum import Enum
from types import MethodType
from typing import get_type_hints

from .. import app_commands
from ..client import UnsupportedFeature
from ..compat import Client
from ..objects import Member, Permissions, Role, TextChannel, User


class CommandError(Exception):
    pass


class CommandNotFound(CommandError):
    pass


class BadArgument(CommandError):
    pass


class MissingRequiredArgument(CommandError):
    def __init__(self, parameter) -> None:
        self.param = parameter
        super().__init__(f"Missing required argument: {parameter.name}")


class CheckFailure(CommandError):
    pass


class MissingPermissions(CheckFailure):
    def __init__(self, permissions: list[str]) -> None:
        self.missing_permissions = permissions
        super().__init__("Missing permissions: " + ", ".join(permissions))


class CommandOnCooldown(CommandError):
    def __init__(self, retry_after: float) -> None:
        self.retry_after = retry_after
        super().__init__("This command is on cooldown")


class BucketType(Enum):
    default = "default"
    user = "user"
    member = "member"
    guild = "guild"
    channel = "channel"


class Converter:
    async def convert(self, ctx, argument: str):
        return argument


def _callback(target):
    return target.callback if isinstance(target, Command) else target


def check(predicate):
    def decorator(target):
        callback = _callback(target)
        callback.__pollak_prefix_checks__ = [*getattr(callback, "__pollak_prefix_checks__", []), predicate]
        return target
    return decorator


def guild_only():
    return check(lambda ctx: ctx.guild is not None)


def is_owner():
    return check(lambda ctx: ctx.author is not None and ctx.author.id == ctx.bot.owner_id)


def has_permissions(**permissions: bool):
    Permissions(**permissions)
    async def predicate(ctx):
        data = await ctx.bot._request("GET", f"channels/{ctx.channel.id}/members/{ctx.author.id}")
        actual = Permissions(data["permissions"])
        missing = [name for name, enabled in permissions.items() if getattr(actual, name) != enabled]
        if missing:
            raise MissingPermissions(missing)
        return True
    return check(predicate)


def bot_has_permissions(**permissions: bool):
    Permissions(**permissions)
    async def predicate(ctx):
        channel = await ctx.bot.fetch_channel(ctx.channel.id)
        actual = channel.permissions_for(channel.guild.me)
        missing = [name for name, enabled in permissions.items() if getattr(actual, name) != enabled]
        if missing:
            raise MissingPermissions(missing)
        return True
    return check(predicate)


def has_role(item):
    async def predicate(ctx):
        member = await ctx.guild.fetch_member(ctx.author.id)
        return any(role.id == item if isinstance(item, int) else role.name == item for role in member.roles)
    return check(predicate)


def cooldown(rate: int, per: float, type: BucketType = BucketType.default):
    if rate < 1 or per <= 0 or not isinstance(type, BucketType):
        raise ValueError("Invalid cooldown")
    def decorator(target):
        _callback(target).__pollak_cooldown__ = (rate, per, type)
        return target
    return decorator


class Context:
    def __init__(self, bot: Bot, message, *, prefix: str = "", invoked_with: str = "", command: Command | None = None, argument_text: str = "") -> None:
        self.bot = bot
        self.message = message
        self.guild = message.guild
        self.channel = message.channel
        self.author = message.author
        self.prefix = prefix
        self.invoked_with = invoked_with
        self.command = command
        self.argument_text = argument_text
        self.command_failed = False

    @property
    def valid(self) -> bool:
        return self.command is not None

    async def send(self, content, **kwargs):
        return await self.channel.send(content, **kwargs)

    async def reply(self, content, **kwargs):
        return await self.message.reply(content, **kwargs)

    @classmethod
    def __class_getitem__(cls, _item):
        return cls


async def _convert(ctx: Context, parameter, annotation, value: str):
    if annotation in (inspect.Parameter.empty, str):
        return value
    annotation, _ = app_commands._optional(annotation)
    if annotation is bool:
        lowered = value.lower()
        if lowered in ("yes", "y", "true", "t", "1", "enable", "on"):
            return True
        if lowered in ("no", "n", "false", "f", "0", "disable", "off"):
            return False
        raise BadArgument("Expected a boolean")
    if annotation in (Member, User, TextChannel, Role):
        matched = re.fullmatch(r"(?:<[@#](?:[!&])?)?([0-9]{1,19})>?", value)
        if matched:
            object_id = int(matched[1])
            if annotation in (Member, User):
                return await ctx.guild.fetch_member(object_id)
            item = ctx.guild.get_channel(object_id) if annotation is TextChannel else ctx.guild.get_role(object_id)
        elif annotation in (Member, User):
            item = None
            async for member in ctx.guild.fetch_members(limit=None):
                if value in (member.name, member.display_name):
                    item = member
                    break
        else:
            items = ctx.guild.channels if annotation is TextChannel else ctx.guild.roles
            item = next((item for item in items if item.name == value), None)
        if item is None:
            raise BadArgument(f"No matching {annotation.__name__} in this server")
        return item
    try:
        converter = annotation() if inspect.isclass(annotation) and issubclass(annotation, Converter) else annotation
        converted = converter.convert(ctx, value) if isinstance(converter, Converter) else converter(value)
        return await converted if inspect.isawaitable(converted) else converted
    except (ValueError, TypeError) as error:
        raise BadArgument(f"Invalid argument: {parameter.name}") from error


class Command:
    def __init__(self, callback, *, name: str | None = None, aliases: list[str] | None = None, help: str | None = None, hidden: bool = False) -> None:
        if not inspect.iscoroutinefunction(callback):
            raise TypeError("Command callbacks must be async functions")
        self.callback = callback
        self.name = name or callback.__name__
        self.aliases = list(aliases or [])
        if any(not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", value) for value in [self.name, *self.aliases]):
            raise ValueError("Invalid command name or alias")
        self.help = help or inspect.getdoc(callback) or ""
        self.hidden = hidden
        self._error_handler = None
        self._buckets = OrderedDict()

    def error(self, callback):
        self._error_handler = callback
        return callback

    def _cooldown(self, ctx: Context) -> None:
        setting = getattr(self.callback, "__pollak_cooldown__", None)
        if setting is None:
            return
        rate, per, bucket = setting
        key = {BucketType.default: 0, BucketType.user: ctx.author.id, BucketType.guild: ctx.guild.id, BucketType.channel: ctx.channel.id, BucketType.member: (ctx.guild.id, ctx.author.id)}[bucket]
        now = time.monotonic()
        hits = [hit for hit in self._buckets.get(key, []) if now - hit < per]
        if len(hits) >= rate:
            raise CommandOnCooldown(per - (now - hits[0]))
        self._buckets[key] = [*hits, now]
        self._buckets.move_to_end(key)
        while len(self._buckets) > 2048:
            self._buckets.popitem(last=False)

    async def invoke(self, ctx: Context) -> None:
        for predicate in [*ctx.bot._checks, *getattr(self.callback, "__pollak_prefix_checks__", [])]:
            allowed = predicate(ctx)
            if inspect.isawaitable(allowed):
                allowed = await allowed
            if not allowed:
                raise CheckFailure("The command check failed")
        self._cooldown(ctx)
        try:
            tokens = shlex.split(ctx.argument_text)
        except ValueError as error:
            raise BadArgument("Unclosed quote") from error
        parameters = list(inspect.signature(self.callback).parameters.values())[1:]
        hints = get_type_hints(self.callback)
        args, kwargs = [ctx], {}
        cursor = 0
        for parameter in parameters:
            annotation = hints.get(parameter.name, parameter.annotation)
            _, optional = app_commands._optional(annotation)
            if parameter.kind is parameter.VAR_KEYWORD:
                raise UnsupportedFeature("Prefix commands cannot use **kwargs")
            if parameter.kind is parameter.VAR_POSITIONAL:
                for value in tokens[cursor:]:
                    args.append(await _convert(ctx, parameter, annotation, value))
                cursor = len(tokens)
                continue
            if cursor >= len(tokens):
                if parameter.default is parameter.empty and not optional:
                    raise MissingRequiredArgument(parameter)
                value = parameter.default if parameter.default is not parameter.empty else None
            else:
                raw = " ".join(tokens[cursor:]) if parameter.kind is parameter.KEYWORD_ONLY else tokens[cursor]
                try:
                    value = await _convert(ctx, parameter, annotation, raw)
                    cursor = len(tokens) if parameter.kind is parameter.KEYWORD_ONLY else cursor + 1
                except BadArgument:
                    if not optional or parameter.kind is parameter.KEYWORD_ONLY:
                        raise
                    value = parameter.default if parameter.default is not parameter.empty else None
            if parameter.kind is parameter.KEYWORD_ONLY:
                kwargs[parameter.name] = value
            else:
                args.append(value)
        if cursor < len(tokens):
            raise BadArgument("Too many arguments")
        await self.callback(*args, **kwargs)


def command(*, name: str | None = None, aliases: list[str] | None = None, help: str | None = None, hidden: bool = False):
    def decorator(callback):
        return Command(callback, name=name, aliases=aliases, help=help, hidden=hidden)
    return decorator


def when_mentioned(bot, message) -> list[str]:
    return [f"<@{bot.user.id}> ", f"<@!{bot.user.id}> "] if bot.user else []


def when_mentioned_or(*prefixes: str):
    return lambda bot, message: [*when_mentioned(bot, message), *prefixes]


class Cog:
    @classmethod
    def listener(cls, name: str | None = None):
        def decorator(callback):
            callback.__pollak_listener__ = name or callback.__name__
            return callback
        return decorator


class Bot(Client):
    def __init__(self, command_prefix="!", *, origin: str | None = None, intents=None, help_command=True, max_messages: int = 1000) -> None:
        super().__init__(origin=origin, intents=intents, max_messages=max_messages)
        self.command_prefix = command_prefix
        self.all_commands: dict[str, Command] = {}
        self._checks: list = []
        self.cogs: dict[str, Cog] = {}
        self._cog_bindings: dict[str, list] = {}
        if help_command is not None and help_command is not False:
            async def help_callback(ctx):
                names = sorted(item.name for item in self.commands if not item.hidden)
                await ctx.send("Commands: " + ", ".join(ctx.prefix + name for name in names))
            self.add_command(Command(help_callback, name="help"))

    @property
    def commands(self) -> set[Command]:
        return set(self.all_commands.values())

    def command(self, **kwargs):
        def decorator(callback):
            item = command(**kwargs)(callback)
            self.add_command(item)
            return item
        return decorator

    def add_command(self, command: Command) -> None:
        names = [command.name, *command.aliases]
        if len(set(names)) != len(names) or any(name in self.all_commands for name in names):
            raise ValueError("Command name or alias is already registered")
        for name in names:
            self.all_commands[name] = command

    def get_command(self, name: str) -> Command | None:
        return self.all_commands.get(name)

    def remove_command(self, name: str) -> Command | None:
        item = self.all_commands.get(name)
        if item:
            self.all_commands = {key: value for key, value in self.all_commands.items() if value is not item}
        return item

    def add_check(self, predicate) -> None:
        self._checks.append(predicate)

    async def get_prefix(self, message):
        prefix = self.command_prefix
        if callable(prefix):
            prefix = prefix(self, message)
            if inspect.isawaitable(prefix):
                prefix = await prefix
        values = [prefix] if isinstance(prefix, str) else list(prefix)
        if any(not isinstance(value, str) or not value for value in values):
            raise ValueError("Prefixes must be nonempty strings")
        return values

    async def get_context(self, message) -> Context:
        prefix = next((prefix for prefix in await self.get_prefix(message) if message.content.startswith(prefix)), "")
        if not prefix:
            return Context(self, message)
        parts = message.content[len(prefix):].lstrip().split(None, 1)
        name = parts[0] if parts else ""
        return Context(self, message, prefix=prefix, invoked_with=name, command=self.get_command(name), argument_text=parts[1] if len(parts) > 1 else "")

    async def process_commands(self, message) -> None:
        if message.author is None or message.author.bot or message.guild is None:
            return
        ctx = await self.get_context(message)
        if not ctx.prefix or not ctx.invoked_with:
            return
        try:
            if ctx.command is None:
                raise CommandNotFound(ctx.invoked_with)
            await ctx.command.invoke(ctx)
            await self._emit("command_completion", ctx)
        except Exception as error:
            ctx.command_failed = True
            if ctx.command and ctx.command._error_handler:
                await ctx.command._error_handler(ctx, error)
            else:
                await self._emit("command_error", ctx, error)

    async def on_message(self, message) -> None:
        await self.process_commands(message)

    async def on_command_error(self, ctx, error) -> None:
        await self.on_error("command", type(error).__name__)

    async def add_cog(self, cog: Cog, *, override: bool = False) -> None:
        name = type(cog).__name__
        if name in self.cogs:
            if not override:
                raise ValueError("Cog is already loaded")
            await self.remove_cog(name)
        bindings = []
        try:
            for attribute in dir(type(cog)):
                original = getattr(type(cog), attribute)
                if isinstance(original, Command):
                    item = copy.copy(original)
                    item.callback = MethodType(original.callback, cog)
                    item._buckets = OrderedDict()
                    if original._error_handler:
                        item._error_handler = MethodType(original._error_handler, cog)
                    self.add_command(item)
                    bindings.append(("command", item))
                elif isinstance(original, app_commands.Command):
                    item = copy.copy(original)
                    item.callback = MethodType(original.callback, cog)
                    self.tree.add_command(item)
                    bindings.append(("slash", item))
                elif hasattr(original, "__pollak_listener__"):
                    callback = getattr(cog, attribute)
                    self.add_listener(callback, original.__pollak_listener__)
                    bindings.append((original.__pollak_listener__, callback))
            if hasattr(cog, "cog_load"):
                await cog.cog_load()
        except Exception:
            self._remove_bindings(bindings)
            raise
        self.cogs[name] = cog
        self._cog_bindings[name] = bindings

    def _remove_bindings(self, bindings) -> None:
        for kind, item in bindings:
            if kind == "command":
                self.remove_command(item.name)
            elif kind == "slash":
                self.tree.remove_command(item.name)
            else:
                self.remove_listener(item, kind)

    async def remove_cog(self, name: str) -> Cog | None:
        cog = self.cogs.pop(name, None)
        if cog:
            self._remove_bindings(self._cog_bindings.pop(name, []))
            if hasattr(cog, "cog_unload"):
                result = cog.cog_unload()
                if inspect.isawaitable(result):
                    await result
        return cog
