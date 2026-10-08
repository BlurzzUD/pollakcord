export const PERMISSION_BITS: Record<string, number> = {
  view_channel: 1 << 0,
  send_messages: 1 << 1,
  read_message_history: 1 << 2,
  add_reactions: 1 << 3,
  connect: 1 << 4,
  speak: 1 << 5,
  mute_members: 1 << 6,
  deafen_members: 1 << 7,
  create_invite: 1 << 8,
  kick_members: 1 << 9,
  ban_members: 1 << 10,
  manage_messages: 1 << 11,
  manage_channels: 1 << 12,
  manage_roles: 1 << 13,
  manage_members: 1 << 14,
  manage_server: 1 << 15,
  view_audit_log: 1 << 16,
  administrator: 1 << 17,
};

export const CHANNEL_PERMISSIONS = [
  "view_channel",
  "send_messages",
  "read_message_history",
  "add_reactions",
  "connect",
  "speak",
  "mute_members",
  "deafen_members",
  "manage_messages",
  "create_invite",
] as const;

export function can(bits: number | undefined, permission: string): boolean {
  if (bits === undefined) {
    return false;
  }
  return (bits & PERMISSION_BITS[permission]) !== 0;
}
