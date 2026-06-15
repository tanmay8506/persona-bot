# Project Plan: Persona Bot (Next.js + FastAPI + Supabase Monorepo)

This project aims to build a high-fidelity, production-grade persona-cloning chatbot. The system ingests conversation logs (WhatsApp `.txt` or Instagram `.html`/`.json`), pre-processes and structures them, extracts personality style parameters, and provides a polished React chat interface where the user can talk to the clone.

---

## 🏗️ Core Architecture & Tech Stack

To ensure seamless one-click deployment on **Vercel** with zero-latency cold starts, robust data handling, and zero local ML dependencies, the project uses a **Serverless Monorepo** architecture:

*   **Frontend:** Next.js (React, TypeScript, TailwindCSS, shadcn/ui) hosted on Vercel.
*   **Backend:** FastAPI serverless functions running inside the Next.js `/api` folder.
*   **Database (Vector & Chat History):** **Supabase PostgreSQL** utilizing the **`pgvector`** extension for semantic searches and permanent storage of user chat sessions.
*   **LLM API:** **Groq** running **`llama-3.3-70b-specdec`** (flagship Llama 3.3 model with speculative decoding for ultra-low latency and Hinglish comprehension).
*   **Embedding API:** **Cohere Multilingual Embeddings** (v3, 1024-dimensional) via API, keeping Vercel package size under the 250MB limit by avoiding heavy local dependencies.

---

## 🛠️ Development Phases

### Phase 1: High-Signal Ingestion & Pre-processing (Priority 1)
*   **Multi-Pattern WhatsApp Parsing:** Test multiple common WhatsApp timestamp regex patterns (Standard US/EU formats, iOS bracketed formats) to auto-detect and adapt to different regional phone exports.
*   **Line-Buffering for WhatsApp:** Buffer and append lines that do not start with a timestamp to the body of the previous message to prevent multi-line text truncation.
*   **Chronological HTML & JSON Parsing:** Instagram HTML/JSON files list messages in reverse-chronological order (newest first). The parser extracts message timestamps, parses them into datetime objects using a robust multi-format date parser, and sorts all extracted messages chronologically *before* performing turn grouping and pair building.
*   **Time-Gap turn boundary checks:** Group messages into turns only when sent consecutively. Do not merge messages or create pairs across a gap of >2 hours of conversation inactivity, and never across different files.
*   **Burst-Merging:** Join consecutive messages sent by the same person within a 2-minute window using `\n` linebreaks.
*   **Quality Filtering:** Clean out media indicators (e.g., `IMG-....jpg (file attached)`), system messages ("deleted this message", "end-to-end encrypted"), and null values.
*   **PII & Privacy Scrubbing:** Run a regex-based PII masking filter to replace phone numbers, email addresses, and private card details with placeholders (e.g., `[Phone]`, `[Email]`) before saving to the database.

### Phase 2: Style DNA Extraction & Vectorization (Priority 2)
*   **Style DNA Card Generator:** Analyze the target's messages to extract key statistical style properties:
    *   *Opener frequency* (top 15 words used to start a message turn).
    *   *Language ratio* (Hinglish/Hindi words vs. English).
    *   *Emoji distribution* (stacked emoji usage, favorite emojis).
    *   *Punctuation rules* (capitalization habits, end-of-text periods, question marks).
    *   *Message length distribution* (short burst ratio vs. long paragraph ratio).
*   **Supabase Ingestion (Bulk Batching):** Send pairs to Cohere Multilingual Embeddings API in batches of 96. Perform bulk inserts (e.g., 200 pairs per request) into Supabase PostgreSQL to prevent network roundtrip timeouts.

### Phase 3: Conversational Memory & Storage (Storage Layer)
*   **Session Management:** Store user sessions and message history in relational PostgreSQL tables in Supabase (fully persistent, no Vercel idle deletion).
*   **Supabase HTTP REST Interface:** Connect the FastAPI backend to Supabase via its stateless REST API to avoid connection pool exhaustion typical of serverless functions.
*   **Fast Vector Indexing:** Set up an HNSW (Hierarchical Navigable Small World) index on the vector embeddings column to guarantee sub-second vector search times, keeping the serverless response time far below Vercel's 10-second timeout boundary.

### Phase 4: Prompt Engineering & LLM Orchestration (Priority 3)
*   **Dynamic System Prompting:** Inject the extracted "Style DNA Card" directly into the system instructions to enforce writing styles (e.g., lowercase only, emoji constraints).
*   **Few-Shot Copycat Injection:** For every incoming user message:
    1. Check for "dead zone" filler messages (e.g., "ok", "lol") to avoid repetitive retrieval.
    2. Search the database using `pgvector` cosine similarity to find the top 3 most contextually relevant past turns.
    3. Inject these real-life turns directly into the prompt as few-shot examples.
