from __future__ import annotations

import asyncio
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from .client import Bot, UnsupportedFeature

PERMISSION_NAMES = (
    "view_channel", "send_messages", "read_message_history", "add_reactions", "connect", "speak", "mute_members", "deafen_members",
    "create_invite", "kick_members", "ban_members", "manage_messages", "manage_channels", "manage_roles", "manage_members", "manage_server", "view_audit_log", "administrator",
)
PERMISSION_ALIASES = {"read_messages": "view_channel", "manage_guild": "manage_server", "moderate_members": "manage_members", "create_instant_invite": "create_invite"}


def snowflake(value) -> int:
    return int(Bot._id(getattr(value, "id", value)))


def timestamp(value) -> datetime | None:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


class Object:
    def __init__(self, id: int | str) -> None:
        self.id = snowflake(id)

    def __eq__(self, other) -> bool:
        return isinstance(other, Object) and self.id == other.id

    def __hash__(self) -> int:
        return hash(self.id)

    def __repr__(self) -> str:
        return f"<{type(self).__name__} id={self.id}>"


class Permissions:
    def __init__(self, permissions: int = 0, **flags: bool) -> None:
        if type(permissions) is not int or permissions < 0 or permissions >= 1 << len(PERMISSION_NAMES):
            raise ValueError("Invalid PollákCord permission bitset")
        self.value = permissions
        self.update(**flags)

    def update(self, **flags: bool) -> None:
        for name, value in flags.items():
            key = PERMISSION_ALIASES.get(name, name)
            if key not in PERMISSION_NAMES:
                raise UnsupportedFeature(f"Permission {name} is not supported by PollákCord")
            if type(value) is not bool:
                raise TypeError("Permission flags must be booleans")
            bit = 1 << PERMISSION_NAMES.index(key)
            self.value = self.value | bit if value else self.value & ~bit

    def __getattr__(self, name: str) -> bool:
        key = PERMISSION_ALIASES.get(name, name)
        if key not in PERMISSION_NAMES:
            raise AttributeError(name)
        return bool(self.value & (1 << PERMISSION_NAMES.index(key)))

    def __iter__(self):
        return iter((name, bool(self.value & (1 << index))) for index, name in enumerate(PERMISSION_NAMES))

    def names(self) -> list[str]:
        return [name for name, enabled in self if enabled]

    @classmethod
    def none(cls) -> Permissions:
        return cls()

    @classmethod
    def all(cls) -> Permissions:
        return cls((1 << len(PERMISSION_NAMES)) - 1)


class Intents:
    _names = frozenset({"guilds", "members", "messages", "message_content", "reactions"})

    def __init__(self, **flags: bool) -> None:
        for name in self._names:
            setattr(self, name, False)
        for name, value in flags.items():
            setattr(self, name, value)

    def __setattr__(self, name: str, value: bool) -> None:
        key = {"guild_messages": "messages", "guild_reactions": "reactions"}.get(name, name)
        if key not in self._names:
            raise UnsupportedFeature(f"Intent {name} is not supported by PollákCord")
        if type(value) is not bool:
            raise TypeError("Intent flags must be booleans")
        object.__setattr__(self, key, value)

    @property
    def guild_messages(self) -> bool:
        return self.messages

    @property
    def guild_reactions(self) -> bool:
        return self.reactions

    @classmethod
    def default(cls) -> Intents:
        return cls(guilds=True, messages=True, reactions=True, message_content=True)

    @classmethod
    def all(cls) -> Intents:
        return cls(**dict.fromkeys(cls._names, True))

    @classmethod
    def none(cls) -> Intents:
        return cls()


class Asset:
    def __init__(self, url: str) -> None:
        self.url = url

    def __str__(self) -> str:
        return self.url


class User(Object):
    def __init__(self, client, data: dict) -> None:
        super().__init__(data["id"])
        self._client = client
        self.name = data.get("username", "")
        self.global_name = data.get("display_name")
        self.bot = bool(data.get("is_bot", False))
        avatar = data.get("avatar_url")
        self.avatar = Asset(client.origin + avatar if avatar and avatar.startswith("/") else avatar) if avatar else None

    @property
    def display_name(self) -> str:
        return self.global_name or self.name

    @property
    def mention(self) -> str:
        return f"<@{self.id}>"

    def __str__(self) -> str:
        return self.name

    async def send(self, content: str):
        raise UnsupportedFeature("Bots cannot use direct messages on PollákCord")


