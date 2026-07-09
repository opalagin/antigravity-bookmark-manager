from fastapi import FastAPI, HTTPException, Depends, Request, BackgroundTasks, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from sqlalchemy import text
from sqlmodel import select

from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime
import uvicorn
import httpx
from contextlib import asynccontextmanager
from sqlmodel.ext.asyncio.session import AsyncSession
from uuid import UUID, uuid4
from datetime import timedelta, timezone
import jwt

from database import get_session, engine
from models import AllowedUser, RefreshToken, openai_dim
import auth
import settings

from services import ingestion_service, search_service, management_service
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
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    content_markdown: Optional[str] = None

class BookmarkUpdateRequest(BaseModel):
    title: Optional[str] = None
    tags: Optional[List[str]] = None

class BulkTagUpdateRequest(BaseModel):
    old_prefix: str
    new_prefix: str

class BulkDeleteRequest(BaseModel):
    bookmark_ids: List[str]

class BulkAddRemoveTagRequest(BaseModel):
    bookmark_ids: List[str]
    tag: str

class PaginatedBookmarksResponse(BaseModel):
    items: List[BookmarkResponse]
    total: int
    skip: int
    limit: int

class TagCount(BaseModel):
    tag: str
    count: int

class BulkUpdateResponse(BaseModel):
    updated_count: int

class BulkDeleteResponse(BaseModel):
    deleted_count: int

class SearchRequest(BaseModel):
    query: str
    limit: int = 5

class SearchResult(BaseModel):
    id: str
    url: str
    title: Optional[str]
    score: float  # Cosine distance — lower is closer
    text: Optional[str] = None

class ChatRequest(BaseModel):
    query: str

class ChatResponse(BaseModel):
    answer: str
    sources: List[str]


class GoogleAuthRequest(BaseModel):
    google_access_token: str


class RefreshTokenRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str



