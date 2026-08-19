"""admin identity: tg_username, full_name

Revision ID: 3c8a5dd5f8d5
Revises: 0004
Create Date: 2026-08-16 10:37:49.495167

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3c8a5dd5f8d5'
down_revision: Union[str, Sequence[str], None] = '0004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Adminlar ro'yxatida "kim kimligi" ko'rinishi uchun ism/username.

    Eslatma: autogenerate bu yerga `cases.short_code` indeksiga tegadigan
    ikkita qatorni ham qo'shgan edi — ular OLIB TASHLANDI. Bu SQLite
    reflection shovqini (mavjud unique indeks nomini "o'zgargan" deb
    ko'rsatadi); qo'llansa, ishlab turgan indeks o'chirilib qayta
    yaratilardi. Bu migratsiyaning maqsadiga aloqasi yo'q.
    """
    op.add_column('admins', sa.Column('tg_username', sa.String(length=255), nullable=True))
    op.add_column('admins', sa.Column('full_name', sa.String(length=255), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('admins', 'full_name')
    op.drop_column('admins', 'tg_username')
