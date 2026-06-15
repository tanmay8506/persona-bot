-- Database Schema Setup for Supabase PostgreSQL with pgvector

-- Enable the pgvector extension if not already present
CREATE EXTENSION IF NOT EXISTS vector;

-- 1. Profiles Table
-- Stores the target profile details and extracted style parameters
CREATE TABLE IF NOT EXISTS profiles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT UNIQUE NOT NULL,
    style JSONB NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

-- 2. Pairs Table
-- Stores Q&A context-response pairs alongside their semantic embeddings (Cohere v3, 1024d)
CREATE TABLE IF NOT EXISTS pairs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    profile_name TEXT REFERENCES profiles(name) ON DELETE CASCADE,
    context TEXT NOT NULL,
    response TEXT NOT NULL,
    embedding VECTOR(1024)
);

-- Create HNSW Index for sub-second similarity search on 1024d vectors
CREATE INDEX IF NOT EXISTS pairs_embedding_idx ON pairs USING hnsw (embedding vector_cosine_ops);

-- 3. Conversations Table
-- Stores active chat sessions between the user and target persona
CREATE TABLE IF NOT EXISTS conversations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    profile_name TEXT REFERENCES profiles(name) ON DELETE CASCADE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

-- 4. Messages Table
-- Stores conversation history for active sessions
CREATE TABLE IF NOT EXISTS messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id UUID REFERENCES conversations(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

-- Create indexes on lookup columns
CREATE INDEX IF NOT EXISTS pairs_profile_name_idx ON pairs (profile_name);
CREATE INDEX IF NOT EXISTS conversations_profile_name_idx ON conversations (profile_name);
CREATE INDEX IF NOT EXISTS messages_conversation_id_idx ON messages (conversation_id);
CREATE INDEX IF NOT EXISTS messages_created_at_idx ON messages (created_at ASC);

-- 5. Match Pairs Similarity RPC Function
-- Enables PostgREST REST API to trigger fast cosine similarity searches via /rpc/match_pairs
CREATE OR REPLACE FUNCTION match_pairs (
  query_embedding vector(1024),
  match_threshold float,
  match_count int,
  p_profile_name text
)
RETURNS TABLE (
  id uuid,
  context text,
  response text,
  similarity float
)
LANGUAGE plpgsql
AS $$
BEGIN
  RETURN QUERY
  SELECT
    pairs.id,
    pairs.context,
    pairs.response,
    1 - (pairs.embedding <=> query_embedding) AS similarity
  FROM pairs
  WHERE pairs.profile_name = p_profile_name
    AND 1 - (pairs.embedding <=> query_embedding) > match_threshold
  ORDER BY pairs.embedding <=> query_embedding
  LIMIT match_count;
END;
$$;

