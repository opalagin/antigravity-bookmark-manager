from typing import Optional, List, Any
from uuid import UUID, uuid4
from datetime import datetime
from sqlmodel import Field, SQLModel, Relationship, Column, TIMESTAMP, UniqueConstraint
from pgvector.sqlalchemy import Vector
from sqlalchemy import func
from sqlalchemy.dialects.postgresql import ARRAY, VARCHAR
import os

try:
    openai_dim = int(os.getenv("OPENAI_EMBEDDING_DIMENSIONS", "1536"))
except ValueError:
    openai_dim = 1536

class Bookmark(SQLModel, table=True):
    __tablename__: Any = "bookmarks"
    __table_args__ = (UniqueConstraint("user_id", "url", name="unique_user_url"),)
    
    id: Optional[UUID] = Field(default_factory=uuid4, primary_key=True)
    user_id: str = Field(index=True)
    url: str = Field(index=True)
    title: Optional[str] = None
    content_markdown: Optional[str] = None
    tags: List[str] = Field(default=[], sa_column=Column(ARRAY(VARCHAR)))
    created_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(TIMESTAMP(timezone=True), server_default=func.now())
    )
    updated_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(TIMESTAMP(timezone=True), onupdate=func.now())
    )
    
    # Relationship
    embeddings: List["BookmarkEmbedding"] = Relationship(
        back_populates="bookmark",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )
    embeddings_openai: List["BookmarkEmbeddingOpenAI"] = Relationship(
        back_populates="bookmark",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )

class BookmarkEmbedding(SQLModel, table=True):
    __tablename__: Any = "bookmark_embeddings"
    
    id: Optional[UUID] = Field(default_factory=uuid4, primary_key=True)
    bookmark_id: UUID = Field(foreign_key="bookmarks.id")
    chunk_index: int
    chunk_text: str
    embedding: List[float] = Field(
        sa_column=Column(Vector(384))
    )  # Dimension for all-MiniLM-L6-v2
    
    # Relationship
    bookmark: Optional[Bookmark] = Relationship(back_populates="embeddings")

class BookmarkEmbeddingOpenAI(SQLModel, table=True):
    __tablename__: Any = "bookmark_embeddings_openai"
    
    id: Optional[UUID] = Field(default_factory=uuid4, primary_key=True)
    bookmark_id: UUID = Field(foreign_key="bookmarks.id")
    chunk_index: int
    chunk_text: str
    embedding: List[float] = Field(sa_column=Column(Vector(openai_dim)))
    
    # Relationship
    bookmark: Optional[Bookmark] = Relationship(back_populates="embeddings_openai")

class AllowedUser(SQLModel, table=True):
    __tablename__: Any = "allowed_users"
    
    email: str = Field(primary_key=True)
    created_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(TIMESTAMP(timezone=True), server_default=func.now())
    )


class RefreshToken(SQLModel, table=True):
    __tablename__: Any = "refresh_tokens"

    jti: UUID = Field(primary_key=True, default_factory=uuid4)
    user_sub: str = Field(index=True)
    email: str
    created_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(TIMESTAMP(timezone=True), server_default=func.now())
    )
    expires_at: datetime = Field(
        sa_column=Column(TIMESTAMP(timezone=True), nullable=False)
    )
    last_used_at: Optional[datetime] = Field(
        default=None, sa_column=Column(TIMESTAMP(timezone=True))
    )
    revoked_at: Optional[datetime] = Field(
        default=None, sa_column=Column(TIMESTAMP(timezone=True))
    )
    user_agent: Optional[str] = None

