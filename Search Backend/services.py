from typing import List, Protocol, Optional, Type
from sqlmodel import select, delete, SQLModel
from sqlalchemy import func, text
from sqlmodel.ext.asyncio.session import AsyncSession
from models import Bookmark, BookmarkEmbedding, BookmarkEmbeddingOpenAI
from database import get_session
import asyncio
import os
import gc, ctypes, sys
from openai import AsyncOpenAI, RateLimitError, APIConnectionError
import httpx
from datetime import datetime

try:
    _libc = ctypes.CDLL("libc.so.6")
except OSError:
    _libc = None

def _release_memory():
    gc.collect()
    if _libc is not None:
        try:
            _libc.malloc_trim(0)
        except Exception:
            pass

_openai_client: AsyncOpenAI | None = None

def _get_openai_client() -> AsyncOpenAI | None:
    global _openai_client
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None
    if _openai_client is None:
        _openai_client = AsyncOpenAI(api_key=api_key)
    return _openai_client

def split_text(text: str, chunk_size: int = 1000, overlap: int = 200) -> list[str]:
    if len(text) <= chunk_size:
        return [text]
    chunks, start = [], 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        chunks.append(text[start:end])
        start += chunk_size - overlap
    return chunks

# --- Embedding Provider Abstraction ---
class EmbeddingProvider(Protocol):
    name: str              # "local" | "openai"
    dimension: int         # vector size produced by this provider
    table_name: str        # pgvector table this provider's vectors live in
    threshold: float       # default cosine distance threshold for search
    model_class: Type[SQLModel]

    async def embed_documents(self, texts: List[str]) -> List[List[float]]: ...
    async def embed_query(self, text: str) -> List[float]: ...

class LocalEmbeddingProvider:
    name: str = "local"
    dimension: int = 384
    table_name: str = "bookmark_embeddings"
    
    def __init__(self, threshold: float = 0.4):
        self.threshold = threshold
        self.model_class = BookmarkEmbedding
        from fastembed import TextEmbedding
        self.model = TextEmbedding("BAAI/bge-small-en-v1.5", threads=1)

    def _embed_sync(self, texts: List[str]) -> List[List[float]]:
        # fastembed yields generators, so convert to list explicitly
        return [embedding.tolist() for embedding in self.model.embed(texts, parallel=0)]

    async def embed_documents(self, texts: List[str]) -> List[List[float]]:
        # Offload blocking work to threadpool
        result = await asyncio.to_thread(self._embed_sync, texts)
        _release_memory()
        return result
    
    async def embed_query(self, text: str) -> List[float]:
        def _query_embed_sync():
            return next(self.model.query_embed(text, parallel=0)).tolist()
        return await asyncio.to_thread(_query_embed_sync)

class OpenAIEmbeddingProvider:
    name: str = "openai"
    table_name: str = "bookmark_embeddings_openai"

    def __init__(self, model_name: str = "text-embedding-3-small", dimension: int = 1536, threshold: float = 0.6):
        self.model_name = model_name
        self.dimension = dimension
        self.threshold = threshold
        self.model_class = BookmarkEmbeddingOpenAI

    async def _embed_with_retry(self, func, *args, **kwargs):
        import random
        retries = 3
        delay = 1.0
        for attempt in range(retries + 1):
            try:
                return await func(*args, **kwargs)
            except (RateLimitError, APIConnectionError) as e:
                if attempt == retries:
                    raise e
                jitter = random.uniform(0, 0.1 * delay)
                sleep_time = delay + jitter
                print(f"OpenAI embedding call failed due to {type(e).__name__}: {e}. Retrying in {sleep_time:.2f}s...")
                await asyncio.sleep(sleep_time)
                delay *= 2.0

    async def embed_documents(self, texts: List[str]) -> List[List[float]]:
        client = _get_openai_client()
        if not client:
            raise ValueError("OpenAI client not configured (missing OPENAI_API_KEY).")
        
        async def _call():
            response = await client.embeddings.create(
                input=texts,
                model=self.model_name,
                dimensions=self.dimension
            )
            return [data.embedding for data in response.data]
            
        return await self._embed_with_retry(_call)

    async def embed_query(self, text: str) -> List[float]:
        client = _get_openai_client()
        if not client:
            raise ValueError("OpenAI client not configured (missing OPENAI_API_KEY).")
        
        async def _call():
            response = await client.embeddings.create(
                input=[text],
                model=self.model_name,
                dimensions=self.dimension
            )
            return response.data[0].embedding
            
        return await self._embed_with_retry(_call)

