import sqlalchemy as sa
from alembic import op

revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('forms',
    sa.Column('id', sa.BigInteger(), autoincrement=False, nullable=False),
    sa.Column('creator_id', sa.BigInteger(), nullable=True),
    sa.Column('creator_role', sa.String(length=24), nullable=False),
    sa.Column('title', sa.String(length=120), nullable=False),
    sa.Column('description', sa.String(length=1000), nullable=False),
    sa.Column('target_scope', sa.String(length=8), nullable=False),
    sa.Column('school_class_id', sa.BigInteger(), nullable=True),
    sa.Column('status', sa.String(length=8), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('closed_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['creator_id'], ['users.id'], name=op.f('fk_forms_creator_id_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['school_class_id'], ['school_classes.id'], name=op.f('fk_forms_school_class_id_school_classes'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_forms'))
    )
    with op.batch_alter_table('forms', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_forms_creator_id'), ['creator_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_forms_school_class_id'), ['school_class_id'], unique=False)

    op.create_table('form_questions',
    sa.Column('id', sa.BigInteger(), autoincrement=False, nullable=False),
    sa.Column('form_id', sa.BigInteger(), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('type', sa.String(length=16), nullable=False),
    sa.Column('label', sa.String(length=200), nullable=False),
    sa.Column('required', sa.Boolean(), nullable=False),
    sa.Column('options', sa.JSON(), nullable=False),
    sa.ForeignKeyConstraint(['form_id'], ['forms.id'], name=op.f('fk_form_questions_form_id_forms'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_form_questions'))
    )
    with op.batch_alter_table('form_questions', schema=None) as batch_op:
        batch_op.create_index('ix_form_questions_form_id_position', ['form_id', 'position'], unique=False)

    op.create_table('form_responses',
    sa.Column('id', sa.BigInteger(), autoincrement=False, nullable=False),
    sa.Column('form_id', sa.BigInteger(), nullable=False),
    sa.Column('user_id', sa.BigInteger(), nullable=False),
    sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['form_id'], ['forms.id'], name=op.f('fk_form_responses_form_id_forms'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_form_responses_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_form_responses')),
    sa.UniqueConstraint('form_id', 'user_id', name=op.f('uq_form_responses_form_id'))
    )
    with op.batch_alter_table('form_responses', schema=None) as batch_op:
        batch_op.create_index('ix_form_responses_form_id_id', ['form_id', 'id'], unique=False)
        batch_op.create_index(batch_op.f('ix_form_responses_user_id'), ['user_id'], unique=False)

    op.create_table('form_answers',
    sa.Column('response_id', sa.BigInteger(), nullable=False),
    sa.Column('question_id', sa.BigInteger(), nullable=False),
    sa.Column('value_enc', sa.LargeBinary(), nullable=False),
    sa.Column('key_id', sa.String(length=16), nullable=False),
    sa.ForeignKeyConstraint(['question_id'], ['form_questions.id'], name=op.f('fk_form_answers_question_id_form_questions'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['response_id'], ['form_responses.id'], name=op.f('fk_form_answers_response_id_form_responses'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('response_id', 'question_id', name=op.f('pk_form_answers'))
    )
    with op.batch_alter_table('form_answers', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_form_answers_question_id'), ['question_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('form_answers', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_form_answers_question_id'))

    op.drop_table('form_answers')
    with op.batch_alter_table('form_responses', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_form_responses_user_id'))
        batch_op.drop_index('ix_form_responses_form_id_id')

    op.drop_table('form_responses')
    with op.batch_alter_table('form_questions', schema=None) as batch_op:
        batch_op.drop_index('ix_form_questions_form_id_position')

    op.drop_table('form_questions')
    with op.batch_alter_table('forms', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_forms_school_class_id'))
        batch_op.drop_index(batch_op.f('ix_forms_creator_id'))

    op.drop_table('forms')