class Role(Object):
    def __init__(self, guild: Guild, data: dict) -> None:
        super().__init__(data["id"])
        self.guild = guild
        self.name = data["name"]
        self.position = data["position"]
        self.permissions = Permissions(data.get("permissions", 0))
        self.managed = data.get("kind") == "bot"
        self._default = data.get("is_default", False)
        self.color = data.get("color")

    def __str__(self) -> str:
        return self.name

    @property
    def mention(self) -> str:
        return f"<@&{self.id}>"

    def is_default(self) -> bool:
        return self._default

    def __lt__(self, other: Role) -> bool:
        if self.guild.id != other.guild.id:
            raise ValueError("Cannot compare roles from different servers")
        return (self.position, -self.id) < (other.position, -other.id)

    async def edit(self, *, name: str | None = None, permissions: Permissions | None = None, position: int | None = None, color: str | None = None) -> Role:
        body = {key: value for key, value in {"name": name, "position": position, "color": color}.items() if value is not None}
        if permissions is not None:
            body["permissions"] = permissions.names()
        data = await self.guild._client._request("PATCH", f"servers/{self.guild.id}/roles/{self.id}", body)
        return self.guild._store_role(data)

    async def delete(self) -> None:
        await self.guild._client._request("DELETE", f"servers/{self.guild.id}/roles/{self.id}")
        self.guild._roles.pop(self.id, None)


class Member(User):
    def __init__(self, guild: Guild, data: dict) -> None:
        super().__init__(guild._client, data.get("user", data))
        self.guild = guild
        self.nick = data.get("nickname")
        self.joined_at = timestamp(data.get("joined_at"))
        self.timed_out_until = timestamp(data.get("timeout_until"))
        self._role_ids = {snowflake(value) for value in data.get("role_ids", [])}

    @property
    def display_name(self) -> str:
        return self.nick or super().display_name

    @property
    def roles(self) -> list[Role]:
        return sorted((role for role in self.guild.roles if role.id in self._role_ids or role.is_default()), key=lambda role: (role.position, role.id))

    @property
    def top_role(self) -> Role | None:
        return max(self.roles, default=None)

    @property
    def guild_permissions(self) -> Permissions:
        if self.guild._client.user and self.id == self.guild._client.user.id:
            return Permissions(self.guild._my_permissions)
        if self.id == self.guild.owner_id:
            return Permissions.all()
        bits = 0
        for role in self.roles:
            bits |= role.permissions.value
        return Permissions.all() if Permissions(bits).administrator else Permissions(bits)

    async def kick(self) -> None:
        await self.guild.kick(self)

    async def ban(self, *, reason: str | None = None) -> None:
        await self.guild.ban(self, reason=reason)

    async def timeout(self, until: datetime | timedelta | None) -> None:
        if isinstance(until, datetime):
            if until.tzinfo is None:
                raise ValueError("Timeout datetimes must include a timezone")
            seconds = (until - datetime.now(timezone.utc)).total_seconds()
        else:
            seconds = until.total_seconds() if until is not None else 0
        if not math.isfinite(seconds) or seconds > 28 * 86400:
            raise ValueError("Timeouts are limited to 28 days")
        await self.guild._client._request("PATCH", f"servers/{self.guild.id}/members/{self.id}", {"timeout_minutes": max(0, math.ceil(seconds / 60))})

    async def edit(self, *, nick: str | None) -> Member:
        await self.guild._client._request("PATCH", f"servers/{self.guild.id}/members/{self.id}", {"nickname": nick})
        return await self.guild.fetch_member(self.id)

    async def add_roles(self, *roles: Role) -> None:
        for role in roles:
            if role.guild.id != self.guild.id:
                raise ValueError("Role belongs to another server")
            await self.guild._client._request("PUT", f"servers/{self.guild.id}/members/{self.id}/roles/{role.id}")
        self._role_ids = (await self.guild.fetch_member(self.id))._role_ids

    async def remove_roles(self, *roles: Role) -> None:
        for role in roles:
            if role.guild.id != self.guild.id:
                raise ValueError("Role belongs to another server")
            await self.guild._client._request("DELETE", f"servers/{self.guild.id}/members/{self.id}/roles/{role.id}")
        self._role_ids = (await self.guild.fetch_member(self.id))._role_ids


