from typing import Optional, List
from uuid import UUID, uuid4
from datetime import datetime
from sqlmodel import Field, SQLModel, Relationship, Column, TIMESTAMP
from pgvector.sqlalchemy import Vector
from sqlalchemy import func

class Bookmark(SQLModel, table=True):
    __tablename__ = "bookmarks"
    
    id: Optional[UUID] = Field(default_factory=uuid4, primary_key=True)
    url: str = Field(unique=True, index=True)
    title: Optional[str] = None
    content_markdown: Optional[str] = None
    created_at: Optional[datetime] = Field(
        sa_column=Column(TIMESTAMP(timezone=True), server_default=func.now())
    )
    
    # Relationship
    embeddings: List["BookmarkEmbedding"] = Relationship(back_populates="bookmark")

class BookmarkEmbedding(SQLModel, table=True):
    __tablename__ = "bookmark_embeddings"
    
    id: Optional[UUID] = Field(default_factory=uuid4, primary_key=True)
    bookmark_id: UUID = Field(foreign_key="bookmarks.id")
    chunk_index: int
    chunk_text: str
    embedding: List[float] = Field(sa_column=Column(Vector(384))) # Dimension for all-MiniLM-L6-v2
    
    # Relationship
    bookmark: Optional[Bookmark] = Relationship(back_populates="embeddings")
