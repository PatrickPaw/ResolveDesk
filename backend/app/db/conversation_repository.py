from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ConversationRecord, MessageRecord
from app.models.conversation import (
    ConversationStage,
    ConversationState,
    DiagnosticState,
)
from app.models.incident import IncidentState
from app.models.resolution import ResolutionState


class PostgreSQLConversationRepository:
    def __init__(self, db: Session, owner_id: str = "local-demo", admin: bool = True):
        self.db = db
        self.owner_id = owner_id
        self.admin = admin

    def create(self) -> ConversationState:
        conversation = ConversationState(
            conversation_id=str(uuid4())
        )

        record = ConversationRecord(
            owner_id=self.owner_id,
            id=conversation.conversation_id,
            stage=conversation.stage.value,
            incident_state=conversation.incident.model_dump(
                mode="json"
            ),
            diagnostic_state=conversation.diagnostic.model_dump(
                mode="json"
            ),
            resolution_state=conversation.resolution.model_dump(
                mode="json"
            ),
            last_question=conversation.last_question,
            security_emergency=conversation.security_emergency,
        )

        self.db.add(record)
        self.db.flush()

        return conversation

    def get(
        self,
        conversation_id: str,
        for_update: bool = False,
    ) -> ConversationState | None:
        statement = select(ConversationRecord).where(ConversationRecord.id == conversation_id)
        if not self.admin:
            statement = statement.where(ConversationRecord.owner_id == self.owner_id)
        if for_update:
            statement = statement.with_for_update()
        record = self.db.scalar(statement)

        if record is None:
            return None

        return ConversationState(
            conversation_id=record.id,
            stage=ConversationStage(record.stage),
            incident=IncidentState.model_validate(
                record.incident_state
            ),
            diagnostic=DiagnosticState.model_validate(
                record.diagnostic_state
            ),
            resolution=ResolutionState.model_validate(
                record.resolution_state
            ),
            last_question=record.last_question,
            security_emergency=record.security_emergency,
        )

    def save(
        self,
        conversation: ConversationState,
    ) -> None:
        record = self.db.get(
            ConversationRecord,
            conversation.conversation_id,
        )

        if record is None:
            raise ValueError(
                "Conversation does not exist."
            )

        record.stage = conversation.stage.value
        record.incident_state = conversation.incident.model_dump(
            mode="json"
        )
        record.diagnostic_state = conversation.diagnostic.model_dump(
            mode="json"
        )
        record.resolution_state = conversation.resolution.model_dump(
            mode="json"
        )
        record.last_question = conversation.last_question
        record.security_emergency = conversation.security_emergency

        self.db.flush()

    def add_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
    ) -> int:
        message = MessageRecord(
            conversation_id=conversation_id,
            role=role,
            content=content,
        )

        self.db.add(message)
        self.db.flush()
        return message.id

    def get_messages(
        self,
        conversation_id: str,
    ) -> list[MessageRecord]:
        statement = (
            select(MessageRecord)
            .where(
                MessageRecord.conversation_id
                == conversation_id
            )
            .order_by(
                MessageRecord.created_at,
                MessageRecord.id,
            )
        )

        return list(
            self.db.scalars(statement).all()
        )