class Guild(Object):
    def __init__(self, client, data: dict) -> None:
        super().__init__(data["id"])
        self._client = client
        self._members: dict[int, Member] = {}
        self._channels: dict[int, TextChannel] = {}
        self._roles: dict[int, Role] = {}
        self._update(data)

    def _update(self, data: dict) -> None:
        self.name = data.get("name", getattr(self, "name", ""))
        self.description = data.get("description", getattr(self, "description", ""))
        self.owner_id = snowflake(data["owner_id"]) if data.get("owner_id") else getattr(self, "owner_id", None)
        self._my_permissions = data.get("my_permissions", getattr(self, "_my_permissions", 0))
        self._my_role_ids = data.get("my_role_ids", getattr(self, "_my_role_ids", []))
        if "roles" in data:
            self._roles = {snowflake(row["id"]): Role(self, row) for row in data["roles"]}
        if "channels" in data:
            self._channels = {snowflake(row["id"]): TextChannel(self._client, row, guild=self) for row in data["channels"]}

    def __str__(self) -> str:
        return self.name

    @property
    def channels(self) -> list[TextChannel]:
        return sorted(self._channels.values(), key=lambda channel: (channel.position, channel.id))

    @property
    def text_channels(self) -> list[TextChannel]:
        return self.channels

    @property
    def roles(self) -> list[Role]:
        return sorted(self._roles.values(), key=lambda role: (role.position, role.id))

    @property
    def members(self) -> list[Member]:
        return list(self._members.values())

    @property
    def default_role(self) -> Role | None:
        return next((role for role in self.roles if role.is_default()), None)

    @property
    def me(self) -> Member | None:
        user = self._client.user
        if user is None:
            return None
        return Member(self, {"user": {"id": str(user.id), "username": user.name, "display_name": user.global_name, "is_bot": True}, "role_ids": self._my_role_ids})

    def get_member(self, user_id: int) -> Member | None:
        return self._members.get(snowflake(user_id))

    def get_channel(self, channel_id: int) -> TextChannel | None:
        return self._channels.get(snowflake(channel_id))

    def get_role(self, role_id: int) -> Role | None:
        return self._roles.get(snowflake(role_id))

    def _store_member(self, data: dict) -> Member:
        member = Member(self, data)
        self._members[member.id] = member
        return member

    def _store_role(self, data: dict) -> Role:
        role = Role(self, data)
        self._roles[role.id] = role
        return role

    async def fetch_member(self, user_id: int) -> Member:
        return self._store_member(await self._client._request("GET", f"servers/{self.id}/members/{snowflake(user_id)}"))

    async def fetch_members(self, *, limit: int | None = 1000, after=None):
        remaining = limit
        cursor = snowflake(after) if after is not None else None
        if remaining is not None and remaining < 0:
            raise ValueError("limit must be nonnegative or None")
        while remaining is None or remaining > 0:
            params = {"limit": min(100, remaining) if remaining is not None else 100}
            if cursor is not None:
                params["after"] = cursor
            page = await self._client._request("GET", f"servers/{self.id}/members", params=params)
            rows = page["members"]
            for row in rows:
                member = self._store_member(row)
                yield member
                if remaining is not None:
                    remaining -= 1
            if not page.get("has_more") or not rows:
                break
            cursor = snowflake(rows[-1]["user"]["id"])

    async def fetch_channels(self) -> list[TextChannel]:
        rows = await self._client._request("GET", f"servers/{self.id}/channels")
        self._channels = {snowflake(row["id"]): TextChannel(self._client, row, guild=self) for row in rows}
        return self.channels

    async def fetch_roles(self) -> list[Role]:
        rows = await self._client._request("GET", f"servers/{self.id}/roles")
        self._roles = {snowflake(row["id"]): Role(self, row) for row in rows}
        return self.roles

    async def kick(self, user: Object) -> None:
        await self._client._request("DELETE", f"servers/{self.id}/members/{snowflake(user)}")
        self._members.pop(snowflake(user), None)

    async def ban(self, user: Object, *, reason: str | None = None) -> None:
        await self._client._request("PUT", f"servers/{self.id}/bans/{snowflake(user)}", {"reason": reason or ""})
        self._members.pop(snowflake(user), None)

    async def unban(self, user: Object) -> None:
        await self._client._request("DELETE", f"servers/{self.id}/bans/{snowflake(user)}")

    async def create_role(self, *, name: str, permissions: Permissions | None = None, color: str | None = None, position: int | None = None) -> Role:
        body = {"name": name, "permissions": (permissions or Permissions.none()).names(), "color": color, "position": position}
        return self._store_role(await self._client._request("POST", f"servers/{self.id}/roles", body))

    async def create_text_channel(self, name: str, *, topic: str = "", slowmode_delay: int = 0, position: int | None = None) -> TextChannel:
        data = await self._client._request("POST", f"servers/{self.id}/channels", {"name": name, "topic": topic, "slowmode_seconds": slowmode_delay, "position": position})
        channel = TextChannel(self._client, data, guild=self)
        self._channels[channel.id] = channel
        return channel

    async def invites(self) -> list[Invite]:
        return [Invite(self, row) for row in await self._client._request("GET", f"servers/{self.id}/invites")]

    async def edit(self, *, name: str | None = None, description: str | None = None) -> Guild:
        body = {key: value for key, value in {"name": name, "description": description}.items() if value is not None}
        self._update(await self._client._request("PATCH", f"servers/{self.id}", body))
        return self

    async def bans(self, *, limit: int = 200):
        if not 0 <= limit <= 200:
            raise ValueError("PollákCord lists at most 200 bans per request")
        rows = await self._client._request("GET", f"servers/{self.id}/bans")
        for row in rows[:limit]:
            yield BanEntry(User(self._client, row["user"]), row["reason"])

    async def audit_logs(self, *, limit: int | None = 100, before=None):
        remaining = limit
        if remaining is not None and remaining < 0:
            raise ValueError("limit must be nonnegative or None")
        cursor = snowflake(before) if before is not None else None
        while remaining is None or remaining > 0:
            params = {"limit": min(100, remaining) if remaining is not None else 100}
            if cursor is not None:
                params["before"] = cursor
            page = await self._client._request("GET", f"servers/{self.id}/audit-logs", params=params)
            for row in page["entries"]:
                yield AuditLogEntry(self, row)
                if remaining is not None:
                    remaining -= 1
            if not page.get("has_more") or not page["entries"]:
                break
            cursor = snowflake(page["entries"][-1]["id"])


