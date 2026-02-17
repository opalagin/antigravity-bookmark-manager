from typing import List
from sqlmodel import select, delete
from sqlmodel.ext.asyncio.session import AsyncSession
from langchain_text_splitters import RecursiveCharacterTextSplitter
from sentence_transformers import SentenceTransformer
from models import Bookmark, BookmarkEmbedding
from database import get_session
import asyncio
import os
from openai import AsyncOpenAI

# --- Embedding Service ---
class EmbeddingService:
    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        # Load model slightly lazily or globally. 
        # For simplicity in this demo, initializing here. 
        # In prod, consider a singleton or valid dependency injection.
        self.model = SentenceTransformer(model_name)

    def _embed_sync(self, texts: List[str]) -> List[List[float]]:
        # SentenceTransformer is blocking / CPU bound
        # Cast to list[float] explicitly
        embeddings = self.model.encode(texts, convert_to_tensor=False)
        return embeddings.tolist()

    async def embed_documents(self, texts: List[str]) -> List[List[float]]:
        # Offload blocking work to threadpool
        return await asyncio.to_thread(self._embed_sync, texts)
    
    async def embed_query(self, text: str) -> List[float]:
        embeddings = await self.embed_documents([text])
        return embeddings[0]

# Singleton instance
embedding_service = EmbeddingService()


# --- Ingestion Service ---
class IngestionService:
    def __init__(self, embedding_service: EmbeddingService):
        self.embedding_service = embedding_service
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000,
            chunk_overlap=200
        )

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
        chunks = self.text_splitter.split_text(content)
        
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

    async def search(self, session: AsyncSession, user_id: str, query: str, limit: int = 5):
        # 1. Embed Query
        query_vector = await self.embedding_service.embed_query(query)
        
        # 2. Vector Search with Join
        # Return tuple (BookmarkEmbedding, Bookmark)
        # Filter by user_id on Bookmark
        # Fetch more candidates than limit to allow for deduplication
        candidate_limit = limit * 4 
        
        stmt = select(BookmarkEmbedding, Bookmark).join(Bookmark).where(
            Bookmark.user_id == user_id
        ).order_by(
            BookmarkEmbedding.embedding.cosine_distance(query_vector)
        ).limit(candidate_limit)
        
        result = await session.execute(stmt)
        all_matches = result.all()
        
        # Deduplicate: Keep only the best matching chunk per bookmark
        unique_results = []
        seen_bookmarks = set()
        
        for embedding, bookmark in all_matches:
            if bookmark.id not in seen_bookmarks:
                unique_results.append((embedding, bookmark))
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
        
        for embedding_entry, bookmark in results:
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
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            # Fallback Mock
            answer = f"**[Mock AI Response]**\n\nBased on your bookmarks, here is what I found:\n\n{context_text[:500]}... (truncated for mock)\n\n*Note: Set OPENAI_API_KEY to get real answers.*"
            return answer, sources

        try:
            client = AsyncOpenAI(api_key=api_key)
            response = await client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": """
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
                    },
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
