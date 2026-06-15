"""
build_embeddings.py — Run ONCE after build_persona.py to generate and upload
semantic embeddings to Supabase using the Cohere API.

Usage:
    python execution/build_embeddings.py
"""

import os
import sys
import json
import time
import httpx
from dotenv import load_dotenv

# Fix Windows console UTF-8 issues
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except AttributeError:
        pass

# Load environmental variables
load_dotenv()

COHERE_API_KEY            = os.getenv("COHERE_API_KEY", "")
SUPABASE_URL              = os.getenv("SUPABASE_URL", "")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")

# Resolve paths
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
PROFILE_PATH = os.path.join(PROJECT_ROOT, "persona_profile.json")


def print_env_instructions():
    print("=" * 65)
    print("❌ ERROR: Missing Required API Keys / Configurations in `.env`")
    print("=" * 65)
    print("Please add the following values to your `.env` file at the root:")
    print()
    if not COHERE_API_KEY:
        print("  COHERE_API_KEY=your_cohere_api_key_here")
        print("    -> Get a free developer key from: https://dashboard.cohere.com/")
    if not SUPABASE_URL:
        print("  SUPABASE_URL=https://your-project-ref.supabase.co")
        print("    -> Find in your Supabase dashboard: Project Settings -> API -> Project URL")
    if not SUPABASE_SERVICE_ROLE_KEY:
        print("  SUPABASE_SERVICE_ROLE_KEY=your_service_role_secret_key")
        print("    -> Find in Project Settings -> API -> Project API Keys (service_role secret)")
    print()
    print("Once configured, re-run this script!")
    print("=" * 65)


def embed_batch(texts: list[str]) -> list[list[float]] | None:
    """Call Cohere API to generate multilingual embeddings."""
    url = "https://api.cohere.com/v1/embed"
    headers = {
        "Authorization": f"Bearer {COHERE_API_KEY}",
        "Content-Type": "application/json",
        "accept": "application/json",
    }
    payload = {
        "texts": texts,
        "model": "embed-multilingual-v3.0",
        "input_type": "search_document",
        "embedding_types": ["float"]
    }
    
    # Retry logic
    for attempt in range(3):
        try:
            with httpx.Client(timeout=45.0) as client:
                res = client.post(url, json=payload, headers=headers)
                
                if res.status_code == 200:
                    data = res.json()
                    # Cohere v3 structure is: {"embeddings": {"float": [[...], ...]}}
                    return data["embeddings"]["float"]
                else:
                    print(f"  ⚠️  Cohere API returned {res.status_code}: {res.text}")
                    if res.status_code == 429: # Rate limit
                        time.sleep(2 ** attempt + 1)
                        continue
                    return None
        except Exception as e:
            print(f"  ⚠️  Cohere API request exception: {e}")
            time.sleep(2 ** attempt + 1)
            
    return None