@dataclass
class BanEntry:
    user: User
    reason: str


class AuditLogEntry(Object):
    def __init__(self, guild: Guild, data: dict) -> None:
        super().__init__(data["id"])
        self.guild = guild
        self.action = data["action"]
        self.user_id = snowflake(data["actor_id"]) if data.get("actor_id") else None
        self.target = Object(data["target_id"]) if data.get("target_id") else None
        self.created_at = timestamp(data.get("created_at"))


class TextChannel(Object):
    def __init__(self, client, data: dict, *, guild: Guild | None = None) -> None:
        super().__init__(data["id"])
        self._client = client
        self.guild = guild or (client.get_guild(snowflake(data["server_id"])) if data.get("server_id") else None)
        self.name = data.get("name", "")
        self.topic = data.get("topic", "")
        self.position = data.get("position", 0)
        self.slowmode_delay = data.get("slowmode_seconds", 0)
        self._permissions = data.get("my_permissions")

    def __str__(self) -> str:
        return self.name

    @property
    def mention(self) -> str:
        return f"<#{self.id}>"

    def permissions_for(self, member: Member) -> Permissions:
        if self._permissions is None or self._client.user is None or member.id != self._client.user.id:
            raise UnsupportedFeature("Only the bot's effective channel permissions are exposed; fetch_channel refreshes them")
        return Permissions(self._permissions)

    async def send(self, content, *, reference=None, delete_after: float | None = None) -> Message:
        if reference is not None and reference.channel.id != self.id:
            raise ValueError("Reply reference belongs to another channel")
        data = await self._client._transport.send_message(str(self.id), str(content), reply_to_id=str(reference.id) if reference else None)
        message = Message(self._client, data, channel=self)
        self._client._cache_message(message)
        if delete_after is not None:
            self._client._schedule(message.delete(delay=delete_after))
        return message

    async def fetch_message(self, message_id: int) -> Message:
        data = await self._client._request("GET", f"channels/{self.id}/messages/{snowflake(message_id)}")
        message = Message(self._client, data, channel=self)
        self._client._cache_message(message)
        return message

    def get_partial_message(self, message_id: int) -> Message:
        return Message(self._client, {"id": str(snowflake(message_id)), "channel_id": str(self.id)}, channel=self)

    async def history(self, *, limit: int | None = 100, before=None, after=None, oldest_first: bool | None = None):
        if before is not None and after is not None:
            raise UnsupportedFeature("Use either before or after for PollákCord history")
        forward = after is not None
        if oldest_first is not None and oldest_first != forward:
            raise UnsupportedFeature("Use oldest_first=False with before or oldest_first=True with after")
        remaining = limit
        if remaining is not None and remaining < 0:
            raise ValueError("limit must be nonnegative or None")
        cursor = snowflake(after if forward else before) if after is not None or before is not None else None
        while remaining is None or remaining > 0:
            params = {"limit": min(100, remaining) if remaining is not None else 100}
            if cursor is not None:
                params["after" if forward else "before"] = cursor
            page = await self._client._request("GET", f"channels/{self.id}/messages", params=params)
            rows = page["messages"]
            ordered = rows if forward else list(reversed(rows))
            for row in ordered:
                message = Message(self._client, row, channel=self)
                yield message
                if remaining is not None:
                    remaining -= 1
            if not page.get("has_more") or not rows:
                break
            cursor = snowflake(rows[-1 if forward else 0]["id"])

    async def pins(self) -> list[Message]:
        return [Message(self._client, data, channel=self) for data in await self._client._request("GET", f"channels/{self.id}/pins")]

    async def edit(self, *, name: str | None = None, topic: str | None = None, slowmode_delay: int | None = None, position: int | None = None) -> TextChannel:
        body = {key: value for key, value in {"name": name, "topic": topic, "slowmode_seconds": slowmode_delay, "position": position}.items() if value is not None}
        data = await self._client._request("PATCH", f"channels/{self.id}", body)
        channel = TextChannel(self._client, data, guild=self.guild)
        if self.guild:
            self.guild._channels[self.id] = channel
        return channel

    async def delete(self) -> None:
        await self._client._request("DELETE", f"channels/{self.id}")
        if self.guild:
            self.guild._channels.pop(self.id, None)

    async def create_invite(self, *, max_age: int = 0, max_uses: int = 0) -> Invite:
        if not self.guild:
            raise ValueError("The channel has no cached server")
        if max_age < 0 or max_uses < 0:
            raise ValueError("Invite limits cannot be negative")
        data = await self._client._request("POST", f"servers/{self.guild.id}/invites", {"max_uses": max_uses or None, "expires_in_hours": math.ceil(max_age / 3600) if max_age else None})
        return Invite(self.guild, data)


