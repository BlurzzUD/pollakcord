from __future__ import annotations

import inspect
import types
from types import SimpleNamespace
from typing import Union, get_args, get_origin, get_type_hints

from .client import UnsupportedFeature
from .objects import Member, Permissions, TextChannel, User


class AppCommandError(Exception):
    pass


class CheckFailure(AppCommandError):
    pass


def _optional(annotation):
    if get_origin(annotation) in (Union, types.UnionType):
        values = [value for value in get_args(annotation) if value is not type(None)]
        if len(values) == 1 and len(values) != len(get_args(annotation)):
            return values[0], True
    return annotation, False


def _metadata(target):
    return target.callback if isinstance(target, Command) else target


def describe(**descriptions: str):
    def decorator(target):
        callback = _metadata(target)
        callback.__pollak_descriptions__ = {**getattr(callback, "__pollak_descriptions__", {}), **descriptions}
        return target
    return decorator


def default_permissions(**permissions: bool):
    value = Permissions(**permissions)
    def decorator(target):
        _metadata(target).__pollak_permissions__ = value
        return target
    return decorator


def check(predicate):
    def decorator(target):
        callback = _metadata(target)
        callback.__pollak_checks__ = [*getattr(callback, "__pollak_checks__", []), predicate]
        return target
    return decorator


def guild_only():
    return check(lambda interaction: interaction.guild is not None)


class Command:
    def __init__(self, callback, *, name: str | None = None, description: str | None = None) -> None:
        if not inspect.iscoroutinefunction(callback):
            raise TypeError("Slash handlers must be async functions")
        self.callback = callback
        self.name = name or callback.__name__
        self.description = description or inspect.getdoc(callback) or self.name.replace("_", " ").capitalize()
        self.description = self.description.splitlines()[0][:100]

    def _parameters(self):
        parameters = list(inspect.signature(self.callback).parameters.values())
        if not parameters:
            raise TypeError("Slash handlers need an interaction parameter")
        hints = get_type_hints(self.callback)
        for parameter in parameters[1:]:
            if parameter.kind in (parameter.VAR_POSITIONAL, parameter.VAR_KEYWORD):
                raise UnsupportedFeature("Slash handlers cannot use variadic arguments")
            annotation, optional = _optional(hints.get(parameter.name, str))
            yield parameter, annotation, optional

    def definition(self) -> dict:
        descriptions = getattr(self.callback, "__pollak_descriptions__", {})
        if set(descriptions) - {parameter.name for parameter, _, _ in self._parameters()}:
            raise ValueError("An option description names an unknown parameter")
        options = []
        kinds = {str: "string", int: "int", bool: "bool", User: "user", Member: "user", TextChannel: "channel"}
        for parameter, annotation, optional in self._parameters():
            if annotation not in kinds:
                raise UnsupportedFeature(f"Slash option type {annotation} is not supported")
            options.append({"name": parameter.name, "description": descriptions.get(parameter.name, parameter.name.replace("_", " ").capitalize()), "type": kinds[annotation], "required": parameter.default is parameter.empty and not optional})
        return {"name": self.name, "description": self.description, "options": options, "default_member_permissions": getattr(self.callback, "__pollak_permissions__", Permissions.none()).names()}

    async def invoke(self, interaction) -> None:
        for predicate in getattr(self.callback, "__pollak_checks__", []):
            allowed = predicate(interaction)
            if inspect.isawaitable(allowed):
                allowed = await allowed
            if not allowed:
                raise CheckFailure("The command check failed")
        values = {}
        for parameter, annotation, optional in self._parameters():
            if parameter.name not in interaction.options:
                if parameter.default is not parameter.empty:
                    values[parameter.name] = parameter.default
                elif optional:
                    values[parameter.name] = None
                else:
                    raise AppCommandError("A required option is missing")
                continue
            value = interaction.options[parameter.name]
            if annotation is TextChannel:
                value = interaction.client.get_channel(int(value)) or await interaction.client.fetch_channel(int(value))
            elif annotation in (User, Member):
                if interaction.guild is None:
                    raise AppCommandError("This option requires a server")
                value = interaction.guild.get_member(int(value)) or await interaction.guild.fetch_member(int(value))
            values[parameter.name] = value
        await self.callback(interaction, **values)


def command(*, name: str | None = None, description: str | None = None):
    def decorator(callback):
        return Command(callback, name=name, description=description)
    return decorator


class CommandTree:
    def __init__(self, client) -> None:
        self.client = client
        self._commands: dict[str, Command] = {}
        self._error_handler = None

    def command(self, *, name: str | None = None, description: str | None = None):
        def decorator(callback):
            item = Command(callback, name=name, description=description)
            self.add_command(item)
            return item
        return decorator

    def add_command(self, command: Command, *, override: bool = False) -> None:
        if command.name in self._commands and not override:
            raise ValueError(f"Command {command.name} is already registered")
        command.definition()
        if len(self._commands) >= 25 and command.name not in self._commands:
            raise ValueError("PollákCord supports at most 25 slash commands per bot")
        self._commands[command.name] = command

    def get_command(self, name: str) -> Command | None:
        return self._commands.get(name)

    def get_commands(self) -> list[Command]:
        return list(self._commands.values())

    def remove_command(self, name: str) -> Command | None:
        return self._commands.pop(name, None)

    def clear_commands(self, *, guild=None) -> None:
        if guild is not None:
            raise UnsupportedFeature("Per-server command registration is not implemented")
        self._commands.clear()

    async def sync(self, *, guild=None) -> list:
        if guild is not None:
            raise UnsupportedFeature("Commands are available in all installed servers; per-server registration is not implemented")
        rows = await self.client._transport.register_commands([item.definition() for item in self._commands.values()])
        return [SimpleNamespace(**{**row, "id": int(row["id"])}) for row in rows]

    def error(self, callback):
        self._error_handler = callback
        return callback

    async def _invoke(self, interaction) -> None:
        item = self.get_command(interaction.name)
        if item is None:
            return
        try:
            await item.invoke(interaction)
        except Exception as error:
            if self._error_handler:
                await self._error_handler(interaction, error)
            else:
                await self.client._emit("app_command_error", interaction, error)


class checks:
    @staticmethod
    def has_permissions(**permissions: bool):
        Permissions(**permissions)
        def predicate(interaction):
            return all(getattr(interaction.permissions, name) == enabled for name, enabled in permissions.items())
        return check(predicate)
