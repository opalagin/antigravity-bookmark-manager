import asyncio
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select, delete
from database import get_session
from models import Bookmark, BookmarkEmbedding
from services import ingestion_service, split_text

async def reembed_all():
    print("Fetching all bookmarks...")
    # Manually get a session
    async for session in get_session():
        stmt = select(Bookmark)
        result = await session.execute(stmt)
        bookmarks = result.scalars().all()
        
        print(f"Found {len(bookmarks)} bookmarks. Deleting old embeddings...")
        await session.execute(delete(BookmarkEmbedding))
        await session.commit()
        
        print("Re-embedding bookmarks...")
        for b in bookmarks:
            if not b.content_markdown:
                continue
            
            chunks = split_text(b.content_markdown)
            if not chunks:
                continue
                
            embeddings = await ingestion_service.embedding_service.embed_documents(chunks)
            for i, (text, vector) in enumerate(zip(chunks, embeddings)):
                emb_entry = BookmarkEmbedding(
                    bookmark_id=b.id,
                    chunk_index=i,
                    chunk_text=text,
                    embedding=vector
                )
                session.add(emb_entry)
        
        await session.commit()
        print("Done!")
        break

if __name__ == "__main__":
    asyncio.run(reembed_all())