_provider_instance: EmbeddingProvider | None = None

def get_provider() -> EmbeddingProvider:
    global _provider_instance
    if _provider_instance is not None:
        return _provider_instance

    provider_name = os.getenv("EMBEDDING_PROVIDER", "local").lower()
    if provider_name == "local":
        search_threshold_str = os.getenv("EMBEDDING_SEARCH_THRESHOLD")
        threshold = 0.4
        if search_threshold_str:
            try:
                threshold = float(search_threshold_str)
            except ValueError:
                raise ValueError(f"Invalid EMBEDDING_SEARCH_THRESHOLD: {search_threshold_str}")
        _provider_instance = LocalEmbeddingProvider(threshold=threshold)
    elif provider_name == "openai":
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY env variable must be set when EMBEDDING_PROVIDER is 'openai'.")
        
        model_name = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
        dimensions_str = os.getenv("OPENAI_EMBEDDING_DIMENSIONS", "1536")
        try:
            dimensions = int(dimensions_str)
        except ValueError:
            raise ValueError(f"Invalid OPENAI_EMBEDDING_DIMENSIONS value: {dimensions_str}. Must be an integer.")
        
        search_threshold_str = os.getenv("EMBEDDING_SEARCH_THRESHOLD")
        threshold = 0.6
        if search_threshold_str:
            try:
                threshold = float(search_threshold_str)
            except ValueError:
                raise ValueError(f"Invalid EMBEDDING_SEARCH_THRESHOLD value: {search_threshold_str}. Must be a float.")
        
        _provider_instance = OpenAIEmbeddingProvider(
            model_name=model_name,
            dimension=dimensions,
            threshold=threshold
        )
    else:
        raise ValueError(f"Unknown EMBEDDING_PROVIDER: '{provider_name}'")
    
    print(f"Initialized EmbeddingProvider: {_provider_instance.name} (dimension: {_provider_instance.dimension}, table: {_provider_instance.table_name}, threshold: {_provider_instance.threshold})")
    return _provider_instance

class LegacyEmbeddingServiceProxy:
    def __getattr__(self, name):
        return getattr(get_provider(), name)

embedding_service = LegacyEmbeddingServiceProxy()


# --- Ingestion Service ---
class IngestionService:
    def __init__(self, embedding_service: Optional[EmbeddingProvider] = None):
        self._embedding_service = embedding_service

    @property
    def embedding_service(self) -> EmbeddingProvider:
        return self._embedding_service or get_provider()

    async def process_bookmark(self, session: AsyncSession, user_id: str, url: str, title: str, content: str, tags: List[str] = []) -> Bookmark:
        # 1. Check if exists for this user
        stmt = select(Bookmark).where(Bookmark.url == url, Bookmark.user_id == user_id)
        result = await session.execute(stmt)
        existing_bookmark = result.scalar_one_or_none()

        provider = get_provider()
        model_cls = provider.model_class

        if existing_bookmark:
            # Update existing
            bookmark = existing_bookmark
            bookmark.title = title
            bookmark.content_markdown = content
            bookmark.tags = tags
            
            # Clear old embeddings to re-ingest
            del_stmt = delete(model_cls).where(model_cls.bookmark_id == bookmark.id)
            await session.execute(del_stmt)
        else:
            # Create New
            bookmark = Bookmark(user_id=user_id, url=url, title=title, content_markdown=content, tags=tags)
            session.add(bookmark)
            await session.flush() # get ID
        
        if not content:
            await session.commit() # Commit updates if any
            return bookmark

        # 2. Chunk Content
        chunks = split_text(content)
        
        if not chunks:
            return bookmark
            
        # 3. Embed Chunks
        embeddings = await self.embedding_service.embed_documents(chunks)
        
        # 4. Create Embedding Entries
        for i, (text, vector) in enumerate(zip(chunks, embeddings)):
            emb_entry = model_cls(
                bookmark_id=bookmark.id,
                chunk_index=i,
                chunk_text=text,
                embedding=vector
            )
            session.add(emb_entry)
            
        await session.commit()
        await session.refresh(bookmark)
        return bookmark

ingestion_service = IngestionService()


