from dataclasses import dataclass, field
from typing import Any

from ..errors import AppError


@dataclass
class Participant:
    user_id: int
    muted: bool = False
    deafened: bool = False
    server_muted: bool = False
    server_deafened: bool = False


@dataclass
class Room:
    key: str
    server_id: int | None
    channel_id: int | None
    limit: int
    participants: dict[int, Participant] = field(default_factory=dict)

    def snapshot(self) -> list[dict[str, Any]]:
        return [
            {
                "user_id": str(p.user_id),
                "muted": p.muted,
                "deafened": p.deafened,
                "server_muted": p.server_muted,
                "server_deafened": p.server_deafened,
            }
            for p in self.participants.values()
        ]


class VoiceManager:
    def __init__(self, max_participants: int) -> None:
        self._max = max_participants
        self._rooms: dict[str, Room] = {}
        self._user_room: dict[int, str] = {}

    def room_of(self, user_id: int) -> Room | None:
        key = self._user_room.get(user_id)
        return self._rooms.get(key) if key else None

    def room(self, key: str) -> Room | None:
        return self._rooms.get(key)

    def join(self, user_id: int, key: str, *, server_id: int | None, channel_id: int | None, limit: int) -> Room:
        room = self._rooms.get(key)
        cap = min(limit, self._max) if limit > 0 else self._max
        if room is None:
            room = Room(key=key, server_id=server_id, channel_id=channel_id, limit=cap)
            self._rooms[key] = room
        if user_id not in room.participants and len(room.participants) >= cap:
            raise AppError("voice_channel_full", 409)
        room.participants[user_id] = Participant(user_id)
        self._user_room[user_id] = key
        return room

    def leave(self, user_id: int) -> Room | None:
        key = self._user_room.pop(user_id, None)
        room = self._rooms.get(key) if key else None
        if room is None:
            return None
        room.participants.pop(user_id, None)
        if not room.participants:
            del self._rooms[key]
        return room

    def can_relay(self, sender_id: int, recipient_id: int) -> bool:
        room = self.room_of(sender_id)
        return room is not None and recipient_id in room.participants and sender_id != recipient_id

    def update_state(self, user_id: int, *, muted: bool, deafened: bool) -> Room | None:
        room = self.room_of(user_id)
        if room is None:
            return None
        participant = room.participants[user_id]
        participant.muted = muted
        participant.deafened = deafened
        return room

    def moderate(self, room_key: str, target_id: int, *, server_muted: bool | None, server_deafened: bool | None) -> Room | None:
        room = self._rooms.get(room_key)
        if room is None or target_id not in room.participants:
            return None
        participant = room.participants[target_id]
        if server_muted is not None:
            participant.server_muted = server_muted
        if server_deafened is not None:
            participant.server_deafened = server_deafened
        return room

    def channel_states(self, channel_ids: list[int]) -> dict[str, list[dict[str, Any]]]:
        states: dict[str, list[dict[str, Any]]] = {}
        for channel_id in channel_ids:
            room = self._rooms.get(f"channel:{channel_id}")
            if room is not None:
                states[str(channel_id)] = room.snapshot()
        return states