class Reaction:
    def __init__(self, message: Message, data: dict) -> None:
        self.message = message
        self.emoji = data["emoji"]
        self.count = data.get("count", 0)
        self.me = data.get("me", False)

    def __str__(self) -> str:
        return self.emoji


class Message(Object):
    def __init__(self, client, data: dict, *, channel: TextChannel | None = None) -> None:
        super().__init__(data["id"])
        self._client = client
        self.channel = channel or client.get_channel(snowflake(data["channel_id"]))
        if self.channel is None:
            self.channel = TextChannel(client, {"id": data["channel_id"], "server_id": data.get("server_id")})
        self.guild = self.channel.guild
        author = data.get("author")
        if author and self.guild:
            cached = self.guild.get_member(snowflake(author["id"]))
            self.author = cached or Member(self.guild, {"user": author, "nickname": author.get("nickname")})
        else:
            self.author = User(client, author) if author else None
        self.content = data.get("content") or ""
        self.created_at = timestamp(data.get("created_at"))
        self.edited_at = timestamp(data.get("edited_at"))
        self.pinned = bool(data.get("pinned", False))
        self.deleted = bool(data.get("deleted", False))
        self.attachments = data.get("attachments", [])
        self.embeds = data.get("embeds", [])
        self.reactions = [Reaction(self, row) for row in data.get("reactions", [])]

    async def delete(self, *, delay: float = 0) -> None:
        if not math.isfinite(delay) or delay < 0:
            raise ValueError("delay must be a nonnegative finite number")
        if delay:
            await asyncio.sleep(delay)
        await self._client._transport.delete_message(str(self.channel.id), str(self.id))
        self.deleted = True

    async def edit(self, *, content: str) -> Message:
        data = await self._client._request("PATCH", f"channels/{self.channel.id}/messages/{self.id}", {"content": str(content)})
        message = Message(self._client, data, channel=self.channel)
        self._client._cache_message(message)
        return message

    async def reply(self, content, *, delete_after: float | None = None) -> Message:
        return await self.channel.send(content, reference=self, delete_after=delete_after)

    async def add_reaction(self, emoji) -> None:
        await self._client._request("PUT", f"channels/{self.channel.id}/messages/{self.id}/reactions", {"emoji": str(emoji)})

    async def remove_reaction(self, emoji, member: Object) -> None:
        if not self._client.user or snowflake(member) != self._client.user.id:
            raise UnsupportedFeature("Bots can remove only their own reactions")
        await self._client._request("DELETE", f"channels/{self.channel.id}/messages/{self.id}/reactions", {"emoji": str(emoji)})

    async def pin(self) -> None:
        await self._client._request("PUT", f"channels/{self.channel.id}/pins/{self.id}")
        self.pinned = True

    async def unpin(self) -> None:
        await self._client._request("DELETE", f"channels/{self.channel.id}/pins/{self.id}")
        self.pinned = False


