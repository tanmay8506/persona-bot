# SOP: Building the Persona Profile

This directive outlines the process to clean, parse, filter, and vectorize raw chat files into a structured persona profile stored in Supabase.

## Inputs
- **WhatsApp Chat Logs**: `.txt` export from WhatsApp (Settings -> Chats -> Export chat -> Without media).
- **HTML Message Logs**: Exports from Instagram or Facebook Messenger (`message_1.html`, etc.).
- Store raw files in the `files/` directory.

## Steps

### 1. Configuration
Open `execution/build_persona.py` and modify the CONFIG block:
- `TARGET_NAME`: The name of the person you want to clone (e.g., "Anvesha").
- `TARGET_ALIASES`: Any variants of their name in the chat logs.
- `CHAT_FILES`: List of tuples containing `(path, type)` for all exports.

### 2. Parse & Construct Pairs
Run the script to parse the files and compute style parameters:
```bash
python execution/build_persona.py
```
This script does the following:
- Cleans and parses WhatsApp patterns (handling multiple formats and line buffering for newlines).
- Parses Instagram HTML chronologically (sorting all messages across files by timestamp).
- Filters cross-file boundaries and communication gaps (>2 hours).
- Filters out system messages, media logs, and applies regex-based PII scrubbing.
- Computes style distribution cards (Hinglish ratio, message lengths, signature words).
- Outputs `persona_profile.json` (temporary structure without vectors).

### 3. Generate Semantic Embeddings & Write to Supabase
Vectorize the conversation pairs using the Cohere API and store them in Supabase:
```bash
python execution/build_embeddings.py
```
This script:
- Loads the style card and pairs from `persona_profile.json`.
- Calls Cohere Multilingual Embeddings v3 API in batches of 96 to generate 1024-dimensional vector embeddings.
- Connects to Supabase via the HTTP REST Data API.
- Inserts the style card into the `profiles` table.
- Inserts pairs and their 1024-dimensional vectors into the `pairs` table in bulk batches of 200 to prevent connection timeouts.

## Outputs
- **Supabase Database:** `profiles` row and corresponding vectorized `pairs` rows.
