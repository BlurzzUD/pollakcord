import sqlalchemy as sa
from alembic import op

revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('class_space_members',
    sa.Column('user_id', sa.BigInteger(), nullable=False),
    sa.Column('school_class_id', sa.BigInteger(), nullable=False),
    sa.Column('show_username', sa.Boolean(), nullable=False),
    sa.Column('answered_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['school_class_id'], ['school_classes.id'], name=op.f('fk_class_space_members_school_class_id_school_classes'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_class_space_members_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_id', name=op.f('pk_class_space_members'))
    )
    with op.batch_alter_table('class_space_members', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_class_space_members_school_class_id'), ['school_class_id'], unique=False)

    op.create_table('class_space_messages',
    sa.Column('id', sa.BigInteger(), autoincrement=False, nullable=False),
    sa.Column('school_class_id', sa.BigInteger(), nullable=False),
    sa.Column('author_id', sa.BigInteger(), nullable=True),
    sa.Column('author_visible', sa.Boolean(), nullable=False),
    sa.Column('body_enc', sa.LargeBinary(), nullable=False),
    sa.Column('key_id', sa.String(length=16), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['author_id'], ['users.id'], name=op.f('fk_class_space_messages_author_id_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['school_class_id'], ['school_classes.id'], name=op.f('fk_class_space_messages_school_class_id_school_classes'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_class_space_messages'))
    )
    with op.batch_alter_table('class_space_messages', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_class_space_messages_author_id'), ['author_id'], unique=False)
        batch_op.create_index('ix_class_space_messages_school_class_id_id', ['school_class_id', 'id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('class_space_messages', schema=None) as batch_op:
        batch_op.drop_index('ix_class_space_messages_school_class_id_id')
        batch_op.drop_index(batch_op.f('ix_class_space_messages_author_id'))

    op.drop_table('class_space_messages')
    with op.batch_alter_table('class_space_members', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_class_space_members_school_class_id'))

    op.drop_table('class_space_members')
