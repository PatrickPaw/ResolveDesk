from app.api.access import require_admin
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.ai.ollama_provider import OllamaProvider
from app.core.config import settings
from app.db.database import get_db
from app.db.knowledge_repository import PostgreSQLKnowledgeRepository
from app.models.knowledge import (
    KnowledgeArticle,
    KnowledgeArticleCreate,
    KnowledgeArticleUpdate,
)


router = APIRouter(
    dependencies=[Depends(require_admin)],
    prefix="/knowledge",
    tags=["Knowledge Base"],
)

ai_provider = OllamaProvider(
    model=settings.ollama_model,
    embedding_model=settings.ollama_embedding_model,
)


def build_embedding_text(
    title: str,
    content: str,
    category: str | None,
    subcategories: list[str],
) -> str:
    parts = [
        f"Title: {title}",
        f"Content: {content}",
    ]

    if category is not None:
        parts.append(
            f"Category: {category}"
        )

    if subcategories:
        parts.append(
            f"Subcategories: {', '.join(subcategories)}"
        )

    return "\n".join(parts)


@router.post(
    "",
    response_model=KnowledgeArticle,
    status_code=status.HTTP_201_CREATED,
)
def create_article(
    data: KnowledgeArticleCreate,
    db: Session = Depends(get_db),
):
    repository = PostgreSQLKnowledgeRepository(db)

    embedding_text = build_embedding_text(
        title=data.title,
        content=data.content,
        category=(
            data.category.value
            if data.category is not None
            else None
        ),
        subcategories=data.subcategories,
    )

    embedding = ai_provider.embed_document(
        embedding_text
    )

    try:
        return repository.create(
            data=data,
            embedding=embedding,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc


@router.get(
    "",
    response_model=list[KnowledgeArticle],
)
def list_articles(
    db: Session = Depends(get_db),
):
    repository = PostgreSQLKnowledgeRepository(db)
    return repository.list()


@router.get(
    "/{article_id}",
    response_model=KnowledgeArticle,
)
def get_article(
    article_id: str,
    db: Session = Depends(get_db),
):
    repository = PostgreSQLKnowledgeRepository(db)

    article = repository.get(article_id)

    if article is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Knowledge article not found.",
        )

    return article


@router.patch(
    "/{article_id}",
    response_model=KnowledgeArticle,
)
def update_article(
    article_id: str,
    data: KnowledgeArticleUpdate,
    db: Session = Depends(get_db),
):
    repository = PostgreSQLKnowledgeRepository(db)

    current = repository.get(article_id)

    if current is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Knowledge article not found.",
        )

    update_data = data.model_dump(
        exclude_unset=True
    )

    embedding_fields = {
        "title",
        "content",
        "category",
        "subcategories",
    }

    embedding = None

    if embedding_fields.intersection(
        update_data.keys()
    ):
        title = (
            data.title
            if "title" in update_data
            else current.title
        )

        content = (
            data.content
            if "content" in update_data
            else current.content
        )

        category = (
            data.category
            if "category" in update_data
            else current.category
        )

        subcategories = (
            data.subcategories
            if "subcategories" in update_data
            else current.subcategories
        )

        embedding_text = build_embedding_text(
            title=title,
            content=content,
            category=(
                category.value
                if category is not None
                else None
            ),
            subcategories=subcategories,
        )

        embedding = ai_provider.embed_document(
            embedding_text
        )

    article = repository.update(
        article_id=article_id,
        data=data,
        embedding=embedding,
    )

    if article is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Knowledge article not found.",
        )

    return article