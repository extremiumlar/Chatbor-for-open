"""TZ v2 B-3 — check_requests.sent_message_id.

Tekshiruvchiga yuborilgan xabarimizning Telegram id'si: tekshiruvchi reply
qilib javob berganda so'rovga aniq bog'lash uchun (TZ v2 6.4.5, 1-ustuvorlik).

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-12

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0004'
down_revision: Union[str, Sequence[str], None] = '0003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'check_requests', sa.Column('sent_message_id', sa.Integer(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column('check_requests', 'sent_message_id')
