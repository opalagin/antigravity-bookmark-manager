import asyncio
from sqlmodel import select, delete
from database import get_session
from models import Bookmark
from services import get_provider, split_text

async def reembed_all():
    print("Fetching all bookmarks...")
    # Manually get a session
    async for session in get_session():
        stmt = select(Bookmark)
        result = await session.execute(stmt)
        bookmarks = result.scalars().all()
        
        provider = get_provider()
        model_cls = provider.model_class
        
        print(
            f"Found {len(bookmarks)} bookmarks for provider "
            f"'{provider.name}'. Deleting old embeddings..."
        )
        await session.execute(delete(model_cls))
        await session.commit()
        
        print("Re-embedding bookmarks...")
        for b in bookmarks:
            if not b.content_markdown:
                continue
            
            chunks = split_text(b.content_markdown)
            if not chunks:
                continue
                
            embeddings = await provider.embed_documents(chunks)
            for i, (text, vector) in enumerate(zip(chunks, embeddings)):
                emb_entry = model_cls(
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