*   **Temporal Awareness Context:** Dynamically inject the active local timestamp, day of the week, and date into the context of every user-assistant turn to align LLM behaviors with current time realities.
*   **Groq Inference:** Call Groq Llama 3.3 70B model with a balanced temperature (0.85) and frequency/presence penalties to prevent repetitive styling.

### Phase 5: Frontend Interface (Presentation Layer)
*   **Setup Tab:** Interface to paste API keys, input target names, and upload chat files.
*   **Chat Tab:** A clean, messaging-app-style UI with responsive scrolling, supporting:
    *   Split-message burst rendering.
    *   Visual status indicators (loading/typing).

---

## 🎨 Aesthetics & Design System

*   **Theme Factory:**
    *   *Palette:* Charcoal (`#1a1a1a`) as primary dark background, Dark Gray (`#2d2d2d`) for cards/bubbles, Slate Gray (`#708090`) for accents, and White (`#ffffff`) for text.
    *   *Typography:* Google Fonts pairing *Inter* (body text) and *Outfit* (headers).
*   **Taste Design:**
    *   *Design Style:* Minimalist, high visual density (tight message bubbles, removing standard loose padding blocks).
    *   *Motion:* Smooth CSS transitions for hover states, message fades, and typing indicator dots.

---

## 🛡️ Risk Mitigation & Architectural Safeguards

### 1. React "Burst Texting" Bubble Rendering
*   **Risk:** Reconstructing text containing newlines (`\n`) as a single huge bubble ruins the texting look.
*   **Fix:** Write a custom component in React that splits the assistant output by `\n` and maps over it to render consecutive, styled message bubbles natively in JSX.

### 2. Token Budgeting & Groq Rate Limits
*   **Risk:** Excessive token consumption from system prompts, memory summary, active history, and RAG context causing API rate crashes.
*   **Fix:** Limit the total prompt context to 1,500 tokens: System (200 tokens), RAG Few-shot examples (max 3 pairs / 500 tokens), Active Session (max 8 turns / 600 tokens).

### 3. "Dead Zone" Retrieval Fallback
*   **Risk:** Short filler messages (e.g., "ok", "cool") causing semantic search to retrieve irrelevant past conversation topics.
*   **Fix:** Automatically intercept "dead zone" inputs, bypass semantic search, and return a randomized selection of the persona's own historical replies to that specific filler word.

### 4. AI Bleed-through Filter
*   **Risk:** LLM leaking its identity by outputting phrases like *"As an AI..."* or *"As Anvesha, I would..."*
*   **Fix:** Implement a post-processing regex block at the output layer. If the generated message triggers the filter, discard the output and silently trigger a rerun of the LLM call.

### 5. Latin-Script Hinglish Enforcer
*   **Risk:** LLMs responding in Devanagari script (e.g. `क्या कर रही हो`) or formal dictionary Hindi when prompted to text in Hinglish.
*   **Fix:** Explicitly forbid Devanagari script in system prompts and lock down spelling conventions of frequently used words (e.g., enforce `nhi` instead of `nahi`, `rhi` instead of `rahi`).

### 6. Serverless Database Connection Exhaustion
*   **Risk:** Vercel serverless functions spinning up and down and exhausting Supabase's database connection pool limit (max 60).
*   **Fix:** Connect FastAPI to Supabase using the stateless **Supabase HTTP Data API (REST)** instead of a raw SQL client to auto-pool connections.

### 7. Python Dependency Version Conflicts on Vercel
*   **Risk:** Large machine learning libraries (e.g. `torch`, `sentence-transformers`) failing to compile or exceeding the 250MB package limit on Vercel.
*   **Fix:** Keep `requirements.txt` extremely clean and lean by offloading embeddings to Cohere API. The only dependencies are: `fastapi`, `supabase`, `groq`, `beautifulsoup4`, `python-dotenv`, `httpx`, and `cohere` (guaranteeing 100% build success on Vercel).

### 8. next.config.js Proxy Rewrite
*   **Risk:** Browser blocking API requests from React frontend (localhost:3000) to FastAPI backend (localhost:8000) due to CORS policies during local testing.
*   **Fix:** Configure Next.js Rewrites in `next.config.js` to proxy `/api/*` requests to the local Python FastAPI port transparently, eliminating local CORS headers errors.

### 9. Access Passcode Protection
*   **Risk:** Anyone visiting the public Vercel deployment URL could abuse the bot, uploading giant files and draining the host's Groq and Cohere API credits.
*   **Fix:** Define an optional `ACCESS_PASSCODE` in Vercel environment variables. If set, require the user to input this passcode on the setup tab, storing it in the client browser's `localStorage` and passing it in request authorization headers.
