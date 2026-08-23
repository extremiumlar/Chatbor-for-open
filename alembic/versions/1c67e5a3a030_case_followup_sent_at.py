"""cases.followup_sent_at — §5.3 matni mijozga yuborilgan vaqti

Nega kerak: matn case boshiga bir marta ketishi kerak, lekin "bir marta"ni
partiya soniga qarab hisoblash noto'g'ri edi. Birinchi partiya soya
rejimida tashlansa matn to'siladi, keyingilari esa "birinchi emas" deb jim
qoladi va mijoz matnni umuman olmaydi (jonli sinovda aynan shu bo'ldi).
Endi YUBORILGAN vaqt saqlanadi.

DIQQAT: autogenerate qo'shgan `drop_index('uq_cases_short_code')` +
`create_unique_constraint` juftligi QO'LDA OLIB TASHLANDI. Ular bu
o'zgarishga aloqasi yo'q — SQLite'da mavjud unique indeksni alembic
boshqacha ifodalagani uchun paydo bo'ladigan soxta farq. Bajarilsa
`short_code` indeksi keraksiz qayta qurilardi.

Revision ID: 1c67e5a3a030
Revises: 3c8a5dd5f8d5
Create Date: 2026-08-23 16:41:25.789826

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1c67e5a3a030'
down_revision: Union[str, Sequence[str], None] = '3c8a5dd5f8d5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('cases', sa.Column('followup_sent_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column('cases', 'followup_sent_at')
