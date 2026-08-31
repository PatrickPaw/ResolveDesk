from datetime import datetime, timezone

from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class ConversationRecord(Base):
    __tablename__ = "conversations"
    owner_id: Mapped[str] = mapped_column(String(100), nullable=False, default="local-demo", index=True)

    security_emergency: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    id: Mapped[str] = mapped_column(
        String(100),
        primary_key=True,
    )

    stage: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    incident_state: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )

    diagnostic_state: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )

    resolution_state: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )

    last_question: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class MessageRecord(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
    )

    conversation_id: Mapped[str] = mapped_column(
        ForeignKey(
            "conversations.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    role: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )

    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class TicketRecord(Base):
    __tablename__ = "tickets"

    diagnostic_state: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    routing: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    ticket_id: Mapped[str] = mapped_column(
        String(100),
        primary_key=True,
    )

    conversation_id: Mapped[str] = mapped_column(
        ForeignKey(
            "conversations.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    incident_state: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
    )

    resolution_attempts: Mapped[list] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )

    escalation_reason: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class KnowledgeArticleRecord(Base):
    __tablename__ = "knowledge_articles"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
    )

    article_id: Mapped[str] = mapped_column(
        String(100),
        unique=True,
        nullable=False,
        index=True,
    )

    title: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    category: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
        index=True,
    )

    subcategories: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )

    active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
    )

    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(768),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class ResolvedIncidentRecord(Base):
    __tablename__ = "resolved_incidents"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
    )

    incident_id: Mapped[str] = mapped_column(
        String(100),
        unique=True,
        nullable=False,
        index=True,
    )

    conversation_id: Mapped[str] = mapped_column(
        ForeignKey(
            "conversations.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    category: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
    )

    subcategory: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        index=True,
    )

    summary: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    error_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    resolution: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    technician_verified: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        index=True,
    )

    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(768),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class ChatRequestRecord(Base):
    __tablename__ = "chat_requests"
    request_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(100), nullable=False)
    original_conversation_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    response: Mapped[dict | None] = mapped_column(JSON, nullable=True)
