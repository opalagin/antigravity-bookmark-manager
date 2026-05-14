from typing import List
from sqlmodel import select, delete
from sqlalchemy import func, text
from sqlmodel.ext.asyncio.session import AsyncSession
from fastembed import TextEmbedding
from models import Bookmark, BookmarkEmbedding
from database import get_session
import asyncio
import os
from openai import AsyncOpenAI
import httpx
from datetime import datetime

def split_text(text: str, chunk_size: int = 1000, overlap: int = 200) -> list[str]:
    if len(text) <= chunk_size:
        return [text]
    chunks, start = [], 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        chunks.append(text[start:end])
        start += chunk_size - overlap
    return chunks

# --- Embedding Service ---
class EmbeddingService:
    def __init__(self):
        self.model = TextEmbedding("BAAI/bge-small-en-v1.5")

    def _embed_sync(self, texts: List[str]) -> List[List[float]]:
        # fastembed yields generators, so convert to list explicitly
        return [embedding.tolist() for embedding in self.model.embed(texts)]

    async def embed_documents(self, texts: List[str]) -> List[List[float]]:
        # Offload blocking work to threadpool
        return await asyncio.to_thread(self._embed_sync, texts)
    
    async def embed_query(self, text: str) -> List[float]:
        def _query_embed_sync():
            return next(self.model.query_embed(text)).tolist()
        return await asyncio.to_thread(_query_embed_sync)

# Singleton instance
embedding_service = EmbeddingService()


# --- Ingestion Service ---
class IngestionService:
    def __init__(self, embedding_service: EmbeddingService):
        self.embedding_service = embedding_service

    async def process_bookmark(self, session: AsyncSession, user_id: str, url: str, title: str, content: str, tags: List[str] = []) -> Bookmark:
        # 1. Check if exists for this user
        stmt = select(Bookmark).where(Bookmark.url == url, Bookmark.user_id == user_id)
        result = await session.execute(stmt)
        existing_bookmark = result.scalar_one_or_none()

        if existing_bookmark:
            # Update existing
            bookmark = existing_bookmark
            bookmark.title = title
            bookmark.content_markdown = content
            bookmark.tags = tags
            
            # Clear old embeddings to re-ingest
            del_stmt = delete(BookmarkEmbedding).where(BookmarkEmbedding.bookmark_id == bookmark.id)
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
            emb_entry = BookmarkEmbedding(
                bookmark_id=bookmark.id,
                chunk_index=i,
                chunk_text=text,
                embedding=vector
            )
            session.add(emb_entry)
            
        await session.commit()
        await session.refresh(bookmark)
        return bookmark

ingestion_service = IngestionService(embedding_service)


