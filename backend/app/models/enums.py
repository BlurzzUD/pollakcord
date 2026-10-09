from enum import StrEnum


class AccountStatus(StrEnum):
    PENDING_SECURITY = "pending_security"
    ACTIVE = "active"
    SUSPENDED = "suspended"


class PlatformRole(StrEnum):
    USER = "user"
    SCHOOL_MODERATOR = "school_moderator"
    SCHOOL_ADMIN = "school_admin"
    DOK_REPRESENTATIVE = "dok_representative"
    DOK_PRESIDENT = "dok_president"


STAFF_ROLES = frozenset({PlatformRole.SCHOOL_MODERATOR.value, PlatformRole.SCHOOL_ADMIN.value})


class AuthMethodKind(StrEnum):
    PASSWORD = "password"
    TOTP = "totp"


class SessionScope(StrEnum):
    FULL = "full"
    SETUP = "setup"


class ClassVisibility(StrEnum):
    HIDDEN = "hidden"
    FRIENDS = "friends"
    SHARED_SERVERS = "shared_servers"
    EVERYONE = "everyone"


class ProfileVisibility(StrEnum):
    EVERYONE = "everyone"
    SHARED_CONTEXT = "shared_context"
    FRIENDS = "friends"


class PresenceVisibility(StrEnum):
    NOBODY = "nobody"
    FRIENDS = "friends"
    SHARED_SERVERS = "shared_servers"


class FriendRequestPolicy(StrEnum):
    EVERYONE = "everyone"
    SHARED_SERVERS = "shared_servers"
    NOBODY = "nobody"


class DirectMessagePolicy(StrEnum):
    EVERYONE = "everyone"
    SHARED_SERVERS = "shared_servers"
    FRIENDS = "friends"


class ActivityVisibility(StrEnum):
    NOBODY = "nobody"
    FRIENDS = "friends"


class CallPolicy(StrEnum):
    FRIENDS = "friends"
    NOBODY = "nobody"


class ThemeMode(StrEnum):
    SYSTEM = "system"
    DARK = "dark"
    LIGHT = "light"
    CUSTOM = "custom"


class ChannelType(StrEnum):
    TEXT = "text"
    VOICE = "voice"


class OverwriteScope(StrEnum):
    CATEGORY = "category"
    CHANNEL = "channel"


class OverwriteTarget(StrEnum):
    ROLE = "role"
    MEMBER = "member"


class ScopeKind(StrEnum):
    DM = "dm"
    CHANNEL = "channel"


class DokScope(StrEnum):
    CLASS = "class"
    SCHOOL = "school"


class RoleKind(StrEnum):
    MEMBER = "member"
    MODERATOR = "moderator"
    ADMINISTRATOR = "administrator"
    CUSTOM = "custom"


class ReportStatus(StrEnum):
    OPEN = "open"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


class NotificationType(StrEnum):
    FRIEND_REQUEST = "friend_request"
    FRIEND_ACCEPTED = "friend_accepted"
    DM = "dm"
    MENTION = "mention"
    SERVER = "server"
    CALL_INCOMING = "call_incoming"
    CALL_MISSED = "call_missed"
    MODERATION = "moderation"
    DOK_MESSAGE = "dok_message"


class AuditAction(StrEnum):
    MEMBER_KICK = "member.kick"
    MEMBER_BAN = "member.ban"
    MEMBER_UNBAN = "member.unban"
    MEMBER_TIMEOUT = "member.timeout"
    MEMBER_UPDATE = "member.update"
    MEMBER_ROLES = "member.roles"
    ROLE_CREATE = "role.create"
    ROLE_UPDATE = "role.update"
    ROLE_DELETE = "role.delete"
    CHANNEL_CREATE = "channel.create"
    CHANNEL_UPDATE = "channel.update"
    CHANNEL_DELETE = "channel.delete"
    CHANNEL_PERMISSIONS = "channel.permissions"
    CATEGORY_CREATE = "category.create"
    CATEGORY_UPDATE = "category.update"
    CATEGORY_DELETE = "category.delete"
    SERVER_UPDATE = "server.update"
    MESSAGE_DELETE = "message.delete"
    MESSAGE_PIN = "message.pin"
    MESSAGE_UNPIN = "message.unpin"
    INVITE_CREATE = "invite.create"
    INVITE_REVOKE = "invite.revoke"
    VOICE_MODERATE = "voice.moderate"
    REPORT_RESOLVE = "report.resolve"
    PLATFORM_IDENTITY_REVEAL = "platform.identity_reveal"
    PLATFORM_MESSAGE_VIEW = "platform.message_view"
    PLATFORM_USER_STATUS = "platform.user_status"
    PLATFORM_REPORT_VIEW = "platform.report_view"
    ACCOUNT_RECOVERY = "account.recovery"
    DOK_MESSAGE_SEND = "dok.message_send"
