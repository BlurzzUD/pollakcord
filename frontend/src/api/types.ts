export type Id = string;
export type Language = "hu" | "en" | "de";
export type ThemeMode = "system" | "dark" | "light" | "custom";
export type Presence = "online" | "offline" | null;

export interface UserCard {
  id: Id;
  username: string;
  display_name: string;
  avatar_url: string | null;
  staff: boolean;
  nickname?: string | null;
  is_member?: boolean;
  presence?: Presence;
  is_friend?: boolean;
  mutual_friends?: number | null;
  class_code?: string | null;
}

export interface Privacy {
  friend_requests: "everyone" | "shared_servers" | "nobody";
  direct_messages: "everyone" | "shared_servers" | "friends";
  class_visibility: "hidden" | "friends" | "shared_servers" | "everyone";
  online_status: "nobody" | "friends" | "shared_servers";
  profile_visibility: "everyone" | "shared_context" | "friends";
  activity_visibility: "nobody" | "friends";
  voice_calls: "friends" | "nobody";
}

export interface ChatAppearance {
  density: "compact" | "cozy";
  font_scale: number;
  show_timestamps: boolean;
}

export type NotificationPrefs = Record<
  "friend_requests" | "direct_messages" | "mentions" | "server" | "calls" | "moderation" | "dok" | "sounds",
  boolean
>;

export interface Settings {
  language: Language;
  theme_mode: ThemeMode;
  active_theme_id: Id | null;
  custom_css: string;
  developer_mode: boolean;
  chat_appearance: ChatAppearance;
  notification_prefs: NotificationPrefs;
  privacy: Privacy;
  class_prompt_answered: boolean;
}

export interface Me extends UserCard {
  bio: string;
  banner_url: string | null;
  accent_color: string | null;
  created_at: string;
  status: string;
  platform_role: "user" | "school_moderator" | "school_admin" | "dok_representative" | "dok_president";
  class_code: string | null;
  settings: Settings;
}

export interface Profile extends UserCard {
  bio: string;
  banner_url: string | null;
  accent_color: string | null;
  created_at: string;
  class_code: string | null;
  presence: Presence;
  last_seen_at: string | null;
  mutual_friends: number | null;
  relation: { friends: boolean; blocked: boolean; shares_server: boolean; pending: "incoming" | "outgoing" | null } | null;
  shared_servers: { id: Id; name: string; icon_url: string | null }[];
}

export interface SchoolClass {
  id: Id;
  code: string;
  grade: number;
  section: string;
}

export interface ThemeTokens {
  bg?: string;
  bg_alt?: string;
  bg_deep?: string;
  text?: string;
  text_muted?: string;
  accent?: string;
  accent_text?: string;
  danger?: string;
  mention?: string;
  border?: string;
  background?: string;
  radius?: string;
}

export interface SavedTheme {
  id: Id;
  name: string;
  tokens: ThemeTokens;
}

export interface Reaction {
  emoji: string;
  count: number;
  me: boolean;
}

export interface ReplyPreview {
  id: Id;
  author_id: Id | null;
  deleted: boolean;
  preview: string | null;
}

export interface Message {
  id: Id;
  scope: "dm" | "channel";
  channel_id: Id | null;
  conversation_id: Id | null;
  author: UserCard | null;
  content: string | null;
  deleted: boolean;
  created_at: string;
  reply_to: ReplyPreview | null;
  pinned: boolean;
  reactions: Reaction[];
}

export interface HistoryPage {
  messages: Message[];
  has_more: boolean;
  last_read_message_id: Id | null;
}

export interface Conversation {
  id: Id;
  user: UserCard;
  presence: Presence;
  last_message: { content: string; author_id: Id | null; created_at: string } | null;
  last_message_at: string | null;
  unread: number;
}

export interface FriendRequestEntry {
  id: Id;
  user: UserCard;
  created_at: string;
}

export interface ServerSummary {
  id: Id;
  name: string;
  description: string;
  icon_url: string | null;
  owner_id: Id;
  member_count: number | null;
  created_at: string;
}