def main():
    print("=" * 60)
    print("  Supabase Vector Embedding Generator (Cohere API)")
    print("=" * 60)

    # Validate environments
    if not COHERE_API_KEY or not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        print_env_instructions()
        sys.exit(1)

    # Validate profile exists
    if not os.path.exists(PROFILE_PATH):
        print(f"❌ '{PROFILE_PATH}' not found. Run python execution/build_persona.py first.")
        sys.exit(1)

    with open(PROFILE_PATH, encoding="utf-8") as f:
        profile = json.load(f)

    pairs = profile["pairs"]
    name = profile["name"]
    style = profile["style"]
    
    print(f"Profile loaded: {name}")
    print(f"Pairs to embed: {len(pairs):,}")

    # Step 1: Push / Upsert Profile Style DNA Card in Supabase
    print("\n[Step 1/3] Uploading Profile Style DNA Card to Supabase...")
    profile_url = f"{SUPABASE_URL.rstrip('/')}/rest/v1/profiles"
    headers = {
        "apikey": SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates" # postgrest upsert
    }
    # Ensure raw_samples is saved inside the style column in Supabase
    style_with_samples = {**style, "raw_samples": profile.get("raw_samples", [])}
    profile_payload = {
        "name": name,
        "style": style_with_samples
    }
    
    try:
        # We append ?on_conflict=name for PostgREST upsert
        res = httpx.post(f"{profile_url}?on_conflict=name", json=profile_payload, headers=headers, timeout=15.0)
        if res.status_code in (200, 201):
            print("  ✅ Profile DNA uploaded successfully.")
        else:
            print(f"  ❌ Failed to upload Profile DNA: {res.status_code} {res.text}")
            sys.exit(1)
    except Exception as e:
        print(f"  ❌ Supabase connection error: {e}")
        sys.exit(1)

    # Step 2: Delete old pairs for this profile to prevent duplication
    print("\n[Step 2/3] Cleaning up old vector pairs in Supabase...")
    pairs_url = f"{SUPABASE_URL.rstrip('/')}/rest/v1/pairs"
    try:
        res = httpx.delete(f"{pairs_url}?profile_name=eq.{name}", headers=headers, timeout=15.0)
        if res.status_code in (200, 204, 201):
            print("  ✅ Old database pairs cleared.")
        else:
            print(f"  ⚠️  Clean delete returned status: {res.status_code} {res.text}")
    except Exception as e:
        print(f"  ⚠️  Failed to clear old database pairs: {e}")

    # Step 3: Embed and Push in batches
    print("\n[Step 3/3] Generating vectors and uploading pairs...")
    
    batch_size = 96
    db_insert_batch_size = 200
    
    cohere_batches = [pairs[i:i + batch_size] for i in range(0, len(pairs), batch_size)]
    
    total_uploaded = 0
    pending_inserts = []
    
    start_time = time.time()
    
    for i, batch in enumerate(cohere_batches):
        pct = (i / len(cohere_batches)) * 100
        print(f"  Processing batch {i+1}/{len(cohere_batches)} ({pct:.1f}%)...")
        
        # In Cohere v3, we embed context + response together to capture context-response associations
        texts = [p["ctx"] + " " + p["resp"] for p in batch]
        
        vectors = embed_batch(texts)
        if not vectors or len(vectors) != len(batch):
            print("  ❌ Vector generation failed. Aborting pipeline.")
            sys.exit(1)
            
        for pair, vec in zip(batch, vectors):
            pending_inserts.append({
                "profile_name": name,
                "context": pair["ctx"],
                "response": pair["resp"],
                "embedding": vec
            })
            
        # Bulk upload to Supabase when buffer hits db_insert_batch_size or at the end
        if len(pending_inserts) >= db_insert_batch_size or i == len(cohere_batches) - 1:
            try:
                res = httpx.post(pairs_url, json=pending_inserts, headers=headers, timeout=30.0)
                if res.status_code in (200, 201, 204):
                    total_uploaded += len(pending_inserts)
                    # Clear buffer
                    pending_inserts = []
                else:
                    print(f"  ❌ Supabase batch upload failed: {res.status_code} {res.text}")
                    sys.exit(1)
            except Exception as e:
                print(f"  ❌ Supabase bulk insert exception: {e}")
                sys.exit(1)
                
    elapsed = time.time() - start_time
    print(f"\n✅ SUCCESS!")
    print(f"   Uploaded {total_uploaded:,} vectorized pairs to Supabase.")
    print(f"   Elapsed time: {elapsed:.1f}s (avg {total_uploaded/elapsed:.1f} pairs/sec).")
    
    # Save a local receipt in profile to indicate Supabase vector status
    profile["supabase_sync"] = True
    profile["embed_model"] = "cohere:embed-multilingual-v3.0"
    profile["embed_dim"] = 1024
    
    # Save back to disk (stripping raw text pairs to keep file extremely tiny for serverless deployment)
    profile["pairs"] = [] # Clear pairs locally (optional, but keeps local zip tiny!)
    profile["keyword_index"] = {} # Clear locally
    
    with open(PROFILE_PATH, "w", encoding="utf-8") as f:
        json.dump(profile, f, ensure_ascii=False, indent=2)
        
    print(f"   Saved sync receipt to {PROFILE_PATH}")
    print("\nMonorepo Backend is ready. Proceed to run: npm run dev")


if __name__ == "__main__":
    main()
