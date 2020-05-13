"""empty message

Revision ID: 1a8c89b722e2
Revises: 54a3fc54a2cf
Create Date: 2020-05-05 20:41:17.407032

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '1a8c89b722e2'
down_revision = '54a3fc54a2cf'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('registration_bootstrap',
    sa.Column('identifier', sa.String(length=10), nullable=False),
    sa.Column('account', sa.Integer(), nullable=True),
    sa.Column('last_modified', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('identifier')
    )
    op.create_index(op.f('ix_registration_bootstrap_account'), 'registration_bootstrap', ['account'], unique=False)
    op.add_column('filings', sa.Column('temp_reg', sa.String(length=10), nullable=True))
    op.create_foreign_key(None, 'filings', 'registration_bootstrap', ['temp_reg'], ['identifier'])
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_constraint(None, 'filings', type_='foreignkey')
    op.drop_column('filings', 'temp_reg')
    op.drop_index(op.f('ix_registration_bootstrap_account'), table_name='registration_bootstrap')
    op.drop_table('registration_bootstrap')
    # ### end Alembic commands ###