export interface Role {
  id: Id;
  name: string;
  color: string | null;
  position: number;
  permissions: number;
  permission_names: string[];
  is_default: boolean;
  kind: "member" | "moderator" | "administrator" | "custom";
}

export interface Category {
  id: Id;
  name: string;
  position: number;
}

export interface Channel {
  id: Id;
  server_id: Id;
  category_id: Id | null;
  type: "text" | "voice";
  name: string;
  topic: string;
  position: number;
  user_limit: number;
  slowmode_seconds: number;
  my_permissions?: number;
}

export interface VoiceParticipant {
  user_id: Id;
  muted: boolean;
  deafened: boolean;
  server_muted: boolean;
  server_deafened: boolean;
}

export interface ServerDetail extends ServerSummary {
  moderation_settings: { reports_enabled: boolean; invites_enabled: boolean; max_mentions_per_message: number };
  is_owner: boolean;
  my_permissions: number;
  my_permission_names: string[];
  my_role_ids: Id[];
  roles: Role[];
  categories: Category[];
  channels: Channel[];
  voice_states: Record<Id, VoiceParticipant[]>;
  unread: Record<Id, number>;
  invite_code?: string;
}

export interface Member {
  user: UserCard;
  nickname: string | null;
  role_ids: Id[];
  joined_at: string;
  timeout_until: string | null;
  presence: Presence;
  is_owner: boolean;
}

export interface InviteEntry {
  code: string;
  creator: UserCard | null;
  uses: number;
  max_uses: number | null;
  expires_at: string | null;
  revoked: boolean;
  created_at: string;
}

export interface AppNotification {
  id: Id;
  type: "friend_request" | "friend_accepted" | "dm" | "mention" | "server" | "call_incoming" | "call_missed" | "moderation" | "dok_message";
  payload: Record<string, any>;
  read: boolean;
  created_at: string;
}

export interface AuditEntry {
  id: Id;
  action: string;
  actor: UserCard | null;
  target_type: string | null;
  target_id: Id | null;
  target_user: UserCard | null;
  details: Record<string, unknown>;
  created_at: string;
}

export interface ReportEntry {
  id: Id;
  reason: string;
  details: string;
  status: "open" | "resolved" | "dismissed";
  escalated: boolean;
  server_id: Id | null;
  channel_id: Id | null;
  conversation_id: Id | null;
  message_id: Id | null;
  created_at: string;
  resolution: string | null;
  note: string;
  target: UserCard | null;
  reporter: UserCard | null;
  context?: { id: Id; content: string | null; created_at: string; reported: boolean; deleted: boolean; author?: UserCard | null }[];
}

export interface Meta {
  app_name: string;
  reactions: string[];
  permissions: string[];
  report_reasons: string[];
  limits: { message_max_length: number; voice_max_participants: number };
}

export interface SessionInfo {
  authenticated: boolean;
  user?: Me;
  setup?: { username: string; display_name: string };
  suspended?: boolean;
}

export interface SessionRow {
  id: Id;
  current: boolean;
  created_at: string;
  last_seen_at: string;
  ip_hint: string;
  user_agent: string;
}

export interface IceConfig {
  ice_servers: RTCIceServer[];
  max_participants: number;
}

export type DokRole = "dok_representative" | "dok_president";
export type DokScope = "class" | "school";
export type DokTarget = { type: "school" } | { type: "class"; class_id: Id; code: string };

export interface DokThread {
  id: Id;
  scope: DokScope;
  class: { id: Id; code: string } | null;
  last_message: { preview: string; created_at: string } | null;
  last_message_at: string;
  unread: number;
  can_send: boolean;
}

export interface DokInbox {
  threads: DokThread[];
  unread: number;
  send: { allowed: boolean; targets: DokTarget[] };
}

export interface DokMessage {
  id: Id;
  thread_id: Id;
  scope: DokScope;
  author_role: DokRole;
  author: UserCard | null;
  mine: boolean;
  content: string;
  created_at: string;
}

export interface DokHistoryPage {
  messages: DokMessage[];
  has_more: boolean;
  last_read_message_id: Id | null;
}