# --- Search Service ---
class SearchService:
    def __init__(self, embedding_service: EmbeddingService):
        self.embedding_service = embedding_service

    async def search(self, session: AsyncSession, user_id: str, query: str, limit: int = 5, threshold: float = 0.4):
        # 1. Embed Query
        query_vector = await self.embedding_service.embed_query(query)
        
        # 2. Vector Search with Join
        # Return tuple (BookmarkEmbedding, Bookmark, distance)
        # Filter by user_id on Bookmark
        # Fetch more candidates than limit to allow for deduplication AND threshold filtering
        candidate_limit = limit * 4 
        
        # Define distance expression for selection and ordering
        distance_col = BookmarkEmbedding.embedding.cosine_distance(query_vector).label("distance")
        
        stmt = select(BookmarkEmbedding, Bookmark, distance_col).join(Bookmark).where(
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
        api_key = os.getenv("OPENAI_API_KEY")
        
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

        if not api_key:
            # Fallback Mock
            answer = f"**[Mock AI Response]**\n\nBased on your bookmarks, here is what I found:\n\n{context_text[:500]}... (truncated for mock)\n\n*Note: Set OPENAI_API_KEY to get real answers.*"
            return answer, sources

        try:
            client = AsyncOpenAI(api_key=api_key)
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
        stmt = select(Bookmark).where(Bookmark.user_id == user_id).order_by(Bookmark.created_at.desc()).limit(limit)
        result = await session.execute(stmt)
        return result.scalars().all()

search_service = SearchService(embedding_service)

# --- Management Service ---
class ManagementService:
    async def get_bookmarks(self, session: AsyncSession, user_id: str, skip: int = 0, limit: int = 50, tag_prefix: str = None, query: str = None):
        stmt = select(Bookmark).where(Bookmark.user_id == user_id)
        
        if tag_prefix:
            if tag_prefix == "untagged":
                stmt = stmt.where((Bookmark.tags == '{}') | (Bookmark.tags == None))
            else:
                # Match exact tag or nested tags under this prefix
                stmt = stmt.where(text("EXISTS (SELECT 1 FROM unnest(tags) tag WHERE tag = :tag_exact OR tag LIKE :tag_prefix)")).params(tag_exact=tag_prefix, tag_prefix=f"{tag_prefix}/%")
            
        if query:
            stmt = stmt.where(Bookmark.title.ilike(f"%{query}%") | Bookmark.url.ilike(f"%{query}%"))
            
        # Get total count
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total_result = await session.execute(count_stmt)
        total = total_result.scalar_one()
        
        # Get paginated results
        stmt = stmt.order_by(Bookmark.created_at.desc()).offset(skip).limit(limit)
        result = await session.execute(stmt)
        bookmarks = result.scalars().all()
        
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
        stmt = select(Bookmark).where(Bookmark.user_id == user_id).where(text("EXISTS (SELECT 1 FROM unnest(tags) tag WHERE tag = :old_exact OR tag LIKE :old_prefix)")).params(old_exact=old_prefix, old_prefix=f"{old_prefix}/%")
        result = await session.execute(stmt)
        bookmarks = result.scalars().all()
        
        updated_count = 0
        for bookmark in bookmarks:
            new_tags = []
            changed = False
            for tag in bookmark.tags:
                if tag == old_prefix:
                    new_tags.append(new_prefix)
                    changed = True
                elif tag.startswith(old_prefix + "/"):
                    new_tag = new_prefix + tag[len(old_prefix):]
                    new_tags.append(new_tag)
                    changed = True
                else:
                    new_tags.append(tag)
                    
            if changed:
                bookmark.tags = new_tags
                bookmark.updated_at = datetime.utcnow()
                updated_count += 1
                
        await session.commit()
        return updated_count

    async def bulk_delete(self, session: AsyncSession, user_id: str, bookmark_ids: List[str]):
        stmt = delete(Bookmark).where(Bookmark.user_id == user_id, Bookmark.id.in_(bookmark_ids))
        result = await session.execute(stmt)
        await session.commit()
        return result.rowcount

    async def bulk_add_tag(self, session: AsyncSession, user_id: str, bookmark_ids: List[str], tag: str):
        stmt = select(Bookmark).where(Bookmark.user_id == user_id, Bookmark.id.in_(bookmark_ids))
        result = await session.execute(stmt)
        bookmarks = result.scalars().all()
        
        updated_count = 0
        for bookmark in bookmarks:
            if tag not in bookmark.tags:
                new_tags = list(bookmark.tags)
                new_tags.append(tag)
                bookmark.tags = new_tags
                bookmark.updated_at = datetime.utcnow()
                updated_count += 1
                
        await session.commit()
        return updated_count

    async def bulk_remove_tag(self, session: AsyncSession, user_id: str, bookmark_ids: List[str], tag: str):
        stmt = select(Bookmark).where(Bookmark.user_id == user_id, Bookmark.id.in_(bookmark_ids))
        result = await session.execute(stmt)
        bookmarks = result.scalars().all()
        
        updated_count = 0
        for bookmark in bookmarks:
            if tag in bookmark.tags:
                new_tags = [t for t in bookmark.tags if t != tag]
                bookmark.tags = new_tags
                bookmark.updated_at = datetime.utcnow()
                updated_count += 1
                
        await session.commit()
        return updated_count

management_service = ManagementService()
