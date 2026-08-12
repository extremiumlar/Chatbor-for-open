"""TZ v2 (Qo'lda Admin Oqimi) — B-1 poydevor jadvallari.

Yangi jadvallar: admin_sessions, screenshot_batches, check_requests,
scheduled_jobs. Mavjudlarga qo'shimcha: admins.is_active,
admins.can_view_all_stats, cases.short_code/coupon/coupon_at.

CaseStatus ustunlari native_enum=False (oddiy VARCHAR) bo'lgani uchun yangi
v2 status qiymatlari (SCREENSHOTS_SENT, CHECK_QUEUED, ...) uchun ALTER
kerak emas — ular shunchaki yangi satr qiymatlari.

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-12

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0003'
down_revision: Union[str, Sequence[str], None] = '0002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'admins',
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        'admins',
        sa.Column('can_view_all_stats', sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    op.add_column('cases', sa.Column('short_code', sa.String(length=16), nullable=True))
    # SQLite ALTER orqali constraint qo'sha olmaydi — unique INDEX bir xil
    # kafolatni beradi va ALTERsiz ishlaydi.
    op.create_index('uq_cases_short_code', 'cases', ['short_code'], unique=True)
    op.add_column('cases', sa.Column('coupon', sa.String(length=16), nullable=True))
    op.add_column('cases', sa.Column('coupon_at', sa.DateTime(), nullable=True))

    op.create_table(
        'admin_sessions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('admin_id', sa.Integer(), nullable=False),
        sa.Column('session_name', sa.String(length=255), nullable=False),
        sa.Column('phone', sa.String(length=32), nullable=False),
        sa.Column(
            'status',
            sa.Enum('CONNECTED', 'DISCONNECTED', 'AUTH_LOST', name='sessionstatus', native_enum=False, length=16),
            nullable=False,
            server_default='DISCONNECTED',
        ),
        sa.Column('last_seen_at', sa.DateTime(), nullable=True),
        sa.Column('last_error', sa.String(length=500), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.ForeignKeyConstraint(['admin_id'], ['admins.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('admin_id'),
        sa.UniqueConstraint('session_name'),
    )

    op.create_table(
        'screenshot_batches',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('case_id', sa.Integer(), nullable=False),
        sa.Column('admin_id', sa.Integer(), nullable=False),
        sa.Column('phone', sa.String(length=32), nullable=False),
        sa.Column('image_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('file_ids', sa.Text(), nullable=False, server_default='[]'),
        sa.Column('group_chat_id', sa.Integer(), nullable=True),
        sa.Column('group_message_id', sa.Integer(), nullable=True),
        sa.Column('is_duplicate', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('duplicate_of_batch_id', sa.Integer(), nullable=True),
        sa.Column('sent_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column(
            'outcome',
            sa.Enum('PENDING', 'PASSED', 'FAILED', 'UNKNOWN', 'STALLED', name='batchoutcome', native_enum=False, length=16),
            nullable=False,
            server_default='PENDING',
        ),
        sa.Column(
            'outcome_source',
            sa.Enum('AUTO', 'MANUAL', name='outcomesource', native_enum=False, length=16),
            nullable=False,
            server_default='AUTO',
        ),
        sa.Column('reacted_by', sa.Integer(), nullable=True),
        sa.Column('reacted_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['admin_id'], ['admins.id'], ),
        sa.ForeignKeyConstraint(['case_id'], ['cases.id'], ),
        sa.ForeignKeyConstraint(['duplicate_of_batch_id'], ['screenshot_batches.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table(
        'check_requests',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('case_id', sa.Integer(), nullable=False),
        sa.Column('phone', sa.String(length=32), nullable=False),
        sa.Column('requested_by_admin_id', sa.Integer(), nullable=False),
        sa.Column(
            'trigger',
            sa.Enum('MANUAL', 'AUTO', name='checktrigger', native_enum=False, length=16),
            nullable=False,
        ),
        sa.Column('is_recheck', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('queued_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('sent_at', sa.DateTime(), nullable=True),
        sa.Column('replied_at', sa.DateTime(), nullable=True),
        sa.Column(
            'result',
            sa.Enum('PASSED', 'FAILED', 'UNRECOGNIZED', 'NO_REPLY', name='checkresult', native_enum=False, length=16),
            nullable=True,
        ),
        sa.Column('raw_reply', sa.Text(), nullable=False, server_default=''),
        sa.Column('late_corrected', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('customer_notified_at', sa.DateTime(), nullable=True),
        sa.Column(
            'notified_by',
            sa.Enum('AUTO', 'ADMIN', name='notifiedby', native_enum=False, length=16),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(['case_id'], ['cases.id'], ),
        sa.ForeignKeyConstraint(['requested_by_admin_id'], ['admins.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table(
        'scheduled_jobs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column(
            'kind',
            sa.Enum('CHECK_DUE', 'REMIND_NO_SCREENSHOT', 'STALLED_ALERT', 'DAILY_REPORT', name='jobkind', native_enum=False, length=32),
            nullable=False,
        ),
        sa.Column('case_id', sa.Integer(), nullable=True),
        sa.Column('due_at', sa.DateTime(), nullable=False),
        sa.Column('payload', sa.Text(), nullable=False, server_default='{}'),
        sa.Column('done_at', sa.DateTime(), nullable=True),
        sa.Column('attempts', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.ForeignKeyConstraint(['case_id'], ['cases.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_scheduled_jobs_due_at', 'scheduled_jobs', ['due_at'])


def downgrade() -> None:
    op.drop_index('ix_scheduled_jobs_due_at', table_name='scheduled_jobs')
    op.drop_table('scheduled_jobs')
    op.drop_table('check_requests')
    op.drop_table('screenshot_batches')
    op.drop_table('admin_sessions')
    op.drop_index('uq_cases_short_code', table_name='cases')
    op.drop_column('cases', 'coupon_at')
    op.drop_column('cases', 'coupon')
    op.drop_column('cases', 'short_code')
    op.drop_column('admins', 'can_view_all_stats')
    op.drop_column('admins', 'is_active')
