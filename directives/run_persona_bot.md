# SOP: Running the Persona Bot

This directive outlines the steps to run the chatbot interface, manage system prompts, load few-shot RAG retrieval contexts, and run the session history summarizer.

## Prerequisites
- Completed profile vectorization in Supabase (see `directives/build_persona.md`).
- Remote APIs and Database configured in `.env`:
  ```env
  GROQ_API_KEY=your_gsk_key_here
  COHERE_API_KEY=your_cohere_key_here
  SUPABASE_URL=your_supabase_project_url
  SUPABASE_SERVICE_ROLE_KEY=your_supabase_service_role_key
  ACCESS_PASSCODE=your_optional_access_passcode
  ```

## Steps

### 1. Launch the Serverless Application Locally
Start the Next.js development server:
```bash
npm run dev
```
This launches Next.js on `http://localhost:3000` and automatically proxies `/api/*` requests to the Python FastAPI backend (which runs on port 8000 via Next.js dev rules in `next.config.js` or via running the concurrent python worker).

### 2. Chat Processing Flow (FastAPI Backend)
The orchestration is divided into layers:
- **Layer 1 (System Prompt):** Loaded dynamically from the `profiles` table in Supabase, setting spelling, Hinglish ratio, signature vocabulary, message lengths, and punctuation habits.
- **Layer 2 (Context Retrieval):** 
  - Checks if the user's message is in the "dead zone" (short filler words like *ok, lol, bro*). If so, it retrieves a random sample of responses to avoid repetitive keyword matching.
  - Otherwise, calls Cohere Multilingual Embeddings API to generate a query vector.
  - Matches the query vector using pgvector cosine similarity against the `pairs` table, utilizing the HNSW index for sub-second responses.
- **Layer 3 (Tone Hinting):** Detects if the current message matches structural patterns (questions, casual conversation, emotional lines) and appends a tonal system prompt hint.
- **Layer 4 (Memory Summarization):** After 6 turns, compresses the earlier discussion history into a concise topic summary to preserve Groq context window space.
- **Layer 5 (Few-shot Prompt Construction):** Combines the above sections with the last 8 messages and sends the request to Groq LLM (defaults to `llama-3.3-70b-specdec`).

## Quality Assurance & Safeguards
- **Streak Blocker:** Ensures the chatbot does not send the same exact text message response back-to-back.
- **AI Bleed-Through Filter:** Strips typical LLM phrases like *"Here is a response as Anvesha:"* or *"I am an AI assistant"*.
- **Passcode Verification:** Restricts public api routes using header authentication.
