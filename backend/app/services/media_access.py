from sqlalchemy.ext.asyncio import AsyncSession

from ..db.types import utcnow
from ..errors import AppError
from ..models import Conversation, User
from ..models.enums import ChannelType
from . import privacy
from .permissions import Perm, load_channel_context


async def require_media_scope(db: AsyncSession, user: User, scope: str, scope_id: int, *, write: bool) -> None:
    if not 0 < scope_id < 2**63:
        raise AppError("not_found", 404)
    if scope == "channel":
        channel, context = await load_channel_context(db, scope_id, user.id)
        if channel.type != ChannelType.TEXT.value:
            raise AppError("channel_type_invalid", 422)
        if write and context.member.timeout_until is not None and context.member.timeout_until > utcnow():
            raise AppError("timed_out", 403)
        context.require_in(channel, Perm.SEND_MESSAGES if write else Perm.READ_MESSAGE_HISTORY)
        return
    if scope != "dm":
        raise AppError("not_found", 404)
    conversation = await db.get(Conversation, scope_id)
    if conversation is None or user.id not in (conversation.user_low_id, conversation.user_high_id):
        raise AppError("not_found", 404)
    if write:
        other_id = conversation.user_high_id if user.id == conversation.user_low_id else conversation.user_low_id
        relation = await privacy.relation(db, user.id, other_id)
        preferences = await privacy.get_settings_row(db, other_id)
        if not privacy.can_direct_message(relation, preferences):
            raise AppError("dm_not_allowed", 403)
