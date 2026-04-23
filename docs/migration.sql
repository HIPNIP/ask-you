-- ═══════════════════════════════════════════════════════════════════════
-- Ask-You — Supabase SQL Migration
-- ═══════════════════════════════════════════════════════════════════════
--
-- Open the Supabase SQL Editor for your project and run the appropriate
-- section below.
--
-- ═══════════════════════════════════════════════════════════════════════


-- ═══════════════════════════════════════════════════════════════════════
-- SECTION 1 — For brand new users (run this first):
-- Creates the knowledge table and match function from scratch.
-- ═══════════════════════════════════════════════════════════════════════

-- Enable pgvector (skip if already enabled in your project)
create extension if not exists vector;

-- Main knowledge table
create table if not exists knowledge (
  id          bigserial primary key,
  content     text      not null,
  embedding   vector(3072) not null,
  source_doc  text,
  chunk_index int
);



-- Similarity search function
create or replace function match_knowledge(
  query_embedding  vector(3072),
  match_threshold  float,
  match_count      int
)
returns table (
  content     text,
  source_doc  text,
  similarity  float
)
language sql stable
as $$
  select
    content,
    source_doc,
    1 - (embedding <=> query_embedding) as similarity
  from knowledge
  where 1 - (embedding <=> query_embedding) > match_threshold
  order by embedding <=> query_embedding
  limit match_count;
$$;


-- ═══════════════════════════════════════════════════════════════════════
-- SECTION 2 — For users migrating from ask-isaac (optional):
-- Run ONLY if you already have an "isaac_knowledge" table and
-- "match_isaac_knowledge" function from the original ask-isaac project.
-- This renames them in-place so no data is lost.
-- ═══════════════════════════════════════════════════════════════════════

-- Rename the old table (all existing rows are preserved)
alter table isaac_knowledge rename to knowledge;

-- Drop the old function
drop function if exists match_isaac_knowledge(vector, float, int);

-- Create the new function pointing at the renamed table
create or replace function match_knowledge(
  query_embedding  vector(3072),
  match_threshold  float,
  match_count      int
)
returns table (
  content     text,
  source_doc  text,
  similarity  float
)
language sql stable
as $$
  select
    content,
    source_doc,
    1 - (embedding <=> query_embedding) as similarity
  from knowledge
  where 1 - (embedding <=> query_embedding) > match_threshold
  order by embedding <=> query_embedding
  limit match_count;
$$;
