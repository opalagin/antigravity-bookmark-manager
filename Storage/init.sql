-- Enable the pgvector extension to work with embedding vectors
CREATE EXTENSION IF NOT EXISTS vector;

-- Table for storing high-level bookmark/article metadata
CREATE TABLE IF NOT EXISTS bookmarks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id TEXT NOT NULL,
    url TEXT NOT NULL,
    title TEXT,
    content_markdown TEXT,
    tags TEXT[],
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT unique_user_url UNIQUE (user_id, url)
);
CREATE INDEX IF NOT EXISTS idx_bookmarks_user_id ON bookmarks(user_id);

-- Table for storing vector embeddings of article chunks
CREATE TABLE IF NOT EXISTS bookmark_embeddings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    bookmark_id UUID REFERENCES bookmarks(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    chunk_text TEXT NOT NULL,
    -- Dimension 384 is for all-MiniLM-L6-v2.
    embedding VECTOR(384)
);

-- Index for searching embeddings using HNSW (Hierarchical Navigable Small World) for speed
-- 'vector_cosine_ops' optimizes for cosine similarity
CREATE INDEX IF NOT EXISTS embedding_idx ON bookmark_embeddings USING hnsw (embedding vector_cosine_ops);

-- Index for foreign key performance
CREATE INDEX IF NOT EXISTS idx_bookmark_embeddings_bookmark_id ON bookmark_embeddings(bookmark_id);
