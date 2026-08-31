from alembic import op
import pgvector.sqlalchemy
import sqlalchemy as sa


revision: str = 'e13280f9c6bd'
down_revision: str | None = None
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute('CREATE EXTENSION IF NOT EXISTS vector')
    op.create_table('chat_requests',
    sa.Column('request_id', sa.String(length=36), nullable=False),
    sa.Column('owner_id', sa.String(length=100), nullable=False),
    sa.Column('original_conversation_id', sa.String(length=100), nullable=True),
    sa.Column('response', sa.JSON(), nullable=True),
    sa.PrimaryKeyConstraint('request_id')
    )
    op.create_table('conversations',
    sa.Column('owner_id', sa.String(length=100), nullable=False),
    sa.Column('security_emergency', sa.Boolean(), nullable=False),
    sa.Column('id', sa.String(length=100), nullable=False),
    sa.Column('stage', sa.String(length=50), nullable=False),
    sa.Column('incident_state', sa.JSON(), nullable=False),
    sa.Column('diagnostic_state', sa.JSON(), nullable=False),
    sa.Column('resolution_state', sa.JSON(), nullable=False),
    sa.Column('last_question', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_conversations_owner_id'), 'conversations', ['owner_id'], unique=False)
    op.create_table('knowledge_articles',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('article_id', sa.String(length=100), nullable=False),
    sa.Column('title', sa.String(length=255), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('category', sa.String(length=50), nullable=True),
    sa.Column('subcategories', sa.JSON(), nullable=False),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.Column('embedding', pgvector.sqlalchemy.vector.VECTOR(dim=768), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_knowledge_articles_article_id'), 'knowledge_articles', ['article_id'], unique=True)
    op.create_index(op.f('ix_knowledge_articles_category'), 'knowledge_articles', ['category'], unique=False)
    op.create_table('messages',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('conversation_id', sa.String(length=100), nullable=False),
    sa.Column('role', sa.String(length=20), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_messages_conversation_id'), 'messages', ['conversation_id'], unique=False)
    op.create_table('resolved_incidents',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('incident_id', sa.String(length=100), nullable=False),
    sa.Column('conversation_id', sa.String(length=100), nullable=False),
    sa.Column('category', sa.String(length=50), nullable=False),
    sa.Column('subcategory', sa.String(length=100), nullable=True),
    sa.Column('summary', sa.Text(), nullable=False),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.Column('resolution', sa.Text(), nullable=False),
    sa.Column('technician_verified', sa.Boolean(), nullable=False),
    sa.Column('embedding', pgvector.sqlalchemy.vector.VECTOR(dim=768), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_resolved_incidents_category'), 'resolved_incidents', ['category'], unique=False)
    op.create_index(op.f('ix_resolved_incidents_conversation_id'), 'resolved_incidents', ['conversation_id'], unique=False)
    op.create_index(op.f('ix_resolved_incidents_incident_id'), 'resolved_incidents', ['incident_id'], unique=True)
    op.create_index(op.f('ix_resolved_incidents_subcategory'), 'resolved_incidents', ['subcategory'], unique=False)
    op.create_index(op.f('ix_resolved_incidents_technician_verified'), 'resolved_incidents', ['technician_verified'], unique=False)
    op.create_table('tickets',
    sa.Column('diagnostic_state', sa.JSON(), nullable=False),
    sa.Column('routing', sa.JSON(), nullable=False),
    sa.Column('ticket_id', sa.String(length=100), nullable=False),
    sa.Column('conversation_id', sa.String(length=100), nullable=False),
    sa.Column('incident_state', sa.JSON(), nullable=False),
    sa.Column('resolution_attempts', sa.JSON(), nullable=False),
    sa.Column('escalation_reason', sa.Text(), nullable=False),
    sa.Column('status', sa.String(length=50), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('ticket_id')
    )
    op.create_index(op.f('ix_tickets_conversation_id'), 'tickets', ['conversation_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_tickets_conversation_id'), table_name='tickets')
    op.drop_table('tickets')
    op.drop_index(op.f('ix_resolved_incidents_technician_verified'), table_name='resolved_incidents')
    op.drop_index(op.f('ix_resolved_incidents_subcategory'), table_name='resolved_incidents')
    op.drop_index(op.f('ix_resolved_incidents_incident_id'), table_name='resolved_incidents')
    op.drop_index(op.f('ix_resolved_incidents_conversation_id'), table_name='resolved_incidents')
    op.drop_index(op.f('ix_resolved_incidents_category'), table_name='resolved_incidents')
    op.drop_table('resolved_incidents')
    op.drop_index(op.f('ix_messages_conversation_id'), table_name='messages')
    op.drop_table('messages')
    op.drop_index(op.f('ix_knowledge_articles_category'), table_name='knowledge_articles')
    op.drop_index(op.f('ix_knowledge_articles_article_id'), table_name='knowledge_articles')
    op.drop_table('knowledge_articles')
    op.drop_index(op.f('ix_conversations_owner_id'), table_name='conversations')
    op.drop_table('conversations')
    op.drop_table('chat_requests')
