import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("is_bot", sa.Boolean(), server_default="0", nullable=False))
        batch.create_check_constraint("bot_school_boundary", "NOT is_bot OR (platform_role = 'user' AND school_class_id IS NULL)")
    op.create_table(
        "bot_applications",
        sa.Column("bot_user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("owner_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=True, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_bot_applications_owner_id", "bot_applications", ["owner_id"])
    op.create_table(
        "bot_installs",
        sa.Column("server_id", sa.BigInteger(), primary_key=True),
        sa.Column("bot_user_id", sa.BigInteger(), sa.ForeignKey("bot_applications.bot_user_id", ondelete="CASCADE"), primary_key=True),
        sa.Column("role_id", sa.BigInteger(), sa.ForeignKey("roles.id", ondelete="SET NULL"), nullable=True),
        sa.Column("permissions", sa.BigInteger(), nullable=False),
        sa.Column("installed_by", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["server_id", "bot_user_id"], ["server_members.server_id", "server_members.user_id"], ondelete="CASCADE"),
    )
    op.create_table(
        "bot_commands",
        sa.Column("id", sa.BigInteger(), autoincrement=False, primary_key=True),
        sa.Column("bot_user_id", sa.BigInteger(), sa.ForeignKey("bot_applications.bot_user_id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(32), nullable=False),
        sa.Column("description", sa.String(100), nullable=False),
        sa.Column("options", sa.JSON(), nullable=False),
        sa.Column("default_member_permissions", sa.BigInteger(), nullable=False),
        sa.UniqueConstraint("bot_user_id", "name"),
    )
    op.create_index("ix_bot_commands_bot_user_id", "bot_commands", ["bot_user_id"])
    op.create_table(
        "bot_interactions",
        sa.Column("id", sa.BigInteger(), autoincrement=False, primary_key=True),
        sa.Column("bot_user_id", sa.BigInteger(), sa.ForeignKey("bot_applications.bot_user_id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("command_id", sa.BigInteger(), sa.ForeignKey("bot_commands.id", ondelete="SET NULL"), nullable=True),
        sa.Column("channel_id", sa.BigInteger(), sa.ForeignKey("channels.id", ondelete="CASCADE"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("response_message_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_bot_interactions_bot_user_id", "bot_interactions", ["bot_user_id"])
    op.create_index("ix_bot_interactions_channel_id", "bot_interactions", ["channel_id"])


def downgrade() -> None:
    for table in ("bot_interactions", "bot_commands", "bot_installs", "bot_applications"):
        op.drop_table(table)
    with op.batch_alter_table("users") as batch:
        batch.drop_constraint("bot_school_boundary", type_="check")
        batch.drop_column("is_bot")
