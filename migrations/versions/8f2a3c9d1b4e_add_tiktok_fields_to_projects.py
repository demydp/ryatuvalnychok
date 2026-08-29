"""add tiktok fields to projects

Revision ID: 8f2a3c9d1b4e
Revises: 4534e7ff60ea
Create Date: 2026-08-29 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
import app.models


# revision identifiers, used by Alembic.
revision = '8f2a3c9d1b4e'
down_revision = '4534e7ff60ea'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('projects', schema=None) as batch_op:
        batch_op.add_column(sa.Column('tiktok_access_token', app.models.EncryptedText(), nullable=True))
        batch_op.add_column(sa.Column('tiktok_refresh_token', app.models.EncryptedText(), nullable=True))
        batch_op.add_column(sa.Column('tiktok_open_id', sa.String(length=128), nullable=True))
        batch_op.add_column(sa.Column('tiktok_username', sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column('tiktok_display_name', sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column('tiktok_avatar_url', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('tiktok_token_obtained_at', sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column('tiktok_access_token_expires_at', sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column('tiktok_refresh_token_expires_at', sa.String(length=64), nullable=True))


def downgrade():
    with op.batch_alter_table('projects', schema=None) as batch_op:
        batch_op.drop_column('tiktok_refresh_token_expires_at')
        batch_op.drop_column('tiktok_access_token_expires_at')
        batch_op.drop_column('tiktok_token_obtained_at')
        batch_op.drop_column('tiktok_avatar_url')
        batch_op.drop_column('tiktok_display_name')
        batch_op.drop_column('tiktok_username')
        batch_op.drop_column('tiktok_open_id')
        batch_op.drop_column('tiktok_refresh_token')
        batch_op.drop_column('tiktok_access_token')
