from datetime import datetime
from typing import Any

from ..models import Channel, Category, Profile, Role, Server, User, UserSettings
from .permissions import bits_to_names


def sid(value: int | None) -> str | None:
    return None if value is None else str(value)


def iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def media_url(kind: str, key: str | None) -> str | None:
    return f"/media/{kind}/{key}" if key else None


def user_card(user: User, profile: Profile | None) -> dict[str, Any]:
    return {
        "id": sid(user.id),
        "username": user.username,
        "display_name": user.display_name,
        "avatar_url": media_url("avatar", profile.avatar_key if profile else None),
        "staff": user.platform_role != "user",
    }


def user_profile(
    user: User,
    profile: Profile | None,
    *,
    class_code: str | None,
    presence: str | None,
    last_seen: datetime | None,
    mutual_friends: int | None,
    relation: dict[str, bool] | None,
) -> dict[str, Any]:
    card = user_card(user, profile)
    card.update(
        {
            "bio": profile.bio if profile else "",
            "banner_url": media_url("banner", profile.banner_key if profile else None),
            "accent_color": profile.accent_color if profile else None,
            "created_at": iso(user.created_at),
            "class_code": class_code,
            "presence": presence,
            "last_seen_at": iso(last_seen),
            "mutual_friends": mutual_friends,
            "relation": relation,
        }
    )
    return card


def settings_dict(row: UserSettings) -> dict[str, Any]:
    return {
        "language": row.language,
        "theme_mode": row.theme_mode,
        "active_theme_id": sid(row.active_theme_id),
        "custom_css": row.custom_css,
        "developer_mode": row.developer_mode,
        "chat_appearance": row.chat_appearance,
        "notification_prefs": row.notification_prefs,
        "privacy": {
            "friend_requests": row.friend_requests,
            "direct_messages": row.direct_messages,
            "class_visibility": row.class_visibility,
            "online_status": row.online_status,
            "profile_visibility": row.profile_visibility,
            "activity_visibility": row.activity_visibility,
            "voice_calls": row.voice_calls,
        },
        "class_prompt_answered": row.class_prompt_answered,
    }


def self_user(user: User, profile: Profile | None, settings_row: UserSettings, class_code: str | None) -> dict[str, Any]:
    card = user_card(user, profile)
    card.update(
        {
            "bio": profile.bio if profile else "",
            "banner_url": media_url("banner", profile.banner_key if profile else None),
            "accent_color": profile.accent_color if profile else None,
            "created_at": iso(user.created_at),
            "status": user.status,
            "platform_role": user.platform_role,
            "class_code": class_code,
            "settings": settings_dict(settings_row),
        }
    )
    return card


def server_summary(server: Server, member_count: int | None = None) -> dict[str, Any]:
    return {
        "id": sid(server.id),
        "name": server.name,
        "description": server.description,
        "icon_url": media_url("server_icon", server.icon_key),
        "owner_id": sid(server.owner_id),
        "member_count": member_count,
        "created_at": iso(server.created_at),
    }


def role_dict(role: Role) -> dict[str, Any]:
    return {
        "id": sid(role.id),
        "name": role.name,
        "color": role.color,
        "position": role.position,
        "permissions": role.permissions,
        "permission_names": bits_to_names(role.permissions),
        "is_default": role.is_default,
        "kind": role.kind,
    }


def category_dict(category: Category) -> dict[str, Any]:
    return {"id": sid(category.id), "name": category.name, "position": category.position}


def channel_dict(channel: Channel) -> dict[str, Any]:
    return {
        "id": sid(channel.id),
        "server_id": sid(channel.server_id),
        "category_id": sid(channel.category_id),
        "type": channel.type,
        "name": channel.name,
        "topic": channel.topic,
        "position": channel.position,
        "user_limit": channel.user_limit,
        "slowmode_seconds": channel.slowmode_seconds,
    }
