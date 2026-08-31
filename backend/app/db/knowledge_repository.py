from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db.models import KnowledgeArticleRecord, ResolvedIncidentRecord
from app.models.incident import IncidentState
from app.models.knowledge import (
    KnowledgeArticle,
    KnowledgeArticleCreate,
    KnowledgeArticleUpdate,
)


class PostgreSQLKnowledgeRepository:
    MAX_COSINE_DISTANCE = 0.45

    def __init__(self, db: Session):
        self.db = db

    def create(
        self,
        data: KnowledgeArticleCreate,
        embedding: list[float],
    ) -> KnowledgeArticle:
        existing = self.db.scalar(
            select(KnowledgeArticleRecord).where(
                KnowledgeArticleRecord.article_id
                == data.article_id
            )
        )

        if existing is not None:
            raise ValueError(
                "Knowledge article already exists."
            )

        record = KnowledgeArticleRecord(
            article_id=data.article_id,
            title=data.title,
            content=data.content,
            category=(
                data.category.value
                if data.category is not None
                else None
            ),
            subcategories=data.subcategories,
            active=True,
            embedding=embedding,
        )

        self.db.add(record)
        self.db.flush()
        self.db.refresh(record)

        return self._to_article(record)

    def get(
        self,
        article_id: str,
    ) -> KnowledgeArticle | None:
        record = self.db.scalar(
            select(KnowledgeArticleRecord).where(
                KnowledgeArticleRecord.article_id
                == article_id
            )
        )

        if record is None:
            return None

        return self._to_article(record)

    def list(
        self,
    ) -> list[KnowledgeArticle]:
        statement = (
            select(KnowledgeArticleRecord)
            .order_by(
                KnowledgeArticleRecord.article_id
            )
        )

        records = self.db.scalars(
            statement
        ).all()

        return [
            self._to_article(record)
            for record in records
        ]

    def update(
        self,
        article_id: str,
        data: KnowledgeArticleUpdate,
        embedding: list[float] | None = None,
    ) -> KnowledgeArticle | None:
        record = self.db.scalar(
            select(KnowledgeArticleRecord).where(
                KnowledgeArticleRecord.article_id
                == article_id
            )
        )

        if record is None:
            return None

        update_data = data.model_dump(
            exclude_unset=True
        )

        if "category" in update_data:
            category = update_data["category"]
            record.category = (
                category.value
                if category is not None
                else None
            )

        if "title" in update_data:
            record.title = update_data["title"]

        if "content" in update_data:
            record.content = update_data["content"]

        if "subcategories" in update_data:
            record.subcategories = update_data["subcategories"]

        if "active" in update_data:
            record.active = update_data["active"]

        if embedding is not None:
            record.embedding = embedding

        self.db.flush()
        self.db.refresh(record)

        return self._to_article(record)

    def search(
        self,
        incident: IncidentState,
        limit: int = 5,
        query_embedding: list[float] | None = None,
    ) -> list[KnowledgeArticle]:
        if query_embedding is None:
            return self._search_by_category(
                incident=incident,
                limit=limit,
            )

        article_distance = (
            KnowledgeArticleRecord.embedding.cosine_distance(
                query_embedding
            )
        )

        article_conditions = [
            KnowledgeArticleRecord.active.is_(True),
            KnowledgeArticleRecord.embedding.is_not(None),
            article_distance <= self.MAX_COSINE_DISTANCE,
        ]

        if incident.category is not None:
            article_conditions.append(
                or_(
                    KnowledgeArticleRecord.category
                    == incident.category.value,
                    KnowledgeArticleRecord.category.is_(None),
                )
            )

        article_statement = (
            select(
                KnowledgeArticleRecord,
                article_distance.label("distance"),
            )
            .where(*article_conditions)
            .order_by(article_distance)
            .limit(limit)
        )

        incident_distance = (
            ResolvedIncidentRecord.embedding.cosine_distance(
                query_embedding
            )
        )

        incident_conditions = [
            ResolvedIncidentRecord.technician_verified.is_(True),
            ResolvedIncidentRecord.embedding.is_not(None),
            incident_distance <= self.MAX_COSINE_DISTANCE,
        ]

        if incident.category is not None:
            incident_conditions.append(
                ResolvedIncidentRecord.category
                == incident.category.value
            )

        incident_statement = (
            select(
                ResolvedIncidentRecord,
                incident_distance.label("distance"),
            )
            .where(*incident_conditions)
            .order_by(incident_distance)
            .limit(limit)
        )

        ranked: list[
            tuple[float, KnowledgeArticle]
        ] = []

        for record, distance in self.db.execute(
            article_statement
        ).all():
            article = self._to_article(record).model_copy(update={
                "retrieval_similarity": max(0.0, min(1.0, 1.0 - float(distance))),
                "retrieval_method": "VECTOR",
            })
            ranked.append(
                (
                    float(distance),
                    article,
                )
            )

        for record, distance in self.db.execute(
            incident_statement
        ).all():
            article = self._resolved_incident_to_article(record).model_copy(update={
                "retrieval_similarity": max(0.0, min(1.0, 1.0 - float(distance))),
                "retrieval_method": "VECTOR",
            })
            ranked.append(
                (
                    float(distance),
                    article,
                )
            )

        ranked.sort(
            key=lambda item: item[0]
        )

        return [
            article
            for _, article in ranked[:limit]
        ]

    def _search_by_category(
        self,
        incident: IncidentState,
        limit: int,
    ) -> list[KnowledgeArticle]:
        if incident.category is None:
            return []

        category = incident.category.value

        article_statement = select(
            KnowledgeArticleRecord
        ).where(
            KnowledgeArticleRecord.active.is_(True),
            KnowledgeArticleRecord.category == category,
        )

        incident_statement = select(
            ResolvedIncidentRecord
        ).where(
            ResolvedIncidentRecord.technician_verified.is_(True),
            ResolvedIncidentRecord.category == category,
        )

        article_records = self.db.scalars(
            article_statement
        ).all()

        incident_records = self.db.scalars(
            incident_statement
        ).all()

        scored_articles: list[
            tuple[int, KnowledgeArticle]
        ] = []

        for record in article_records:
            score = 1

            if (
                incident.subcategory is not None
                and incident.subcategory
                in record.subcategories
            ):
                score += 2

            scored_articles.append(
                (
                    score,
                    self._to_article(record).model_copy(update={
                        "retrieval_method": "CATEGORY",
                    }),
                )
            )

        for record in incident_records:
            score = 1

            if (
                incident.subcategory is not None
                and record.subcategory
                == incident.subcategory
            ):
                score += 2

            scored_articles.append(
                (
                    score,
                    self._resolved_incident_to_article(record).model_copy(update={
                        "retrieval_method": "CATEGORY",
                    }),
                )
            )

        scored_articles.sort(
            key=lambda item: item[0],
            reverse=True,
        )

        return [
            article
            for _, article in scored_articles[:limit]
        ]

    @staticmethod
    def _resolved_incident_to_article(
        record: ResolvedIncidentRecord,
    ) -> KnowledgeArticle:
        content_parts = [
            f"Problem: {record.summary}",
        ]

        if record.error_message is not None:
            content_parts.append(
                f"Error: {record.error_message}"
            )

        content_parts.append(
            f"Verified resolution: {record.resolution}"
        )

        return KnowledgeArticle(
            article_id=(
                f"INCIDENT-{record.incident_id}"
            ),
            title="Verified resolved incident",
            content="\n".join(content_parts),
            category=record.category,
            subcategories=(
                [record.subcategory]
                if record.subcategory is not None
                else []
            ),
        )

    @staticmethod
    def _to_article(
        record: KnowledgeArticleRecord,
    ) -> KnowledgeArticle:
        return KnowledgeArticle(
            article_id=record.article_id,
            title=record.title,
            content=record.content,
            category=record.category,
            subcategories=record.subcategories,
            active=record.active,
        )
