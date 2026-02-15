from fastapi import FastAPI, HTTPException, Depends, Request
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from sqlmodel import select

from pydantic import BaseModel
from typing import List, Optional
import uvicorn
from contextlib import asynccontextmanager
from sqlmodel.ext.asyncio.session import AsyncSession

from database import get_session, engine
from models import Bookmark, AllowedUser

from services import ingestion_service, search_service

# --- Pydantic Models ---

class BookmarkIngestRequest(BaseModel):
    url: str
    title: str
    content_markdown: str
    tags: List[str] = []

class BookmarkResponse(BaseModel):
    id: str
    url: str
    title: Optional[str]
    tags: List[str] = []
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

limiter = Limiter(key_func=get_remote_address)
app = FastAPI(title="Smart Bookmark Manager API", version="1.0.0", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


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

from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
security = HTTPBearer()

import requests

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    session: AsyncSession = Depends(get_session)
):

    token = credentials.credentials
    
    # 1. OPTION A: Simple Validation via Provider (Google)
    # This checks if the access token is valid and returns user info.
    # It is slower than JWT verification but requires less setup (no keys).
    try:
        response = requests.get(
            "https://www.googleapis.com/oauth2/v3/userinfo",
            headers={"Authorization": f"Bearer {token}"}
        )
        
        if response.status_code != 200:
            # Fallback for Development/Testing (Mock Auth if Token is simple string)
            if token.startswith("user_"): 
                return token # Allow mock tokens for now if they match pattern
            
            raise HTTPException(status_code=401, detail=f"Invalid Authentication Token. Status: {response.status_code}, Resp: {response.text[:100]}")
            
        user_info = response.json()
        # Use 'sub' (Subject) as the immutable unique user ID
        user_id = user_info.get("sub")
        email = user_info.get("email")

        if not user_id:
            print("Auth Error: Token missing subject ID")
            raise HTTPException(status_code=401, detail="Token missing subject ID")
            
        if not email:
            print("Auth Error: Token missing email")
            raise HTTPException(status_code=401, detail="Token missing email")

        # Pilot Mode: Check Allowlist
        try:
            stmt = select(AllowedUser).where(AllowedUser.email == email)
            result = await session.execute(stmt)
            is_allowed = result.scalar_one_or_none()
        except Exception as db_err:
             print(f"DB Error checking allowlist: {db_err}")
             # Let this propagate as 500 or handle it? 
             # For now, if DB fails, it's NOT an auth error, so re-raising as 500 is better than 401.
             raise HTTPException(status_code=500, detail="Database Error during Auth Check")
        
        if not is_allowed:
             print(f"Pilot Mode Denied: {email}")
             raise HTTPException(status_code=403, detail="Pilot Mode: Access restricted to allowed users only.")
        
        return user_id

    except HTTPException:
        raise
    except Exception as e:
         # Fallback for Development (Mock Auth)
        if token.startswith("user_"):
            return token
            
        print(f"Auth Exception: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=401, detail=f"Authentication Failed: {str(e)}")

# --- Endpoints ---

@app.get("/")
async def root():
    return {"message": "Smart Bookmark Manager API is running"}

@app.post("/bookmarks", response_model=BookmarkResponse)
@limiter.limit("10/minute")
async def ingest_bookmark(
    request: Request,
    payload: BookmarkIngestRequest,
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(get_current_user)
):
    try:
        bookmark = await ingestion_service.process_bookmark(
            session, user_id, payload.url, payload.title, payload.content_markdown, payload.tags
        )
        return BookmarkResponse(
            id=str(bookmark.id),
            url=bookmark.url,
            title=bookmark.title,
            tags=bookmark.tags,
            status="ingested"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/search", response_model=List[SearchResult])
@limiter.limit("60/minute")
async def search_bookmarks(
    request: Request,
    payload: SearchRequest,
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(get_current_user)
):
    try:
        # returns list of (BookmarkEmbedding, Bookmark) tuples
        results = await search_service.search(session, user_id, payload.query, payload.limit)
        
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
@limiter.limit("20/minute")
async def chat_bookmarks(
    request: Request,
    payload: ChatRequest,
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(get_current_user)
):
    try:
        answer, sources = await search_service.chat(session, user_id, payload.query)
        return ChatResponse(answer=answer, sources=sources)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/recent", response_model=List[BookmarkResponse])
async def get_recent_bookmarks(
    limit: int = 10,
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(get_current_user)
):
    try:
        bookmarks = await search_service.get_recent(session, user_id, limit)
        return [
            BookmarkResponse(
                id=str(b.id),
                url=b.url,
                title=b.title,
                tags=b.tags,
                status="saved"
            ) for b in bookmarks
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
