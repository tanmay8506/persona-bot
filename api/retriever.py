"""
api/retriever.py — Cohere Embeddings client & Supabase vector semantic search matching.
"""

import os
import httpx
from dotenv import load_dotenv
from api.database import get_supabase_rest_url, get_headers, get_profile

load_dotenv()

COHERE_API_KEY = os.getenv("COHERE_API_KEY", "")

def get_cohere_headers() -> dict:
    if not COHERE_API_KEY:
        raise ValueError("COHERE_API_KEY is not configured in environment variables.")
    return {
        "Authorization": f"Bearer {COHERE_API_KEY}",
        "Content-Type": "application/json",
        "accept": "application/json",
    }


def embed_query(text: str) -> list[float] | None:
    """Embed the user input query using Cohere Multilingual v3 (1024d)."""
    url = "https://api.cohere.com/v1/embed"
    payload = {
        "texts": [text],
        "model": "embed-multilingual-v3.0",
        "input_type": "search_query", # Query type for retrieval
        "embedding_types": ["float"]
    }
    try:
        with httpx.Client(timeout=10.0) as client:
            res = client.post(url, json=payload, headers=get_cohere_headers())
            if res.status_code == 200:
                data = res.json()
                return data["embeddings"]["float"][0]
            else:
                print(f"Cohere query embed API returned error {res.status_code}: {res.text}")
    except Exception as e:
        print(f"Error calling Cohere query embed: {e}")
    return None


def semantic_retrieve(profile_name: str, query: str, limit: int = 3) -> list[dict]:
    """Retrieve top k matched context-response pairs using Supabase pgvector RPC."""
    query_vector = embed_query(query)
    if not query_vector:
        print("Embedding failed, falling back to empty retrieval.")
        return []

    # Call PostgREST RPC match_pairs function
    # Endpoint is: POST /rest/v1/rpc/match_pairs (Note: /rest/v1/rpc/<func-name>)
    # For Supabase REST URL, if get_supabase_rest_url returns /rest/v1/pairs, we modify it to /rest/v1/rpc/match_pairs
    base_url = get_supabase_rest_url("rpc/match_pairs")
    
    payload = {
        "query_embedding": query_vector,
        "match_threshold": 0.35, # Cosine similarity threshold
        "match_count": limit,
        "p_profile_name": profile_name
    }
    
    try:
        with httpx.Client(timeout=15.0) as client:
            res = client.post(base_url, json=payload, headers=get_headers())
            if res.status_code == 200:
                return res.json()
            else:
                print(f"Supabase RPC match_pairs returned error {res.status_code}: {res.text}")
    except Exception as e:
        print(f"Exception during semantic retrieval: {e}")
        
    return []


def retrieve_few_shots(profile_name: str, query: str, limit: int = 3) -> list[dict]:
    """
    Retrieves the best few-shot context-response pairs.
    Bypasses vector search for short 'dead zone' filler inputs, returning diverse
    random samples from target's historical replies to simulate natural flow.
    """
    # Check if message is a short dead zone filler word
    import re
    from api.llm import is_dead_zone # imported dynamically or defined locally
    
    # Minimal dead zone check to avoid circular import if needed
    clean = re.sub(r'[^\w\s]', '', query.lower()).strip()
    words = set(clean.split())
    
    dead_zone_words = {
        "ok","okay","k","hm","hmm","what","why","how","hi","hey","hello","bye",
        "yes","no","sure","fine","nice","good","bad","lol","haha","omg","really",
        "oh","ah","ugh","bro","man","dude","wait","stop","go","come","see",
    }
    
    if len(words) <= 2 and words.issubset(dead_zone_words):
        # Retrieve short samples from profile style data as fallbacks
        p = get_profile(profile_name)
        raw_samples = []
        if p:
            if "raw_samples" in p:
                raw_samples = p["raw_samples"]
            elif "style" in p and "raw_samples" in p["style"]:
                raw_samples = p["style"]["raw_samples"]
                
        if raw_samples:
            # Pick a few random raw samples of short lengths
            import random
            short_samples = [s for s in raw_samples if len(s.split()) <= 4]
            if not short_samples:
                short_samples = raw_samples
            samples = random.sample(short_samples, min(limit, len(short_samples)))
            # Format like matched pairs using keys expected by llm.py (ctx and resp)
            return [{"ctx": "...", "resp": s} for s in samples]
            
    # Otherwise run semantic retrieval
    matches = semantic_retrieve(profile_name, query, limit)
    # Map key names from 'response'/'context' in pgvector function output
    return [{"ctx": m["context"], "resp": m["response"]} for m in matches]
