"""audit K-4/J-8/J-4/J-7: admin role, bot force_release_requested, relay_log

Bu sessiyada (audit topilmalarini bartaraf etish) qo'shilgan uch narsa:
- `admins.role` (K-4/J-8 — TZ 14-bo'lim rol tizimi)
- `bots.force_release_requested` (J-4 — "Majburan bo'shatish" endi
  jarayonlar-aro to'g'ri ishlaydigan bayroq orqali)
- `relay_log` jadvali (J-7 — TZ 11.5 "har bir uzatish izi")

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-30

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0002'
down_revision: Union[str, Sequence[str], None] = '0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'admins',
        sa.Column(
            'role',
            sa.Enum('OWNER', 'ROP', 'DASTURCHI', 'ADMIN', 'KUZATUVCHI', name='adminrole', native_enum=False, length=16),
            nullable=False,
            server_default='ADMIN',
        ),
    )
    op.add_column(
        'bots',
        sa.Column('force_release_requested', sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_table(
        'relay_log',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('case_id', sa.Integer(), nullable=True),
        sa.Column('bot_id', sa.Integer(), nullable=True),
        sa.Column('direction', sa.Enum('TO_BOT', 'FROM_BOT', name='relaydirection', native_enum=False, length=16), nullable=False),
        sa.Column('payload', sa.String(length=2000), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.ForeignKeyConstraint(['bot_id'], ['bots.id'], ),
        sa.ForeignKeyConstraint(['case_id'], ['cases.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade() -> None:
    op.drop_table('relay_log')
    op.drop_column('bots', 'force_release_requested')
    op.drop_column('admins', 'role')