class Invite:
    def __init__(self, guild: Guild, data: dict) -> None:
        self.guild = guild
        self.code = data["code"]
        self.uses = data.get("uses", 0)
        self.max_uses = data.get("max_uses") or 0
        self.expires_at = timestamp(data.get("expires_at"))

    @property
    def url(self) -> str:
        return f"{self.guild._client.origin}/invite/{self.code}"

    def __str__(self) -> str:
        return self.url

    async def delete(self) -> None:
        await self.guild._client._request("DELETE", f"servers/{self.guild.id}/invites/{self.code}")


class InteractionResponse:
    def __init__(self, interaction: Interaction) -> None:
        self._interaction = interaction
        self._done = False
        self._lock = asyncio.Lock()

    def is_done(self) -> bool:
        return self._done

    async def send_message(self, content, *, ephemeral: bool = False) -> Message:
        if ephemeral:
            raise UnsupportedFeature("Ephemeral replies are not implemented on PollákCord")
        async with self._lock:
            if self._done:
                raise RuntimeError("This interaction has already been answered")
            interaction = self._interaction
            data = await interaction.client._transport.respond(str(interaction.id), str(content))
            self._done = True
            message = Message(interaction.client, data, channel=interaction.channel)
            interaction._original = message
            return message

    async def defer(self, *, ephemeral: bool = False, thinking: bool = False) -> None:
        raise UnsupportedFeature("Deferred replies are not implemented; respond within three seconds")


class Interaction(Object):
    def __init__(self, client, data: dict) -> None:
        super().__init__(data["id"])
        self.client = client
        self.name = data["name"]
        self.options = data.get("options", {})
        self.guild_id = snowflake(data["server_id"])
        self.guild = client.get_guild(self.guild_id)
        self.channel_id = snowflake(data["channel_id"])
        self.channel = client.get_channel(self.channel_id)
        self.user = self.guild._store_member(data.get("member") or {"user": data["user"]}) if self.guild else User(client, data["user"])
        self.expires_at = timestamp(data.get("expires_at"))
        self.response = InteractionResponse(self)
        self.permissions = Permissions(data.get("permissions", 0))
        self._original: Message | None = None

    @classmethod
    def __class_getitem__(cls, _item):
        return cls

    async def respond(self, content: str) -> Message:
        return await self.response.send_message(content)

    async def original_response(self) -> Message:
        if self._original is None:
            raise RuntimeError("This interaction has not been answered")
        return self._original

    async def edit_original_response(self, *, content: str) -> Message:
        self._original = await (await self.original_response()).edit(content=content)
        return self._original

    async def delete_original_response(self) -> None:
        await (await self.original_response()).delete()
