from pydantic import BaseModel, Field

from app.models.incident import Category


class KnowledgeArticle(BaseModel):
    article_id: str
    title: str
    content: str
    category: Category | None = None
    subcategories: list[str] = Field(default_factory=list)
    active: bool = True
    retrieval_similarity: float | None = Field(default=None, ge=0.0, le=1.0)
    retrieval_method: str | None = None


class KnowledgeArticleCreate(BaseModel):
    article_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    content: str = Field(min_length=1)
    category: Category | None = None
    subcategories: list[str] = Field(default_factory=list)


class KnowledgeArticleUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1)
    content: str | None = Field(default=None, min_length=1)
    category: Category | None = None
    subcategories: list[str] | None = None
    active: bool | None = None
