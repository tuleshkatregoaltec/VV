"""Persist authorized broker documents, approved media and explicit action proposals.

Revision ID: c7a941ef2b30
Revises: a34d19c0b621
"""
from alembic import op
import sqlalchemy as sa

revision = 'c7a941ef2b30'
down_revision = 'a34d19c0b621'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('crm_broker_documents',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('organization_id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('enquiry_id', sa.Integer(), sa.ForeignKey('crm_inbound_enquiries.id'), nullable=False),
        sa.Column('scope', sa.String(), nullable=False),
        sa.Column('kind', sa.String(), nullable=False),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('idempotency_key', sa.String(), nullable=False),
        sa.Column('input_hash', sa.String(), nullable=False),
        sa.Column('document_json', sa.JSON(), nullable=False),
        sa.Column('attempt_count', sa.Integer(), nullable=False),
        sa.Column('lease_until', sa.DateTime(timezone=True)),
        sa.Column('claim_token', sa.String()),
        sa.Column('object_key', sa.String()),
        sa.Column('sha256', sa.String()),
        sa.Column('error', sa.String()),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('organization_id', 'user_id', 'idempotency_key', name='uq_broker_document_request'))
    for column in ('organization_id', 'user_id', 'enquiry_id', 'status'):
        op.create_index(f'ix_crm_broker_documents_{column}', 'crm_broker_documents', [column])
    op.create_table('crm_broker_media',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('organization_id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('enquiry_id', sa.Integer(), sa.ForeignKey('crm_inbound_enquiries.id'), nullable=False),
        sa.Column('match_id', sa.Integer(), sa.ForeignKey('crm_inbound_matches.id'), nullable=False),
        sa.Column('kind', sa.String(), nullable=False),
        sa.Column('object_key', sa.String(), nullable=False),
        sa.Column('sha256', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False))
    for column in ('organization_id', 'enquiry_id', 'match_id'):
        op.create_index(f'ix_crm_broker_media_{column}', 'crm_broker_media', [column])
    op.create_table('crm_broker_actions',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('organization_id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('enquiry_id', sa.Integer(), sa.ForeignKey('crm_inbound_enquiries.id', ondelete='CASCADE'), nullable=False),
        sa.Column('scope', sa.String(), nullable=False),
        sa.Column('kind', sa.String(), nullable=False),
        sa.Column('body', sa.Text()),
        sa.Column('next_follow_up', sa.Date()),
        sa.Column('expected_updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True)))
    for column in ('organization_id', 'user_id', 'enquiry_id'):
        op.create_index(f'ix_crm_broker_actions_{column}', 'crm_broker_actions', [column])


def downgrade():
    op.drop_table('crm_broker_actions')
    op.drop_table('crm_broker_media')
    op.drop_table('crm_broker_documents')
