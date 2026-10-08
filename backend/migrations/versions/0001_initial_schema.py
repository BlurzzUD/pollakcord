import sqlalchemy as sa
from alembic import op

revision = '0001'
down_revision = None
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.create_table('data_keys',
    sa.Column('id', sa.BigInteger(), autoincrement=False, nullable=False),
    sa.Column('scope_type', sa.String(length=8), nullable=False),
    sa.Column('scope_id', sa.BigInteger(), nullable=False),
    sa.Column('wrapped_key', sa.LargeBinary(), nullable=False),
    sa.Column('kek_id', sa.String(length=16), nullable=False),
    sa.Column('message_count', sa.Integer(), nullable=False),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_data_keys'))
    )
    with op.batch_alter_table('data_keys', schema=None) as batch_op:
        batch_op.create_index('ix_data_keys_scope', ['scope_type', 'scope_id', 'active'], unique=False)

    op.create_table('school_classes',
    sa.Column('id', sa.BigInteger(), autoincrement=False, nullable=False),
    sa.Column('code', sa.String(length=16), nullable=False),
    sa.Column('grade', sa.Integer(), nullable=False),
    sa.Column('section', sa.String(length=8), nullable=False),
    sa.Column('sort_order', sa.Integer(), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_school_classes')),
    sa.UniqueConstraint('code', name=op.f('uq_school_classes_code'))
    )
    op.create_table('users',
    sa.Column('id', sa.BigInteger(), autoincrement=False, nullable=False),
    sa.Column('username', sa.String(length=32), nullable=False),
    sa.Column('username_lower', sa.String(length=32), nullable=False),
    sa.Column('display_name', sa.String(length=40), nullable=False),
    sa.Column('status', sa.String(length=24), nullable=False),
    sa.Column('platform_role', sa.String(length=24), nullable=False),
    sa.Column('school_class_id', sa.BigInteger(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['school_class_id'], ['school_classes.id'], name=op.f('fk_users_school_class_id_school_classes'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_users'))
    )
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_users_school_class_id'), ['school_class_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_users_status'), ['status'], unique=False)
        batch_op.create_index(batch_op.f('ix_users_username_lower'), ['username_lower'], unique=True)

    op.create_table('audit_logs',
    sa.Column('id', sa.BigInteger(), autoincrement=False, nullable=False),
    sa.Column('server_id', sa.BigInteger(), nullable=True),
    sa.Column('actor_id', sa.BigInteger(), nullable=True),
    sa.Column('action', sa.String(length=48), nullable=False),
    sa.Column('target_type', sa.String(length=24), nullable=True),
    sa.Column('target_id', sa.BigInteger(), nullable=True),
    sa.Column('details', sa.JSON(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['actor_id'], ['users.id'], name=op.f('fk_audit_logs_actor_id_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_audit_logs'))
    )
    with op.batch_alter_table('audit_logs', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_audit_logs_action'), ['action'], unique=False)
        batch_op.create_index('ix_audit_logs_server_id_id', ['server_id', 'id'], unique=False)

    op.create_table('auth_methods',
    sa.Column('user_id', sa.BigInteger(), nullable=False),
    sa.Column('method', sa.String(length=10), nullable=False),
    sa.Column('password_hash', sa.String(length=255), nullable=True),
    sa.Column('failed_attempts', sa.Integer(), nullable=False),
    sa.Column('locked_until', sa.DateTime(timezone=True), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_auth_methods_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_id', name=op.f('pk_auth_methods'))
    )
    op.create_table('blocks',
    sa.Column('blocker_id', sa.BigInteger(), nullable=False),
    sa.Column('blocked_id', sa.BigInteger(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['blocked_id'], ['users.id'], name=op.f('fk_blocks_blocked_id_users'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['blocker_id'], ['users.id'], name=op.f('fk_blocks_blocker_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('blocker_id', 'blocked_id', name=op.f('pk_blocks'))
    )
    with op.batch_alter_table('blocks', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_blocks_blocked_id'), ['blocked_id'], unique=False)

    op.create_table('conversations',
    sa.Column('id', sa.BigInteger(), autoincrement=False, nullable=False),
    sa.Column('user_low_id', sa.BigInteger(), nullable=False),
    sa.Column('user_high_id', sa.BigInteger(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_message_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint('user_low_id < user_high_id', name=op.f('ck_conversations_ordered_pair')),
    sa.ForeignKeyConstraint(['user_high_id'], ['users.id'], name=op.f('fk_conversations_user_high_id_users'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_low_id'], ['users.id'], name=op.f('fk_conversations_user_low_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_conversations')),
    sa.UniqueConstraint('user_low_id', 'user_high_id', name=op.f('uq_conversations_user_low_id'))
    )
    with op.batch_alter_table('conversations', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_conversations_user_high_id'), ['user_high_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_conversations_user_low_id'), ['user_low_id'], unique=False)

    op.create_table('friend_requests',
    sa.Column('id', sa.BigInteger(), autoincrement=False, nullable=False),
    sa.Column('sender_id', sa.BigInteger(), nullable=False),
    sa.Column('recipient_id', sa.BigInteger(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['recipient_id'], ['users.id'], name=op.f('fk_friend_requests_recipient_id_users'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['sender_id'], ['users.id'], name=op.f('fk_friend_requests_sender_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_friend_requests')),
    sa.UniqueConstraint('sender_id', 'recipient_id', name=op.f('uq_friend_requests_sender_id'))
    )
    with op.batch_alter_table('friend_requests', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_friend_requests_recipient_id'), ['recipient_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_friend_requests_sender_id'), ['sender_id'], unique=False)

    op.create_table('friendships',
    sa.Column('id', sa.BigInteger(), autoincrement=False, nullable=False),
    sa.Column('user_low_id', sa.BigInteger(), nullable=False),
    sa.Column('user_high_id', sa.BigInteger(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint('user_low_id < user_high_id', name=op.f('ck_friendships_ordered_pair')),
    sa.ForeignKeyConstraint(['user_high_id'], ['users.id'], name=op.f('fk_friendships_user_high_id_users'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_low_id'], ['users.id'], name=op.f('fk_friendships_user_low_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_friendships')),
    sa.UniqueConstraint('user_low_id', 'user_high_id', name=op.f('uq_friendships_user_low_id'))
    )
    with op.batch_alter_table('friendships', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_friendships_user_high_id'), ['user_high_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_friendships_user_low_id'), ['user_low_id'], unique=False)

    op.create_table('notifications',
    sa.Column('id', sa.BigInteger(), autoincrement=False, nullable=False),
    sa.Column('user_id', sa.BigInteger(), nullable=False),
    sa.Column('type', sa.String(length=24), nullable=False),
    sa.Column('payload', sa.JSON(), nullable=False),
    sa.Column('dedupe_key', sa.String(length=64), nullable=True),
    sa.Column('read_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_notifications_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_notifications'))
    )
    with op.batch_alter_table('notifications', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_notifications_user_id'), ['user_id'], unique=False)
        batch_op.create_index('ix_notifications_user_read', ['user_id', 'read_at'], unique=False)

    op.create_table('profiles',
    sa.Column('user_id', sa.BigInteger(), nullable=False),
    sa.Column('bio', sa.String(length=300), nullable=False),
    sa.Column('avatar_key', sa.String(length=80), nullable=True),
    sa.Column('banner_key', sa.String(length=80), nullable=True),
    sa.Column('accent_color', sa.String(length=7), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_profiles_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_id', name=op.f('pk_profiles'))
    )
    op.create_table('read_states',
    sa.Column('user_id', sa.BigInteger(), nullable=False),
    sa.Column('scope_type', sa.String(length=8), nullable=False),
    sa.Column('scope_id', sa.BigInteger(), nullable=False),
    sa.Column('last_read_message_id', sa.BigInteger(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_read_states_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_id', 'scope_type', 'scope_id', name=op.f('pk_read_states'))
    )
    op.create_table('recovery_codes',
    sa.Column('id', sa.BigInteger(), autoincrement=False, nullable=False),
    sa.Column('user_id', sa.BigInteger(), nullable=False),
    sa.Column('code_hash', sa.String(length=64), nullable=False),
    sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_recovery_codes_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_recovery_codes'))
    )
    with op.batch_alter_table('recovery_codes', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_recovery_codes_code_hash'), ['code_hash'], unique=False)
        batch_op.create_index(batch_op.f('ix_recovery_codes_user_id'), ['user_id'], unique=False)

    op.create_table('servers',
    sa.Column('id', sa.BigInteger(), autoincrement=False, nullable=False),
    sa.Column('name', sa.String(length=60), nullable=False),
    sa.Column('description', sa.String(length=500), nullable=False),
    sa.Column('icon_key', sa.String(length=80), nullable=True),
    sa.Column('owner_id', sa.BigInteger(), nullable=False),
    sa.Column('moderation_settings', sa.JSON(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], name=op.f('fk_servers_owner_id_users'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_servers'))
    )
    with op.batch_alter_table('servers', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_servers_owner_id'), ['owner_id'], unique=False)

    op.create_table('sessions',
    sa.Column('id', sa.BigInteger(), autoincrement=False, nullable=False),
    sa.Column('user_id', sa.BigInteger(), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('scope', sa.String(length=12), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('ip_hint', sa.String(length=64), nullable=False),
    sa.Column('user_agent', sa.String(length=200), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_sessions_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_sessions'))
    )
    with op.batch_alter_table('sessions', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_sessions_token_hash'), ['token_hash'], unique=True)
        batch_op.create_index(batch_op.f('ix_sessions_user_id'), ['user_id'], unique=False)

    op.create_table('themes',
    sa.Column('id', sa.BigInteger(), autoincrement=False, nullable=False),
    sa.Column('user_id', sa.BigInteger(), nullable=False),
    sa.Column('name', sa.String(length=40), nullable=False),
    sa.Column('tokens', sa.JSON(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_themes_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_themes'))
    )
    with op.batch_alter_table('themes', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_themes_user_id'), ['user_id'], unique=False)

    op.create_table('totp_configs',
    sa.Column('user_id', sa.BigInteger(), nullable=False),
    sa.Column('secret_enc', sa.LargeBinary(), nullable=False),
    sa.Column('key_id', sa.String(length=16), nullable=False),
    sa.Column('confirmed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_used_step', sa.BigInteger(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_totp_configs_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_id', name=op.f('pk_totp_configs'))
    )
    op.create_table('user_identities',
    sa.Column('user_id', sa.BigInteger(), nullable=False),
    sa.Column('identity_hash', sa.String(length=64), nullable=False),
    sa.Column('real_name_enc', sa.LargeBinary(), nullable=False),
    sa.Column('key_id', sa.String(length=16), nullable=False),
    sa.Column('verified_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_user_identities_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_id', name=op.f('pk_user_identities'))
    )
    with op.batch_alter_table('user_identities', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_user_identities_identity_hash'), ['identity_hash'], unique=True)

    op.create_table('user_settings',
    sa.Column('user_id', sa.BigInteger(), nullable=False),
    sa.Column('language', sa.String(length=5), nullable=False),
    sa.Column('theme_mode', sa.String(length=10), nullable=False),
    sa.Column('active_theme_id', sa.BigInteger(), nullable=True),
    sa.Column('custom_css', sa.Text(), nullable=False),
    sa.Column('developer_mode', sa.Boolean(), nullable=False),
    sa.Column('chat_appearance', sa.JSON(), nullable=False),
    sa.Column('notification_prefs', sa.JSON(), nullable=False),
    sa.Column('friend_requests', sa.String(length=16), nullable=False),
    sa.Column('direct_messages', sa.String(length=16), nullable=False),
    sa.Column('class_visibility', sa.String(length=16), nullable=False),
    sa.Column('online_status', sa.String(length=16), nullable=False),
    sa.Column('profile_visibility', sa.String(length=16), nullable=False),
    sa.Column('activity_visibility', sa.String(length=16), nullable=False),
    sa.Column('voice_calls', sa.String(length=16), nullable=False),
    sa.Column('class_prompt_answered', sa.Boolean(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_user_settings_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_id', name=op.f('pk_user_settings'))
    )
    with op.batch_alter_table('user_settings', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_user_settings_class_visibility'), ['class_visibility'], unique=False)

    op.create_table('bans',
    sa.Column('server_id', sa.BigInteger(), nullable=False),
    sa.Column('user_id', sa.BigInteger(), nullable=False),
    sa.Column('reason', sa.String(length=300), nullable=False),
    sa.Column('banned_by', sa.BigInteger(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['banned_by'], ['users.id'], name=op.f('fk_bans_banned_by_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['server_id'], ['servers.id'], name=op.f('fk_bans_server_id_servers'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_bans_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('server_id', 'user_id', name=op.f('pk_bans'))
    )
    op.create_table('categories',
    sa.Column('id', sa.BigInteger(), autoincrement=False, nullable=False),
    sa.Column('server_id', sa.BigInteger(), nullable=False),
    sa.Column('name', sa.String(length=60), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['server_id'], ['servers.id'], name=op.f('fk_categories_server_id_servers'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_categories'))
    )
    with op.batch_alter_table('categories', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_categories_server_id'), ['server_id'], unique=False)

    op.create_table('invites',
    sa.Column('id', sa.BigInteger(), autoincrement=False, nullable=False),
    sa.Column('code', sa.String(length=24), nullable=False),
    sa.Column('server_id', sa.BigInteger(), nullable=False),
    sa.Column('creator_id', sa.BigInteger(), nullable=True),
    sa.Column('max_uses', sa.Integer(), nullable=True),
    sa.Column('uses', sa.Integer(), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['creator_id'], ['users.id'], name=op.f('fk_invites_creator_id_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['server_id'], ['servers.id'], name=op.f('fk_invites_server_id_servers'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_invites'))
    )
    with op.batch_alter_table('invites', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_invites_code'), ['code'], unique=True)
        batch_op.create_index(batch_op.f('ix_invites_server_id'), ['server_id'], unique=False)

    op.create_table('permission_overwrites',
    sa.Column('id', sa.BigInteger(), autoincrement=False, nullable=False),
    sa.Column('server_id', sa.BigInteger(), nullable=False),
    sa.Column('scope_type', sa.String(length=10), nullable=False),
    sa.Column('scope_id', sa.BigInteger(), nullable=False),
    sa.Column('target_type', sa.String(length=8), nullable=False),
    sa.Column('target_id', sa.BigInteger(), nullable=False),
    sa.Column('allow', sa.BigInteger(), nullable=False),
    sa.Column('deny', sa.BigInteger(), nullable=False),
    sa.ForeignKeyConstraint(['server_id'], ['servers.id'], name=op.f('fk_permission_overwrites_server_id_servers'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_permission_overwrites')),
    sa.UniqueConstraint('scope_type', 'scope_id', 'target_type', 'target_id', name=op.f('uq_permission_overwrites_scope_type'))
    )
    with op.batch_alter_table('permission_overwrites', schema=None) as batch_op:
        batch_op.create_index('ix_overwrites_scope', ['scope_type', 'scope_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_permission_overwrites_server_id'), ['server_id'], unique=False)

    op.create_table('reports',
    sa.Column('id', sa.BigInteger(), autoincrement=False, nullable=False),
    sa.Column('reporter_id', sa.BigInteger(), nullable=True),
    sa.Column('target_user_id', sa.BigInteger(), nullable=True),
    sa.Column('message_id', sa.BigInteger(), nullable=True),
    sa.Column('server_id', sa.BigInteger(), nullable=True),
    sa.Column('channel_id', sa.BigInteger(), nullable=True),
    sa.Column('conversation_id', sa.BigInteger(), nullable=True),
    sa.Column('reason', sa.String(length=32), nullable=False),
    sa.Column('details', sa.String(length=500), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('escalated', sa.Boolean(), nullable=False),
    sa.Column('snapshot_enc', sa.LargeBinary(), nullable=True),
    sa.Column('key_id', sa.String(length=16), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('handled_by', sa.BigInteger(), nullable=True),
    sa.Column('handled_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('resolution', sa.String(length=32), nullable=True),
    sa.Column('note', sa.String(length=500), nullable=False),
    sa.ForeignKeyConstraint(['reporter_id'], ['users.id'], name=op.f('fk_reports_reporter_id_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['server_id'], ['servers.id'], name=op.f('fk_reports_server_id_servers'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['target_user_id'], ['users.id'], name=op.f('fk_reports_target_user_id_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_reports'))
    )
    with op.batch_alter_table('reports', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_reports_server_id'), ['server_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_reports_status'), ['status'], unique=False)
        batch_op.create_index(batch_op.f('ix_reports_target_user_id'), ['target_user_id'], unique=False)

    op.create_table('roles',
    sa.Column('id', sa.BigInteger(), autoincrement=False, nullable=False),
    sa.Column('server_id', sa.BigInteger(), nullable=False),
    sa.Column('name', sa.String(length=40), nullable=False),
    sa.Column('color', sa.String(length=7), nullable=True),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('permissions', sa.BigInteger(), nullable=False),
    sa.Column('is_default', sa.Boolean(), nullable=False),
    sa.Column('kind', sa.String(length=16), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['server_id'], ['servers.id'], name=op.f('fk_roles_server_id_servers'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_roles'))
    )
    with op.batch_alter_table('roles', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_roles_server_id'), ['server_id'], unique=False)

    op.create_table('server_members',
    sa.Column('server_id', sa.BigInteger(), nullable=False),
    sa.Column('user_id', sa.BigInteger(), nullable=False),
    sa.Column('nickname', sa.String(length=40), nullable=True),
    sa.Column('joined_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('timeout_until', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['server_id'], ['servers.id'], name=op.f('fk_server_members_server_id_servers'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_server_members_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('server_id', 'user_id', name=op.f('pk_server_members'))
    )
    with op.batch_alter_table('server_members', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_server_members_user_id'), ['user_id'], unique=False)

    op.create_table('channels',
    sa.Column('id', sa.BigInteger(), autoincrement=False, nullable=False),
    sa.Column('server_id', sa.BigInteger(), nullable=False),
    sa.Column('category_id', sa.BigInteger(), nullable=True),
    sa.Column('type', sa.String(length=8), nullable=False),
    sa.Column('name', sa.String(length=60), nullable=False),
    sa.Column('topic', sa.String(length=300), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('user_limit', sa.Integer(), nullable=False),
    sa.Column('slowmode_seconds', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['category_id'], ['categories.id'], name=op.f('fk_channels_category_id_categories'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['server_id'], ['servers.id'], name=op.f('fk_channels_server_id_servers'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_channels'))
    )
    with op.batch_alter_table('channels', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_channels_server_id'), ['server_id'], unique=False)

    op.create_table('member_roles',
    sa.Column('server_id', sa.BigInteger(), nullable=False),
    sa.Column('user_id', sa.BigInteger(), nullable=False),
    sa.Column('role_id', sa.BigInteger(), nullable=False),
    sa.ForeignKeyConstraint(['role_id'], ['roles.id'], name=op.f('fk_member_roles_role_id_roles'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['server_id', 'user_id'], ['server_members.server_id', 'server_members.user_id'], name=op.f('fk_member_roles_server_id_server_members'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('server_id', 'user_id', 'role_id', name=op.f('pk_member_roles'))
    )
    with op.batch_alter_table('member_roles', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_member_roles_role_id'), ['role_id'], unique=False)

    op.create_table('messages',
    sa.Column('id', sa.BigInteger(), autoincrement=False, nullable=False),
    sa.Column('channel_id', sa.BigInteger(), nullable=True),
    sa.Column('conversation_id', sa.BigInteger(), nullable=True),
    sa.Column('author_id', sa.BigInteger(), nullable=True),
    sa.Column('reply_to_id', sa.BigInteger(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('pinned_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('pinned_by', sa.BigInteger(), nullable=True),
    sa.CheckConstraint('(channel_id IS NOT NULL AND conversation_id IS NULL) OR (channel_id IS NULL AND conversation_id IS NOT NULL)', name=op.f('ck_messages_single_scope')),
    sa.ForeignKeyConstraint(['author_id'], ['users.id'], name=op.f('fk_messages_author_id_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['channel_id'], ['channels.id'], name=op.f('fk_messages_channel_id_channels'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'], name=op.f('fk_messages_conversation_id_conversations'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_messages'))
    )
    with op.batch_alter_table('messages', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_messages_author_id'), ['author_id'], unique=False)
        batch_op.create_index('ix_messages_channel_id_id', ['channel_id', 'id'], unique=False)
        batch_op.create_index('ix_messages_conversation_id_id', ['conversation_id', 'id'], unique=False)

    op.create_table('message_contents',
    sa.Column('message_id', sa.BigInteger(), nullable=False),
    sa.Column('data_key_id', sa.BigInteger(), nullable=False),
    sa.Column('ciphertext', sa.LargeBinary(), nullable=False),
    sa.Column('algorithm', sa.String(length=16), nullable=False),
    sa.ForeignKeyConstraint(['data_key_id'], ['data_keys.id'], name=op.f('fk_message_contents_data_key_id_data_keys'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['message_id'], ['messages.id'], name=op.f('fk_message_contents_message_id_messages'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('message_id', name=op.f('pk_message_contents'))
    )
    with op.batch_alter_table('message_contents', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_message_contents_data_key_id'), ['data_key_id'], unique=False)

    op.create_table('message_mentions',
    sa.Column('message_id', sa.BigInteger(), nullable=False),
    sa.Column('user_id', sa.BigInteger(), nullable=False),
    sa.ForeignKeyConstraint(['message_id'], ['messages.id'], name=op.f('fk_message_mentions_message_id_messages'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_message_mentions_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('message_id', 'user_id', name=op.f('pk_message_mentions'))
    )
    with op.batch_alter_table('message_mentions', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_message_mentions_user_id'), ['user_id'], unique=False)

    op.create_table('message_reactions',
    sa.Column('message_id', sa.BigInteger(), nullable=False),
    sa.Column('user_id', sa.BigInteger(), nullable=False),
    sa.Column('emoji', sa.String(length=32), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['message_id'], ['messages.id'], name=op.f('fk_message_reactions_message_id_messages'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_message_reactions_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('message_id', 'user_id', 'emoji', name=op.f('pk_message_reactions'))
    )
    op.create_table('message_search_tokens',
    sa.Column('message_id', sa.BigInteger(), nullable=False),
    sa.Column('token_hash', sa.LargeBinary(length=16), nullable=False),
    sa.ForeignKeyConstraint(['message_id'], ['messages.id'], name=op.f('fk_message_search_tokens_message_id_messages'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('message_id', 'token_hash', name=op.f('pk_message_search_tokens'))
    )
    with op.batch_alter_table('message_search_tokens', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_message_search_tokens_token_hash'), ['token_hash'], unique=False)

    school_classes = sa.table(
        "school_classes",
        sa.column("id", sa.BigInteger),
        sa.column("code", sa.String),
        sa.column("grade", sa.Integer),
        sa.column("section", sa.String),
        sa.column("sort_order", sa.Integer),
        sa.column("is_active", sa.Boolean),
    )
    rows = []
    for index, (grade, section) in enumerate((g, s) for g in (9, 10, 11, 12, 13, 14) for s in ("A", "B")):
        rows.append(
            {"id": 1000 + index, "code": f"{grade}{section}", "grade": grade, "section": section, "sort_order": index, "is_active": True}
        )
    op.bulk_insert(school_classes, rows)


def downgrade() -> None:

    with op.batch_alter_table('message_search_tokens', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_message_search_tokens_token_hash'))

    op.drop_table('message_search_tokens')
    op.drop_table('message_reactions')
    with op.batch_alter_table('message_mentions', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_message_mentions_user_id'))

    op.drop_table('message_mentions')
    with op.batch_alter_table('message_contents', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_message_contents_data_key_id'))

    op.drop_table('message_contents')
    with op.batch_alter_table('messages', schema=None) as batch_op:
        batch_op.drop_index('ix_messages_conversation_id_id')
        batch_op.drop_index('ix_messages_channel_id_id')
        batch_op.drop_index(batch_op.f('ix_messages_author_id'))

    op.drop_table('messages')
    with op.batch_alter_table('member_roles', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_member_roles_role_id'))

    op.drop_table('member_roles')
    with op.batch_alter_table('channels', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_channels_server_id'))

    op.drop_table('channels')
    with op.batch_alter_table('server_members', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_server_members_user_id'))

    op.drop_table('server_members')
    with op.batch_alter_table('roles', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_roles_server_id'))

    op.drop_table('roles')
    with op.batch_alter_table('reports', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_reports_target_user_id'))
        batch_op.drop_index(batch_op.f('ix_reports_status'))
        batch_op.drop_index(batch_op.f('ix_reports_server_id'))

    op.drop_table('reports')
    with op.batch_alter_table('permission_overwrites', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_permission_overwrites_server_id'))
        batch_op.drop_index('ix_overwrites_scope')

    op.drop_table('permission_overwrites')
    with op.batch_alter_table('invites', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_invites_server_id'))
        batch_op.drop_index(batch_op.f('ix_invites_code'))

    op.drop_table('invites')
    with op.batch_alter_table('categories', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_categories_server_id'))

    op.drop_table('categories')
    op.drop_table('bans')
    with op.batch_alter_table('user_settings', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_user_settings_class_visibility'))

    op.drop_table('user_settings')
    with op.batch_alter_table('user_identities', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_user_identities_identity_hash'))

    op.drop_table('user_identities')
    op.drop_table('totp_configs')
    with op.batch_alter_table('themes', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_themes_user_id'))

    op.drop_table('themes')
    with op.batch_alter_table('sessions', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_sessions_user_id'))
        batch_op.drop_index(batch_op.f('ix_sessions_token_hash'))

    op.drop_table('sessions')
    with op.batch_alter_table('servers', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_servers_owner_id'))

    op.drop_table('servers')
    with op.batch_alter_table('recovery_codes', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_recovery_codes_user_id'))
        batch_op.drop_index(batch_op.f('ix_recovery_codes_code_hash'))

    op.drop_table('recovery_codes')
    op.drop_table('read_states')
    op.drop_table('profiles')
    with op.batch_alter_table('notifications', schema=None) as batch_op:
        batch_op.drop_index('ix_notifications_user_read')
        batch_op.drop_index(batch_op.f('ix_notifications_user_id'))

    op.drop_table('notifications')
    with op.batch_alter_table('friendships', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_friendships_user_low_id'))
        batch_op.drop_index(batch_op.f('ix_friendships_user_high_id'))

    op.drop_table('friendships')
    with op.batch_alter_table('friend_requests', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_friend_requests_sender_id'))
        batch_op.drop_index(batch_op.f('ix_friend_requests_recipient_id'))

    op.drop_table('friend_requests')
    with op.batch_alter_table('conversations', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_conversations_user_low_id'))
        batch_op.drop_index(batch_op.f('ix_conversations_user_high_id'))

    op.drop_table('conversations')
    with op.batch_alter_table('blocks', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_blocks_blocked_id'))

    op.drop_table('blocks')
    op.drop_table('auth_methods')
    with op.batch_alter_table('audit_logs', schema=None) as batch_op:
        batch_op.drop_index('ix_audit_logs_server_id_id')
        batch_op.drop_index(batch_op.f('ix_audit_logs_action'))

    op.drop_table('audit_logs')
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_users_username_lower'))
        batch_op.drop_index(batch_op.f('ix_users_status'))
        batch_op.drop_index(batch_op.f('ix_users_school_class_id'))

    op.drop_table('users')
    op.drop_table('school_classes')
    with op.batch_alter_table('data_keys', schema=None) as batch_op:
        batch_op.drop_index('ix_data_keys_scope')

    op.drop_table('data_keys')