# --- Search Service ---
class SearchService:
    def __init__(self, embedding_service: Optional[EmbeddingProvider] = None):
        self._embedding_service = embedding_service

    @property
    def embedding_service(self) -> EmbeddingProvider:
        return self._embedding_service or get_provider()

    async def search(self, session: AsyncSession, user_id: str, query: str, limit: int = 5, threshold: Optional[float] = None):
        provider = get_provider()
        model_cls = provider.model_class
        if threshold is None:
            threshold = provider.threshold

        # 1. Embed Query
        query_vector = await self.embedding_service.embed_query(query)
        
        # 2. Vector Search with Join
        # Return tuple (BookmarkEmbedding, Bookmark, distance)
        # Filter by user_id on Bookmark
        # Fetch more candidates than limit to allow for deduplication AND threshold filtering
        candidate_limit = limit * 4 
        
        # Define distance expression for selection and ordering
        distance_col = model_cls.embedding.cosine_distance(query_vector).label("distance")
        
        stmt = select(model_cls, Bookmark, distance_col).join(Bookmark).where(
            Bookmark.user_id == user_id
        ).order_by(
            distance_col
        ).limit(candidate_limit)
        
        result = await session.execute(stmt)
        all_matches = result.all()
        
        # Deduplicate & Filter: Keep only the best matching chunk per bookmark that meets the threshold
        unique_results = []
        seen_bookmarks = set()
        
        for embedding, bookmark, distance in all_matches:
            # Skip if distance is too high (low similarity)
            # Cosine distance: 0 = identical, 1 = orthogonal, 2 = opposite
            # Threshold 0.4 filters out unrelated BGE embeddings (which hover around 0.45-0.5)
            if distance > threshold:
                continue

            if bookmark.id not in seen_bookmarks:
                unique_results.append((embedding, bookmark, distance))
                seen_bookmarks.add(bookmark.id)
                
            if len(unique_results) >= limit:
                break
                
        return unique_results

    async def chat(self, session: AsyncSession, user_id: str, query: str) -> tuple[str, List[str]]:
        # 1. Retrieve Context (Get more candidates to find unique bookmarks)
        # Re-using search but looking for top unique bookmarks
        results = await self.search(session, user_id, query, limit=5)
        
        if not results:
            return "I couldn't find any relevant bookmarks to answer your question.", []
            
        context_text = ""
        sources = []
        
        # Deduplicate and take top 3 unique bookmarks
        unique_bookmarks = []
        seen_ids = set()
        
        for embedding_entry, bookmark, _distance in results:
            if bookmark.id not in seen_ids:
                unique_bookmarks.append(bookmark)
                seen_ids.add(bookmark.id)
                if len(unique_bookmarks) >= 3:
                    break
        
        for i, bookmark in enumerate(unique_bookmarks):
            # Use FULL content (truncate if extremely large, but for now take all)
            # A safety truncation could be added here if needed (e.g. [:20000])
            content = bookmark.content_markdown or ""
            context_text += f"Source {i+1} ({bookmark.title}):\n{content}\n\n"
            sources.append(bookmark.url)
            
        print(f"--- Sending Context ({len(context_text)} chars) ---\n{context_text[:500]}...\n--- End Preview ---")

        # 2. LLM Generation
        llm_provider = os.getenv("LLM_PROVIDER", "openai").lower()
        
        system_prompt = """
You are a helpful assistant oriented to guide users in finding relevant information from their bookmarks.

You are provided with the FULL TEXT of the top relevant articles.
Answer questions strictly using the provided article context.

Rules:
- Use ONLY the provided context.
- Do NOT use outside knowledge.
- If the answer is not clearly supported or your confidence is low, just say "I don't know based on the provided context."
- Do not infer or assume missing information.
- If partial information exists, clearly state the limitations.

Formatting requirements:
- Provide a structured answer.
- Trail your answer with a list of sources (URLs).
- Use headings when helpful.
- Use bullet points for lists.
- Use code blocks for code snippets.
- Be precise and technically accurate.
- Avoid unnecessary verbosity.
"""

        if llm_provider == "ollama":
            ollama_base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
            ollama_model = os.getenv("OLLAMA_MODEL", "mistral:7b-instruct-q4_K_M")
            try:
                async with httpx.AsyncClient() as client:
                    payload = {
                        "model": ollama_model,
                        "messages": [
                            {"role": "system", "content": system_prompt.strip()},
                            {"role": "user", "content": f"Context:\n{context_text}\n\nQuestion: {query}\n\nSources:\n{sources}"}
                        ],
                        "stream": False
                    }
                    response = await client.post(f"{ollama_base_url}/api/chat", json=payload, timeout=60.0)
                    response.raise_for_status()
                    data = response.json()
                    return data.get("message", {}).get("content", "Error: No content in response"), sources
            except Exception as e:
                return f"Error contacting Ollama: {str(e)}", sources

        client = _get_openai_client()
        if not client:
            # Fallback Mock
            answer = f"**[Mock AI Response]**\n\nBased on your bookmarks, here is what I found:\n\n{context_text[:500]}... (truncated for mock)\n\n*Note: Set OPENAI_API_KEY to get real answers.*"
            return answer, sources

        try:
            response = await client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_prompt.strip()},
                    {"role": "user", "content": f"Context:\n{context_text}\n\nQuestion: {query}\n\nSources:\n{sources}"}
                ]
            )
            return response.choices[0].message.content, sources
        except Exception as e:
            return f"Error contacting OpenAI: {str(e)}", sources

    async def get_recent(self, session: AsyncSession, user_id: str, limit: int = 10):
        # Return list of Bookmarks
        stmt = select(
            Bookmark.id, Bookmark.url, Bookmark.title, Bookmark.tags,
            Bookmark.created_at, Bookmark.updated_at
        ).where(Bookmark.user_id == user_id).order_by(Bookmark.created_at.desc()).limit(limit)
        result = await session.execute(stmt)
        return result.all()

