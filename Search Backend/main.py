from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel
from typing import List, Optional
import uvicorn
from contextlib import asynccontextmanager
from sqlmodel.ext.asyncio.session import AsyncSession

from database import get_session, engine
from models import Bookmark
from services import ingestion_service, search_service

# --- Pydantic Models ---

class BookmarkIngestRequest(BaseModel):
    url: str
    title: str
    content_markdown: str

class BookmarkResponse(BaseModel):
    id: str
    url: str
    title: Optional[str]
    status: str = "processed"

class SearchRequest(BaseModel):
    query: str
    limit: int = 5

class SearchResult(BaseModel):
    id: str
    url: str
    title: Optional[str]
    score: float # Distance usually, so lower is better for L2, higher for Cos/Inner if converted.
class ChatRequest(BaseModel):
    query: str

class ChatResponse(BaseModel):
    answer: str
    sources: List[str]

# ... existing code ...



@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Ensure engine is ready
    yield
    # Shutdown
    await engine.dispose()

from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Smart Bookmark Manager API", version="1.0.0", lifespan=lifespan)

# --- CORS Configuration ---
# Allow all origins for local development/extensions
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Endpoints ---

@app.get("/")
async def root():
    return {"message": "Smart Bookmark Manager API is running"}

@app.post("/bookmarks", response_model=BookmarkResponse)
async def ingest_bookmark(
    request: BookmarkIngestRequest,
    session: AsyncSession = Depends(get_session)
):
    try:
        bookmark = await ingestion_service.process_bookmark(
            session, request.url, request.title, request.content_markdown
        )
        return BookmarkResponse(
            id=str(bookmark.id),
            url=bookmark.url,
            title=bookmark.title,
            status="ingested"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/recent", response_model=List[BookmarkResponse])
async def get_recent_bookmarks(
    limit: int = 10,
    session: AsyncSession = Depends(get_session)
):
    try:
        bookmarks = await search_service.get_recent(session, limit)
        return [
            BookmarkResponse(
                id=str(b.id),
                url=b.url,
                title=b.title,
                status="saved"
            ) for b in bookmarks
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/search", response_model=List[SearchResult])
async def search_bookmarks(
    request: SearchRequest,
    session: AsyncSession = Depends(get_session)
):
    try:
        # returns list of (BookmarkEmbedding, Bookmark) tuples
        results = await search_service.search(session, request.query, request.limit)
        
        response_list = []
        for embedding_entry, bookmark in results:
            response_list.append(SearchResult(
                id=str(bookmark.id),
                url=bookmark.url,
                title=bookmark.title,
                score=0.0, # Not easily available without extra selection, but sorting is correct
                text=embedding_entry.chunk_text
            ))
            
        return response_list

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/chat", response_model=ChatResponse)
async def chat_bookmarks(
    request: ChatRequest,
    session: AsyncSession = Depends(get_session)
):
    try:
        answer, sources = await search_service.chat(session, request.query)
        return ChatResponse(answer=answer, sources=sources)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
