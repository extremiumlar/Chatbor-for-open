"""screenshot_batches.media_ids — dublikatni RASM bo'yicha ham aniqlash

DIQQAT: autogenerate qo'shgan `drop_index('uq_cases_short_code')` +
`create_unique_constraint` juftligi QO'LDA OLIB TASHLANDI — bu o'zgarishga
aloqasi yo'q soxta farq (SQLite'da mavjud unique indeksni alembic boshqacha
ifodalagani uchun paydo bo'ladi).

Asl sarlavha: batch_media_ids

Revision ID: c8d4c7176703
Revises: 1c67e5a3a030
Create Date: 2026-08-25 11:05:46.678048

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c8d4c7176703'
down_revision: Union[str, Sequence[str], None] = '1c67e5a3a030'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # `server_default` MAJBURIY: jadvalda allaqachon qatorlar bor, standart
    # qiymatsiz NOT NULL ustun qo'shib bo'lmaydi. Eski partiyalarda media id
    # yo'q (o'shanda saqlanmagan) — ular bo'sh ro'yxat oladi va rasm
    # bo'yicha dublikat qidiruvida qatnashmaydi.
    op.add_column(
        'screenshot_batches',
        sa.Column('media_ids', sa.Text(), nullable=False, server_default='[]'),
    )


def downgrade() -> None:
    op.drop_column('screenshot_batches', 'media_ids')
