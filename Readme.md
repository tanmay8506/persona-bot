# 🎭 Persona Bot

An impressive, high-fidelity persona-cloning chatbot that parses private chat logs (WhatsApp `.txt` or Instagram `.html`), extracts statistical style profiles, and hosts a premium messaging UI to chat with the digital clone.

Deployed in one click through **Vercel** with a serverless monorepo architecture.

---

## 🏗️ Next-Gen Tech Stack

*   **Frontend:** [Next.js](https://nextjs.org/) (React 19, TypeScript, TailwindCSS, [shadcn/ui](https://ui.shadcn.com/))
*   **Backend:** [FastAPI](https://fastapi.tiangolo.com/) (Python 3, running as serverless functions in Vercel’s `/api` folder)
*   **Database:** [Supabase](https://supabase.com/) PostgreSQL with the **`pgvector`** extension for persistent session memory and semantic searches
*   **LLM API:** [Groq](https://groq.com/) running **`llama-3.3-70b-specdec`** (flagship Speculative Decoded Llama 3.3 model for ultra-low latency and Hinglish comprehension)
*   **Embedding API:** [Cohere Multilingual Embeddings](https://cohere.com/) for Hinglish-friendly cross-lingual semantic matching

---

## 🛡️ Core Features & Safeguards

1.  **Ingestion & Burst-Merging:** Cleans raw chat logs, reverses Instagram HTML files to chronological order, merges consecutive text messages into linebreaks, and scrubs PII (emails, phone numbers, cards).
2.  **Style DNA Extraction:** Automatically profiles target texting habits (opener vocabulary, Hinglish ratios, favorite emojis, capitalization, and punctuation rules).
3.  **Few-Shot Copycat Retrieval:** Uses semantic cosine similarity in `pgvector` to inject 3 real past conversation turns as examples before the current chat message.
4.  **Temporal Awareness:** Dynamically injects local dates, days, and times to align character greetings and mood states with reality.
5.  **Output Filters:** Blocks AI-isms ("As an AI...") and prevents back-to-back duplicate responses.
6.  **Beautiful Minimalist UI:** Premium, high-density styled chat interface with custom HTML bubble rendering for texting bursts.