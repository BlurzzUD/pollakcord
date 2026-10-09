import sqlalchemy as sa
from alembic import op

revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('dok_threads',
    sa.Column('id', sa.BigInteger(), autoincrement=False, nullable=False),
    sa.Column('scope', sa.String(length=8), nullable=False),
    sa.Column('school_class_id', sa.BigInteger(), nullable=True),
    sa.Column('target_key', sa.String(length=32), nullable=False),
    sa.Column('created_by', sa.BigInteger(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_message_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_dok_threads_created_by_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['school_class_id'], ['school_classes.id'], name=op.f('fk_dok_threads_school_class_id_school_classes'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_dok_threads')),
    sa.UniqueConstraint('target_key', name=op.f('uq_dok_threads_target_key'))
    )
    op.create_table('dok_messages',
    sa.Column('id', sa.BigInteger(), autoincrement=False, nullable=False),
    sa.Column('thread_id', sa.BigInteger(), nullable=False),
    sa.Column('author_id', sa.BigInteger(), nullable=True),
    sa.Column('author_role', sa.String(length=24), nullable=False),
    sa.Column('body_enc', sa.LargeBinary(), nullable=False),
    sa.Column('key_id', sa.String(length=16), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['author_id'], ['users.id'], name=op.f('fk_dok_messages_author_id_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['thread_id'], ['dok_threads.id'], name=op.f('fk_dok_messages_thread_id_dok_threads'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_dok_messages'))
    )
    with op.batch_alter_table('dok_messages', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_dok_messages_author_id'), ['author_id'], unique=False)
        batch_op.create_index('ix_dok_messages_thread_id_id', ['thread_id', 'id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('dok_messages', schema=None) as batch_op:
        batch_op.drop_index('ix_dok_messages_thread_id_id')
        batch_op.drop_index(batch_op.f('ix_dok_messages_author_id'))

    op.drop_table('dok_messages')
    op.drop_table('dok_threads')