search_service = SearchService()

# --- Management Service ---
class ManagementService:
    def __init__(self):
        self.reembed_jobs: dict[str, dict] = {}

    async def get_bookmarks(self, session: AsyncSession, user_id: str, skip: int = 0, limit: int = 50, tag_prefix: str = None, query: str = None):
        base = select(
            Bookmark.id, Bookmark.url, Bookmark.title, Bookmark.tags,
            Bookmark.created_at, Bookmark.updated_at
        ).where(Bookmark.user_id == user_id)
        
        if tag_prefix:
            if tag_prefix == "untagged":
                base = base.where((Bookmark.tags == '{}') | (Bookmark.tags == None))
            else:
                # Match exact tag or nested tags under this prefix
                base = base.where(text("EXISTS (SELECT 1 FROM unnest(tags) tag WHERE tag = :tag_exact OR tag LIKE :tag_prefix)")).params(tag_exact=tag_prefix, tag_prefix=f"{tag_prefix}/%")
            
        if query:
            base = base.where(Bookmark.title.ilike(f"%{query}%") | Bookmark.url.ilike(f"%{query}%"))
            
        # Get total count
        count_stmt = select(func.count()).select_from(base.subquery())
        total_result = await session.execute(count_stmt)
        total = total_result.scalar_one()
        
        # Get paginated results
        stmt = base.order_by(Bookmark.created_at.desc()).offset(skip).limit(limit)
        result = await session.execute(stmt)
        bookmarks = result.all()
        
        return bookmarks, total

    async def get_tags(self, session: AsyncSession, user_id: str):
        # Return unique tags and their counts for the user
        stmt = text("""
            SELECT tag, count(*) as count
            FROM bookmarks, unnest(tags) as tag
            WHERE user_id = :user_id
            GROUP BY tag
            ORDER BY tag
        """)
        result = await session.execute(stmt, {"user_id": user_id})
        return [{"tag": row[0], "count": row[1]} for row in result.all()]

    async def update_bookmark(self, session: AsyncSession, user_id: str, bookmark_id: str, title: str = None, tags: List[str] = None):
        stmt = select(Bookmark).where(Bookmark.id == bookmark_id, Bookmark.user_id == user_id)
        result = await session.execute(stmt)
        bookmark = result.scalar_one_or_none()
        if not bookmark:
            return None
            
        if title is not None:
            bookmark.title = title
        if tags is not None:
            bookmark.tags = tags
            
        bookmark.updated_at = datetime.utcnow()
        await session.commit()
        await session.refresh(bookmark)
        return bookmark

    async def delete_bookmark(self, session: AsyncSession, user_id: str, bookmark_id: str):
        stmt = select(Bookmark).where(Bookmark.id == bookmark_id, Bookmark.user_id == user_id)
        result = await session.execute(stmt)
        bookmark = result.scalar_one_or_none()
        if not bookmark:
            return False
            
        await session.delete(bookmark)
        await session.commit()
        return True

    async def bulk_update_tags(self, session: AsyncSession, user_id: str, old_prefix: str, new_prefix: str):
        # Exact-tag rename
        exact = await session.execute(text("""
            UPDATE bookmarks
            SET tags = array_replace(tags, :old, :new), updated_at = NOW()
            WHERE user_id = :uid AND :old = ANY(tags)
        """), {"uid": user_id, "old": old_prefix, "new": new_prefix})

        # Nested prefix rename (e.g. "work/foo" -> "personal/foo")
        nested = await session.execute(text("""
            UPDATE bookmarks
            SET tags = (
                SELECT array_agg(
                    CASE WHEN tag LIKE :old_prefix
                         THEN :new || substring(tag from :cutoff)
                         ELSE tag END
                )
                FROM unnest(tags) tag
            ),
            updated_at = NOW()
            WHERE user_id = :uid
              AND EXISTS (SELECT 1 FROM unnest(tags) tag WHERE tag LIKE :old_prefix)
        """), {
            "uid": user_id,
            "old_prefix": f"{old_prefix}/%",
            "new": new_prefix,
            "cutoff": len(old_prefix) + 1,
        })
        await session.commit()
        return exact.rowcount + nested.rowcount

    async def bulk_delete(self, session: AsyncSession, user_id: str, bookmark_ids: List[str]):
        # Resolve only bookmark IDs that are actually owned by this user to prevent
        # cross-tenant embedding deletion (P2 fix)
        owned_stmt = select(Bookmark.id).where(
            Bookmark.user_id == user_id, Bookmark.id.in_(bookmark_ids)
        )
        owned_result = await session.execute(owned_stmt)
        owned_ids = [row[0] for row in owned_result.all()]

        if not owned_ids:
            return 0

        # Delete embeddings scoped to confirmed owned bookmarks in both tables
        emb_stmt = delete(BookmarkEmbedding).where(BookmarkEmbedding.bookmark_id.in_(owned_ids))
        await session.execute(emb_stmt)
        emb_openai_stmt = delete(BookmarkEmbeddingOpenAI).where(BookmarkEmbeddingOpenAI.bookmark_id.in_(owned_ids))
        await session.execute(emb_openai_stmt)

        stmt = delete(Bookmark).where(Bookmark.user_id == user_id, Bookmark.id.in_(owned_ids))
        result = await session.execute(stmt)
        await session.commit()
        return result.rowcount

    async def bulk_add_tag(self, session: AsyncSession, user_id: str, bookmark_ids: List[str], tag: str):
        result = await session.execute(text("""
            UPDATE bookmarks
            SET tags = array_append(tags, :tag), updated_at = NOW()
            WHERE user_id = :uid AND id = ANY(:ids) AND NOT (:tag = ANY(tags))
        """), {"uid": user_id, "ids": bookmark_ids, "tag": tag})
        await session.commit()
        return result.rowcount

    async def bulk_remove_tag(self, session: AsyncSession, user_id: str, bookmark_ids: List[str], tag: str):
        result = await session.execute(text("""
            UPDATE bookmarks
            SET tags = array_remove(tags, :tag), updated_at = NOW()
            WHERE user_id = :uid AND id = ANY(:ids) AND :tag = ANY(tags)
        """), {"uid": user_id, "ids": bookmark_ids, "tag": tag})
        await session.commit()
        return result.rowcount

    async def reembed_user_bookmarks(self, user_id: str):
        self.reembed_jobs[user_id] = {"status": "starting", "total": 0, "processed": 0, "error": None}
        
        try:
            async for session in get_session():
                id_rows = await session.execute(
                    select(Bookmark.id).where(Bookmark.user_id == user_id)
                )
                ids = [row[0] for row in id_rows.all()]
                total = len(ids)
                self.reembed_jobs[user_id].update(total=total, status="running")
                
                if total == 0:
                    self.reembed_jobs[user_id]["status"] = "completed"
                    break
                
                processed = 0
                for bid in ids:
                    b = (await session.execute(
                        select(Bookmark).where(Bookmark.id == bid)
                    )).scalar_one()
                    
                    provider = get_provider()
                    model_cls = provider.model_class
                    if b.content_markdown:
                        chunks = split_text(b.content_markdown)
                        if chunks:
                            await session.execute(
                                delete(model_cls).where(
                                    model_cls.bookmark_id == b.id
                                )
                            )
                            embeddings = await provider.embed_documents(chunks)
                            for i, (chunk_text, vector) in enumerate(zip(chunks, embeddings)):
                                session.add(model_cls(
                                    bookmark_id=b.id, chunk_index=i,
                                    chunk_text=chunk_text, embedding=vector,
                                ))
                    
                    await session.commit()
                    session.expunge(b)  # drop from identity map immediately
                    _release_memory()   # see A2
                    processed += 1
                    self.reembed_jobs[user_id]["processed"] = processed
                    
                self.reembed_jobs[user_id]["status"] = "completed"
                break # Only need one session from the generator
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.reembed_jobs[user_id]["status"] = "failed"
            self.reembed_jobs[user_id]["error"] = str(e)

management_service = ManagementService()

