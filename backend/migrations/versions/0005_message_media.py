import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ("messages", "dok_messages", "class_space_messages"):
        op.add_column(table, sa.Column("media_enc", sa.LargeBinary(), nullable=True))
        op.add_column(table, sa.Column("media_key_id", sa.String(16), nullable=True))
    op.create_table(
        "attachments",
        sa.Column("id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("owner_id", sa.BigInteger(), nullable=False),
        sa.Column("channel_id", sa.BigInteger(), nullable=True),
        sa.Column("conversation_id", sa.BigInteger(), nullable=True),
        sa.Column("message_id", sa.BigInteger(), nullable=True),
        sa.Column("storage_key", sa.String(32), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("mime_type", sa.String(100), nullable=False),
        sa.Column("kind", sa.String(8), nullable=False),
        sa.Column("metadata_enc", sa.LargeBinary(), nullable=False),
        sa.Column("key_id", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "(channel_id IS NOT NULL AND conversation_id IS NULL) OR (channel_id IS NULL AND conversation_id IS NOT NULL)",
            name=op.f("ck_attachments_single_scope"),
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], name=op.f("fk_attachments_owner_id_users"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["channel_id"], ["channels.id"], name=op.f("fk_attachments_channel_id_channels"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], name=op.f("fk_attachments_conversation_id_conversations"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], name=op.f("fk_attachments_message_id_messages"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_attachments")),
        sa.UniqueConstraint("storage_key", name=op.f("uq_attachments_storage_key")),
    )
    op.create_index("ix_attachments_owner_id", "attachments", ["owner_id"])
    op.create_index("ix_attachments_message_id", "attachments", ["message_id"])


def downgrade() -> None:
    op.drop_table("attachments")
    for table in ("messages", "dok_messages", "class_space_messages"):
        with op.batch_alter_table(table) as batch:
            batch.drop_column("media_key_id")
            batch.drop_column("media_enc")