@asynccontextmanager
async def lifespan(app: FastAPI):
    # Fail-fast check for JWT secret in production
    if settings.ENVIRONMENT == "production":
        if not settings.JWT_SECRET or len(settings.JWT_SECRET) < 32:
            raise ValueError(
                "JWT_SECRET must be set and at least 32 bytes in production"
            )

    app.state.http = httpx.AsyncClient(timeout=10.0)

    # Startup: Idempotently initialize the database schema.
    # Works on Railway managed Postgres and local Docker Compose alike.
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS bookmarks (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                user_id TEXT NOT NULL,
                url TEXT NOT NULL,
                title TEXT,
                content_markdown TEXT,
                tags TEXT[],
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP WITH TIME ZONE,
                CONSTRAINT unique_user_url UNIQUE (user_id, url)
            )
        """))
        await conn.execute(
            text(
                "ALTER TABLE bookmarks ADD COLUMN IF NOT EXISTS "
                "updated_at TIMESTAMP WITH TIME ZONE"
            )
        )
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_bookmarks_user_id ON bookmarks(user_id)"
        ))
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS bookmark_embeddings (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                bookmark_id UUID REFERENCES bookmarks(id) ON DELETE CASCADE,
                chunk_index INTEGER NOT NULL,
                chunk_text TEXT NOT NULL,
                embedding VECTOR(384)
            )
        """))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS embedding_idx "
            "ON bookmark_embeddings USING hnsw (embedding vector_cosine_ops)"
        ))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_bookmark_embeddings_bookmark_id "
            "ON bookmark_embeddings(bookmark_id)"
        ))
        await conn.execute(text(f"""
            CREATE TABLE IF NOT EXISTS bookmark_embeddings_openai (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                bookmark_id UUID REFERENCES bookmarks(id) ON DELETE CASCADE,
                chunk_index INTEGER NOT NULL,
                chunk_text TEXT NOT NULL,
                embedding VECTOR({openai_dim})
            )
        """))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_bookmark_embeddings_openai_bookmark_id "
            "ON bookmark_embeddings_openai(bookmark_id)"
        ))
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS allowed_users (
                email TEXT PRIMARY KEY,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            )
        """))
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS refresh_tokens (
                jti UUID PRIMARY KEY,
                user_sub TEXT NOT NULL,
                email TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                expires_at TIMESTAMPTZ NOT NULL,
                last_used_at TIMESTAMPTZ,
                revoked_at TIMESTAMPTZ,
                user_agent TEXT
            )
        """))
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS refresh_tokens_user_sub_idx
                ON refresh_tokens (user_sub) WHERE revoked_at IS NULL
        """))


    # Idempotently attempt to create HNSW index in a separate transaction block
    try:
        async with engine.begin() as conn:
            await conn.execute(text(
                "CREATE INDEX IF NOT EXISTS embedding_openai_idx "
                "ON bookmark_embeddings_openai USING hnsw (embedding vector_cosine_ops)"
            ))
    except Exception as e:
        print(
            "Warning: Could not create HNSW index for OpenAI embeddings: "
            f"{e}. Falling back to linear scan."
        )
    yield
    # Shutdown
    await app.state.http.aclose()
    await engine.dispose()



limiter = Limiter(key_func=get_remote_address)
app = FastAPI(title="Smart Bookmark Manager API", version="1.0.0", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore


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



security = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> str:
    token = credentials.credentials

    # Dev fallback preserved — mock tokens starting with "user_" still pass in dev
    if token.startswith("user_"):
        if settings.ENVIRONMENT == "production":
            raise HTTPException(
                status_code=401,
                detail="Mock auth tokens are not permitted in production",
            )
        return token

    try:
        payload = auth.decode_token(token, typ="access")
        sub = payload.get("sub")
        if not sub:
            raise HTTPException(status_code=401, detail="Token missing subject")
        return sub
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {e}")



# --- Endpoints ---

@app.get("/")
async def root():
    return {"message": "Smart Bookmark Manager API is running"}


@app.post("/auth/google")
@limiter.limit("5/minute")
async def auth_google(
    request: Request,
    payload: GoogleAuthRequest,
    session: AsyncSession = Depends(get_session)
):
    google_token = payload.google_access_token
    
    # Dev fallback for Google token
    if google_token.startswith("user_"):
        if settings.ENVIRONMENT == "production":
            raise HTTPException(
                status_code=400, detail="Mock auth not allowed in production"
            )
        sub = google_token
        email = f"{google_token}@example.com"
    else:
        # 1. Validate the Google token
        try:
            response = await request.app.state.http.get(
                "https://www.googleapis.com/oauth2/v3/userinfo",
                headers={"Authorization": f"Bearer {google_token}"}
            )
            if response.status_code != 200:
                raise HTTPException(
                    status_code=401, detail="Invalid Google access token"
                )
        except Exception as e:
            if isinstance(e, HTTPException):
                raise
            raise HTTPException(
                status_code=401,
                detail=f"Failed to validate Google token: {e}",
            )
            
        user_info = response.json()
        sub = user_info.get("sub")
        email = user_info.get("email")
        
        if not sub or not email:
            raise HTTPException(
                status_code=400,
                detail="Missing user identity details from Google",
            )
        
    # 2. Pilot Mode Check
    stmt = select(AllowedUser).where(AllowedUser.email == email)
    result = await session.execute(stmt)
    is_allowed = result.scalar_one_or_none()
    if not is_allowed:
        raise HTTPException(
            status_code=403,
            detail="Pilot Mode: Access restricted to allowed users only.",
        )
        
    # 3. Generate tokens
    jti = uuid4()
    access_token = auth.create_access_token(sub, email)
    refresh_token = auth.create_refresh_token(sub, email, str(jti))
    
    # 4. Save refresh token to database
    expires_at = datetime.now(timezone.utc) + timedelta(
        seconds=settings.JWT_REFRESH_TTL_SECONDS
    )
    user_agent = request.headers.get("user-agent", "")[:255]
    
    db_token = RefreshToken(
        jti=jti,
        user_sub=sub,
        email=email,
        expires_at=expires_at,
        user_agent=user_agent
    )
    session.add(db_token)
    await session.commit()
    
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "Bearer",
        "expires_in": settings.JWT_ACCESS_TTL_SECONDS,
        "user": {
            "sub": sub,
            "email": email
        }
    }


@app.post("/auth/refresh")
@limiter.limit("30/minute")
async def auth_refresh(
    request: Request,
    payload: RefreshTokenRequest,
    session: AsyncSession = Depends(get_session)
):
    refresh_token = payload.refresh_token
    
    # 1. Decode & Verify local claims
    try:
        claims = auth.decode_token(refresh_token, typ="refresh")
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Refresh token expired")
    except jwt.InvalidTokenError as e:
        raise HTTPException(status_code=401, detail=f"Invalid refresh token: {e}")
        
    jti_str = claims.get("jti")
    if not jti_str:
        raise HTTPException(status_code=401, detail="Refresh token missing JTI")
        
    try:
        jti_uuid = UUID(jti_str)
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid JTI format")
        
    # 2. Look up in the database (with row locking to serialize concurrent
    # refresh calls)
    stmt = select(RefreshToken).where(RefreshToken.jti == jti_uuid).with_for_update()
    result = await session.execute(stmt)
    token_record = result.scalar_one_or_none()
    
    if not token_record:
        raise HTTPException(
            status_code=401, detail="Refresh token not found or invalid"
        )
        
    # 3. Check revocation and expiration in DB
    now = datetime.now(timezone.utc)
    if token_record.revoked_at is not None:
        raise HTTPException(status_code=401, detail="Refresh token has been revoked")
    if token_record.expires_at < now:
        raise HTTPException(
            status_code=401,
            detail="Refresh token has expired in database",
        )
        
    # 4. Verify user is still allowed (Pilot Mode)
    stmt_allowed = select(AllowedUser).where(AllowedUser.email == token_record.email)
    res_allowed = await session.execute(stmt_allowed)
    is_allowed = res_allowed.scalar_one_or_none()
    if not is_allowed:
        raise HTTPException(
            status_code=403,
            detail="Pilot Mode: Access restricted to allowed users only.",
        )
        
    # 5. Rotate tokens (single transaction)
    token_record.revoked_at = now
    token_record.last_used_at = now
    session.add(token_record)
    
    new_jti = uuid4()
    new_access_token = auth.create_access_token(
        token_record.user_sub, token_record.email
    )
    new_refresh_token = auth.create_refresh_token(
        token_record.user_sub, token_record.email, str(new_jti)
    )
    
    new_expires_at = now + timedelta(seconds=settings.JWT_REFRESH_TTL_SECONDS)
    new_record = RefreshToken(
        jti=new_jti,
        user_sub=token_record.user_sub,
        email=token_record.email,
        expires_at=new_expires_at,
        user_agent=request.headers.get("user-agent", "")[:255]
    )
    session.add(new_record)
    await session.commit()
    
    return {
        "access_token": new_access_token,
        "refresh_token": new_refresh_token,
        "token_type": "Bearer",
        "expires_in": settings.JWT_ACCESS_TTL_SECONDS,
        "user": {
            "sub": token_record.user_sub,
            "email": token_record.email
        }
    }


@app.post("/auth/logout")
async def auth_logout(
    payload: LogoutRequest,
    session: AsyncSession = Depends(get_session)
):
    refresh_token = payload.refresh_token
    try:
        claims = auth.decode_token(refresh_token, typ="refresh")
        jti_str = claims.get("jti")
        if jti_str:
            jti_uuid = UUID(jti_str)
            stmt = select(RefreshToken).where(RefreshToken.jti == jti_uuid)
            result = await session.execute(stmt)
            token_record = result.scalar_one_or_none()
            if token_record and token_record.revoked_at is None:
                token_record.revoked_at = datetime.now(timezone.utc)
                session.add(token_record)
                await session.commit()
    except Exception:
        # Best effort logout
        pass
    return Response(status_code=204)


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
            session,
            user_id,
            payload.url,
            payload.title,
            payload.content_markdown,
            payload.tags,
        )
        return BookmarkResponse(
            id=str(bookmark.id),
            url=bookmark.url,
            title=bookmark.title,
            tags=bookmark.tags,
            status="ingested",
            created_at=bookmark.created_at,
            updated_at=bookmark.updated_at,
            content_markdown=bookmark.content_markdown
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
        # returns list of (BookmarkEmbedding, Bookmark, distance) tuples
        results = await search_service.search(
            session, user_id, payload.query, payload.limit
        )
        
        response_list = []
        for embedding_entry, bookmark, distance in results:
            response_list.append(SearchResult(
                id=str(bookmark.id),
                url=bookmark.url,
                title=bookmark.title,
                score=distance, 
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
                status="saved",
                created_at=b.created_at,
                updated_at=b.updated_at
            ) for b in bookmarks
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/tags", response_model=List[TagCount])
@limiter.limit("60/minute")
async def get_tags(
    request: Request,
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(get_current_user)
):
    try:
        return await management_service.get_tags(session, user_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/bookmarks", response_model=PaginatedBookmarksResponse)
@limiter.limit("60/minute")
async def get_bookmarks(
    request: Request,
    skip: int = 0,
    limit: int = 50,
    tag_prefix: Optional[str] = None,
    query: Optional[str] = None,
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(get_current_user)
):
    try:
        bookmarks, total = await management_service.get_bookmarks(
            session, user_id, skip, limit, tag_prefix, query
        )
        items = [
            BookmarkResponse(
                id=str(b.id),
                url=b.url,
                title=b.title,
                tags=b.tags,
                status="saved",
                created_at=b.created_at,
                updated_at=b.updated_at
            ) for b in bookmarks
        ]
        return PaginatedBookmarksResponse(
            items=items, total=total, skip=skip, limit=limit
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.patch("/bookmarks/{bookmark_id}", response_model=BookmarkResponse)
@limiter.limit("60/minute")
async def update_bookmark(
    request: Request,
    bookmark_id: str,
    payload: BookmarkUpdateRequest,
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(get_current_user)
):
    try:
        bookmark = await management_service.update_bookmark(
            session, user_id, bookmark_id, payload.title, payload.tags
        )
        if not bookmark:
            raise HTTPException(status_code=404, detail="Bookmark not found")
        return BookmarkResponse(
            id=str(bookmark.id),
            url=bookmark.url,
            title=bookmark.title,
            tags=bookmark.tags,
            status="updated",
            created_at=bookmark.created_at,
            updated_at=bookmark.updated_at,
            content_markdown=bookmark.content_markdown
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/bookmarks/{bookmark_id}")
@limiter.limit("60/minute")
async def delete_bookmark(
    request: Request,
    bookmark_id: str,
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(get_current_user)
):
    try:
        success = await management_service.delete_bookmark(
            session, user_id, bookmark_id
        )
        if not success:
            raise HTTPException(status_code=404, detail="Bookmark not found")
        return {"status": "deleted"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/bookmarks/bulk_update_tags", response_model=BulkUpdateResponse)
@limiter.limit("60/minute")
async def bulk_update_tags(
    request: Request,
    payload: BulkTagUpdateRequest,
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(get_current_user)
):
    try:
        count = await management_service.bulk_update_tags(
            session, user_id, payload.old_prefix, payload.new_prefix
        )
        return BulkUpdateResponse(updated_count=count)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/bookmarks/bulk_delete", response_model=BulkDeleteResponse)
@limiter.limit("60/minute")
async def bulk_delete_bookmarks(
    request: Request,
    payload: BulkDeleteRequest,
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(get_current_user)
):
    try:
        count = await management_service.bulk_delete(
            session, user_id, payload.bookmark_ids
        )
        return BulkDeleteResponse(deleted_count=count)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/bookmarks/bulk_add_tag", response_model=BulkUpdateResponse)
@limiter.limit("60/minute")
async def bulk_add_tag(
    request: Request,
    payload: BulkAddRemoveTagRequest,
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(get_current_user)
):
    try:
        count = await management_service.bulk_add_tag(
            session, user_id, payload.bookmark_ids, payload.tag
        )
        return BulkUpdateResponse(updated_count=count)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/bookmarks/bulk_remove_tag", response_model=BulkUpdateResponse)
@limiter.limit("60/minute")
async def bulk_remove_tag(
    request: Request,
    payload: BulkAddRemoveTagRequest,
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(get_current_user)
):
    try:
        count = await management_service.bulk_remove_tag(
            session, user_id, payload.bookmark_ids, payload.tag
        )
        return BulkUpdateResponse(updated_count=count)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/bookmarks/reembed")
@limiter.limit("5/minute")
async def start_reembed(
    request: Request,
    background_tasks: BackgroundTasks,
    user_id: str = Depends(get_current_user)
):
    background_tasks.add_task(management_service.reembed_user_bookmarks, user_id)
    return {"status": "started"}

@app.get("/bookmarks/reembed/status")
@limiter.limit("60/minute")
async def get_reembed_status(
    request: Request,
    user_id: str = Depends(get_current_user)
):
    status = management_service.reembed_jobs.get(user_id)
    if not status:
        return {"status": "none"}
    return status

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
