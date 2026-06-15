"""
Persona Bot — app.py  v3.0

Architecture:
  LAYER 1: Pinned system prompt (identity + style, ~100 tokens, never changes)
  LAYER 2: Few-shot pairs as real user/assistant turns (semantic or keyword RAG)
  LAYER 3: Tonal context hint (emotional/excited/planning/question/casual)
  LAYER 4: Session memory — compressed topic summary after 6+ turns
  LAYER 5: Live conversation — last 8 turns
  LAYER 6: Current message

Fixes in this version:
  - Dead zone handling: short/filler messages get random diverse pairs
  - Rate limit retry with exponential backoff
  - Response quality filter (catches AI bleed-through)
  - Streak detection: blocks same response twice in a row
  - Exact dedup removed from profile at load time
  - Session memory is topic-compressed, not a raw transcript dump
  - Language ratio detection per message (more Hindi → more Hindi examples)
"""

import os, re, json, time, random
import numpy as np
import gradio as gr
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

GROQ_API_KEY    = os.getenv("GROQ_API_KEY", "")
client          = None
profile         = None
PINNED_SYSTEM   = ""
EMBED_MATRIX    = None
SEMANTIC_ACTIVE = False


# ── Profile loader ────────────────────────────────────────────────────────────

def load_profile(path: str = "persona_profile.json") -> dict | None:
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def clean_profile_pairs(pairs: list[dict]) -> list[dict]:
    """
    Final dedup pass at load time — removes any exact duplicates
    that slipped through build_persona.py.
    Also removes self-referential responses where Anvesha mentions herself.
    """
    seen   = set()
    clean  = []
    for pair in pairs:
        key = re.sub(r'[^\w]', '', pair['resp'].lower())[:50]
        # Remove self-ref (bot referring to itself by name in response)
        if re.search(r'\banvesha\b', pair['resp'], re.I):
            continue
        if key in seen:
            continue
        seen.add(key)
        clean.append(pair)
    return clean


# ── LAYER 1: Pinned system prompt ────────────────────────────────────────────

def build_pinned_system(p: dict) -> str:
    name  = p["name"]
    style = p["style"]
    hind  = style["hinglish"]

    hindi_vocab = {
        "yr","arre","kya","ni","mein","kr","bhi","hn","rhi","rha","hun",
        "fir","toh","yaar","nhi","aur","haan","nahi","abhi","kuch","acha",
        "matlab","chal","theek","mai","hu","thi","tha","isliye","becoz","usse",
    }
    sig_hindi = [w for w in style["top_words"][:20] if w in hindi_vocab]
    sig_all   = style["top_words"][:10]

    hinglish_line = (
        f"Mix Hindi+English mid-sentence naturally ({hind*100:.0f}% of your messages do). "
        f"Hindi words you use a lot: {', '.join(sig_hindi[:10])}"
        if hind > 0.3 else "Write mostly in English."
    )

    solo_q   = "Send '?' alone to mean 'what?'/'huh?' — you do this a lot." if style["solo_q"]  > 15 else ""
    solo_dot = "Send '.' alone as a dry or dismissive reaction."             if style["solo_dot"] > 5  else ""

    short_pct = int(style["short_ratio"] * 100)
    long_pct  = int(style["long_ratio"]  * 100)

    return (
        f"You are {name}. Not an AI — you ARE {name}, texting on WhatsApp.\n\n"
        f"STYLE ({p['total_messages']:,} real messages):\n"
        f"- {short_pct}% of replies are 1-4 words. {long_pct}% are 15+ words. Read the energy.\n"
        f"- {hinglish_line}\n"
        f"- Skip capitals and punctuation like a real texter\n"
        f"- {solo_q} {solo_dot}\n"
        f"- Split long thoughts across separate short lines (natural burst texting)\n"
        f"- Your signature words: {', '.join(sig_all)}\n\n"
        f"NEVER: be formal · say 'As {name}...' · admit being AI · use bullet points · "
        f"ignore what they said · repeat yourself · give generic responses\n\n"
        f"Real examples of how you text are injected below as conversation turns."
    )


# ── Message language detector ─────────────────────────────────────────────────

HINDI_SET = {
    "yr","yaar","arre","kya","kuch","nahi","nhi","haan","hn","mein","abhi",
    "chal","theek","acha","bata","sun","kal","aaj","kyun","matlab","bas","phir",
    "rhi","rha","hun","fir","toh","aur","kr","bhi","ni","hu","mai","tu","vo",
    "tha","thi","woh","usse","tujhe","mujhe","hum","unhe","inhe","kisi","sab",
    "isko","usko","apna","apni","kyunki","isliye","waise","accha","sach",
}

def message_lang_ratio(message: str) -> float:
    """Returns fraction of words that are Hindi. 0=all English, 1=all Hindi."""
    words = message.lower().split()
    if not words:
        return 0.0
    hindi_count = sum(1 for w in words if w in HINDI_SET)
    return hindi_count / len(words)


# ── Dead zone detector ───────────────────────────────────────────────────────

DEAD_ZONE_MSGS = {
    "ok","okay","k","hm","hmm","what","why","how","hi","hey","hello","bye",
    "yes","no","sure","fine","nice","good","bad","lol","haha","omg","really",
    "oh","ah","ugh","bro","man","dude","wait","stop","go","come","see",
}

def is_dead_zone(message: str) -> bool:
    """True if message is too short/generic for keyword retrieval to work."""
    clean = re.sub(r'[^\w\s]', '', message.lower()).strip()
    words = set(clean.split())
    return len(words) <= 2 and words.issubset(DEAD_ZONE_MSGS)


# ── LAYER 2: RAG retriever ────────────────────────────────────────────────────

STOPWORDS = {
    "the","and","for","you","but","was","with","that","this","are","have","not",
    "from","they","will","been","what","when","who","how","him","her","his","she",
    "he","we","our","your","just","okay","ok","yeah","yes","no","oh","hmm","ah","i",
}

def tokenise(message: str) -> set[str]:
    alpha = set(w for w in re.findall(r"[a-zA-Z']+", message.lower()) if len(w)>2 and w not in STOPWORDS)
    hindi = set(w for w in message.lower().split() if w in HINDI_SET and len(w)>1)
    return alpha | hindi


def semantic_retrieve(message: str, p: dict, top_k: int) -> list[dict]:
    """Cosine similarity over embedding matrix."""
    global EMBED_MATRIX
    try:
        if not hasattr(semantic_retrieve, "_model"):
            from sentence_transformers import SentenceTransformer
            semantic_retrieve._model = SentenceTransformer(p.get("embed_model", "all-MiniLM-L6-v2"))
        q_vec  = semantic_retrieve._model.encode([message], normalize_embeddings=True)[0]
        scores = EMBED_MATRIX @ q_vec
        top_i  = np.argsort(scores)[::-1]
        pairs  = p["pairs"]
        seen, selected = set(), []
        for idx in top_i:
            rp = pairs[idx]["resp"][:30]
            if rp not in seen:
                seen.add(rp)
                selected.append(pairs[idx])
            if len(selected) >= top_k:
                break
        return selected
    except Exception:
        return keyword_retrieve(message, p, top_k)


def keyword_retrieve(message: str, p: dict, top_k: int) -> list[dict]:
    """Keyword index retrieval with Hindi-aware tokenisation."""
    pairs   = p["pairs"]
    kw_idx  = p["keyword_index"]
    words   = tokenise(message)

    scores: dict[int, int] = {}
    for w in words:
        for idx in kw_idx.get(w, []):
            scores[idx] = scores.get(idx, 0) + 1

    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)

    # Dead zone fallback — no keyword hits, return diverse spread
    if not ranked:
        step = max(1, len(pairs) // top_k)
        return pairs[::step][:top_k]

    seen, selected = set(), []
    for idx, _ in ranked:
        rp = pairs[idx]["resp"][:30]
        if rp not in seen:
            seen.add(rp)
            selected.append(pairs[idx])
        if len(selected) >= top_k:
            break

    # Pad with fallback if not enough hits
    if len(selected) < top_k // 2:
        step = max(1, len(pairs) // top_k)
        for item in pairs[::step][:top_k * 2]:
            if len(selected) >= top_k:
                break
            if item["resp"][:30] not in seen:
                selected.append(item)
    return selected


def retrieve(message: str, p: dict, top_k: int = 6) -> list[dict]:
    """
    Smart retrieval:
    - Dead zone messages → random diverse pairs (no point searching)
    - Hindi-heavy messages → bias toward Hinglish pairs
    - Otherwise → semantic or keyword
    """
    pairs = p["pairs"]

    if is_dead_zone(message):
        # Pick random spread — dead zone msgs need diverse examples, not specific ones
        indices = random.sample(range(len(pairs)), min(top_k * 3, len(pairs)))
        # Prefer pairs with short responses (matches the energy of short messages)
        short = [pairs[i] for i in indices if len(pairs[i]["resp"].split()) <= 6]
        return (short + [pairs[i] for i in indices])[:top_k]

    # Language-aware: if message is mostly Hindi, boost Hindi pairs
    lang_ratio = message_lang_ratio(message)
    if SEMANTIC_ACTIVE:
        retrieved = semantic_retrieve(message, p, top_k * 2)
    else:
        retrieved = keyword_retrieve(message, p, top_k * 2)

    if lang_ratio > 0.5:
        # Prefer pairs where response has Hindi words
        hindi_first = sorted(
            retrieved,
            key=lambda pair: sum(1 for w in pair["resp"].lower().split() if w in HINDI_SET),
            reverse=True,
        )
        return hindi_first[:top_k]

    return retrieved[:top_k]


def pairs_to_turns(pairs: list[dict]) -> list[dict]:
    """Convert pairs to real user/assistant message turns."""
    turns = []
    for pair in pairs:
        ctx  = pair["ctx"].strip()
        resp = pair["resp"].strip()
        if ctx and resp:
            turns.append({"role": "user",      "content": ctx})
            turns.append({"role": "assistant",  "content": resp})
    return turns


# ── LAYER 3: Tonal context ────────────────────────────────────────────────────

TONE_PATTERNS = {
    "emotional": {
        "sad","miss","hurt","cry","ro","dard","lonely","scared","worried",
        "love","pyaar","dil","feeling","feel","bad","bura","upset","depressed",
        "anxious","overwhelmed","tired","exhausted","broken","lost",
    },
    "excited": {
        "omg","omgg","!!!","yay","amazing","wow","great","best","finally",
        "hogya","mil gya","kya baat","shitt","shiit","🥳","🎉","can't believe",
    },
    "humor": {
        "haha","lol","lmao","funny","joke","mazak","😂","🤣","bruh","bro seriously",
        "kidding","sach mein","seriously","wait what",
    },
    "question":  {"?"},
    "planning": {
        "chal","milte","meet","kab","when","plan","aana","jaana","kal","aaj",
        "time","kahan","where","shall","lets","movie","dinner","lunch","coffee",
    },
}

TONE_HINTS = {
    "emotional": (
        "They're going through something emotional. Respond with genuine care — "
        "ask what happened, acknowledge their feelings. Don't brush it off."
    ),
    "excited": "They're excited. Match that energy — be enthusiastic back.",
    "humor":   "They're being funny or joking around. Play along, banter back.",
    "question": "They asked you something specific. Actually answer it in your texting style.",
    "planning": "They're talking about meeting up or making plans. Respond naturally to that.",
}

def detect_tone(message: str, history: list[dict]) -> str:
    text = message.lower()
    # Include last 2 user messages for better context
    recent = " ".join(h["content"].lower() for h in history[-4:] if h["role"] == "user")
    combined = text + " " + recent

    for tone, keywords in TONE_PATTERNS.items():
        if tone == "question":
            if "?" in message: return "question"
        elif any(w in combined for w in keywords):
            return tone
    return "casual"


# ── LAYER 4: Session memory (topic-compressed) ────────────────────────────────

TOPIC_WORDS = {
    "college": {"clg","college","class","exam","lecture","professor","bunk","attendance","prac","practical","assignment","semester","notes"},
    "friends": {"friend","yaar","yr","bhai","dost","gang","group","party","outing","hangout"},
    "feelings":{"sad","miss","hurt","love","worried","scared","lonely","happy","excited","bored","anxious","feel","feeling"},
    "plans":   {"meet","milte","chal","plan","kal","aaj","movie","dinner","lunch","coffee","time","kahan","when","shall"},
    "family":  {"mom","mummy","dad","papa","bhai","didi","ghar","home","parents","brother","sister"},
    "work":    {"job","internship","project","assignment","submit","deadline","office","work","career"},
}

def extract_topics(history: list[dict]) -> list[str]:
    text = " ".join(h["content"].lower() for h in history)
    found = []
    for topic, words in TOPIC_WORDS.items():
        if any(w in text for w in words):
            found.append(topic)
    return found

def build_session_memory(history: list[dict], name: str) -> str:
    """
    Compressed topic-level summary instead of raw transcript dump.
    Much more token-efficient and useful than just repeating messages.
    """
    if len(history) < 6:
        return ""

    topics = extract_topics(history)
    turns  = len(history) // 2

    # Get last user message for immediate context
    last_user = next((h["content"][:80] for h in reversed(history) if h["role"] == "user"), "")
    last_self = next((h["content"][:80] for h in reversed(history) if h["role"] == "assistant"), "")

    summary = f"[Session: {turns} exchanges"
    if topics:
        summary += f" · Topics: {', '.join(topics)}"
    summary += f"]\nLast thing they said: {last_user}"
    summary += f"\nLast thing {name} said: {last_self}"
    summary += "\n[Continue from here — don't restart, don't repeat]"

    return summary


# ── Response quality filter ───────────────────────────────────────────────────

BAD_PATTERNS = [
    re.compile(r"^(As |I am |I'm )", re.I),
    re.compile(r"\b(language model|I am an AI|artificial intelligence|I cannot|I don't have access)\b", re.I),
    re.compile(r"^\*\w"),                         # asterisk action: *laughs*
    re.compile(r"^(Hello!|Hi there|Hey there)", re.I),
    re.compile(r"\bAnvesha:\s*", re.I),           # self-labelling
]

def is_bad_response(reply: str) -> bool:
    return any(p.search(reply) for p in BAD_PATTERNS)

def clean_response(reply: str) -> str:
    # Strip self-name prefix if model adds it
    reply = re.sub(r"^\[?As \w+[,:\]]?\s*", "", reply, flags=re.I)
    reply = re.sub(r"^(\w+):\s*", lambda m: "" if m.group(1)[0].isupper() else m.group(0), reply)
    reply = re.sub(r"^\*[^*]+\*\s*", "", reply)   # strip *action* prefix
    return reply.strip()


# ── Streak detector ───────────────────────────────────────────────────────────

def get_last_reply(history: list[dict]) -> str:
    for h in reversed(history):
        if h["role"] == "assistant":
            return h["content"]
    return ""

def is_repeat(new_reply: str, last_reply: str) -> bool:
    """True if new reply is too similar to last reply."""
    if not last_reply:
        return False
    a = re.sub(r'[^\w]', '', new_reply.lower())[:60]
    b = re.sub(r'[^\w]', '', last_reply.lower())[:60]
    # Exact match or >80% character overlap
    if a == b:
        return True
    min_len = min(len(a), len(b))
    if min_len == 0:
        return False
    overlap = sum(1 for ca, cb in zip(a, b) if ca == cb)
    return overlap / min_len > 0.8


# ── Rate limit retry ──────────────────────────────────────────────────────────

def call_groq_with_retry(messages: list[dict], max_retries: int = 3) -> str:
    """
    Call Groq API with exponential backoff on rate limit errors.
    """
    for attempt in range(max_retries):
        try:
            response = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=messages,
                temperature=0.92,
                max_tokens=200,
                frequency_penalty=0.45,
                presence_penalty=0.3,
            )
            return response.choices[0].message.content.strip()

        except Exception as e:
            err = str(e)
            if "rate_limit" in err.lower() or "429" in err:
                wait = (2 ** attempt) + random.uniform(0, 1)
                if attempt < max_retries - 1:
                    time.sleep(wait)
                    continue
                else:
                    return f"⚠️ Rate limit hit. Wait a moment and try again. (Tip: Groq free tier = 6k tokens/min on 70b)"
            elif "context_length" in err.lower():
                return "⚠️ Message too long for context window."
            else:
                return f"⚠️ Error: {err[:100]}"
    return "⚠️ Failed after retries."


# ── Message assembler ─────────────────────────────────────────────────────────

def build_messages(message: str, history: list[dict], p: dict) -> list[dict]:
    name = p["name"]

    # Layer 1: pinned identity
    msgs = [{"role": "system", "content": PINNED_SYSTEM}]

    # Layer 2: few-shot examples as real turns
    relevant = retrieve(message, p, top_k=6)
    msgs.extend(pairs_to_turns(relevant))

    # Layer 3: tonal hint
    tone = detect_tone(message, history)
    hint = TONE_HINTS.get(tone, "")
    if hint:
        msgs.append({"role": "system", "content": hint})

    # Layer 4: compressed session memory
    memory = build_session_memory(history, name)
    if memory:
        msgs.append({"role": "system", "content": memory})

    # Layer 5: live conversation (last 8 turns)
    msgs.extend(history[-8:] if len(history) > 8 else history)

    # Layer 6: current message
    msgs.append({"role": "user", "content": message})

    return msgs


# ── Gradio logic ──────────────────────────────────────────────────────────────

def initialise():
    global client, profile, PINNED_SYSTEM, EMBED_MATRIX, SEMANTIC_ACTIVE

    if not GROQ_API_KEY:
        return "❌ GROQ_API_KEY not found in .env"

    client = Groq(api_key=GROQ_API_KEY)
    p = load_profile("persona_profile.json")
    if not p:
        return "❌ persona_profile.json not found. Run build_persona.py first."

    # Clean profile at load time
    original_count = len(p["pairs"])
    p["pairs"]     = clean_profile_pairs(p["pairs"])
    removed        = original_count - len(p["pairs"])

    profile       = p
    PINNED_SYSTEM = build_pinned_system(p)

    # Load embeddings
    if "embeddings" in p:
        try:
            EMBED_MATRIX    = np.array(p["embeddings"], dtype=np.float32)
            SEMANTIC_ACTIVE = True
            rag_status = f"✅ Semantic RAG · {p.get('embed_model','?')} · {EMBED_MATRIX.shape[1]}d"
        except Exception as e:
            SEMANTIC_ACTIVE = False
            rag_status = f"⚠️ Embedding error ({e}) — keyword fallback active"
    else:
        SEMANTIC_ACTIVE = False
        rag_status = "⚠️ Keyword RAG — run build_embeddings.py for semantic search"

    style = p["style"]
    return (
        f"✅ **Persona loaded: {p['name']}**\n\n"
        f"**Data:** {p['total_messages']:,} messages · {len(p['pairs']):,} pairs"
        + (f" ({removed} exact dupes removed at load)" if removed else "") + "\n"
        f"**RAG:** {rag_status}\n"
        f"**Style:** {style['hinglish']*100:.0f}% Hinglish · "
        f"avg {style['avg_len']}w · "
        f"{style['short_ratio']*100:.0f}% short · "
        f"{style['long_ratio']*100:.0f}% long\n"
        f"**Model:** llama-3.3-70b-versatile\n"
        f"**New:** dead zone handling · rate retry · streak detection · quality filter · topic memory\n\n"
        f"Go to **Chat** tab!"
    )


def chat_with_persona(message: str, history: list):
    global client, profile

    if not history:
        history = []

    if not profile or not client:
        history = history + [
            {"role": "user",      "content": message},
            {"role": "assistant", "content": "⚠️ Load persona first — Setup tab → Load Persona."}
        ]
        return "", history, history

    msgs  = build_messages(message, history, profile)
    reply = call_groq_with_retry(msgs)

    # Quality filter — if model breaks character, retry once with extra instruction
    if is_bad_response(reply):
        msgs_retry = msgs + [{
            "role": "system",
            "content": f"Stay in character as {profile['name']}. No AI language. Just text back naturally."
        }]
        reply = call_groq_with_retry(msgs_retry)

    # Streak detection — if same as last reply, nudge for variety
    last = get_last_reply(history)
    if is_repeat(reply, last):
        msgs_var = msgs + [{
            "role": "system",
            "content": "Say something different this time — you just said something very similar."
        }]
        reply = call_groq_with_retry(msgs_var)

    reply = clean_response(reply)

    history = history + [
        {"role": "user",      "content": message},
        {"role": "assistant", "content": reply},
    ]
    return "", history, history


def clear_chat():
    return [], []


def preview_messages(msg: str) -> str:
    if not profile:
        return "Load persona first."
    msgs = build_messages(msg, [], profile)
    out  = [f"RAG: {'SEMANTIC' if SEMANTIC_ACTIVE else 'KEYWORD'} · Layers: {len(msgs)}\n{'='*60}"]
    for i, m in enumerate(msgs):
        out.append(f"\n[{i}] {m['role'].upper()}:\n{m['content']}\n{'─'*50}")
    return "\n".join(out)


# ── UI ─────────────────────────────────────────────────────────────────────────

with gr.Blocks(title="Persona Bot") as demo:

    gr.Markdown(
        "# 🎭 Persona Bot\n"
        "### Semantic RAG · 6-layer prompt · tonal detection · "
        "topic memory · dead zone handling · rate retry · streak detection"
    )

    with gr.Tabs():

        with gr.Tab("⚙️ Setup"):
            gr.Markdown(
                f"**Groq API Key:** "
                f"{'✅ Loaded from `.env`' if GROQ_API_KEY else '❌ Not found — add GROQ_API_KEY to .env and restart'}\n\n"
                "Loads `persona_profile.json`. "
                "Run `build_embeddings.py` once for semantic search upgrade."
            )
            init_btn   = gr.Button("🚀 Load Persona", variant="primary")
            status_out = gr.Markdown()

        with gr.Tab("💬 Chat"):
            chat_state = gr.State([])
            chatbot    = gr.Chatbot(label="", height=520, show_label=False)
            with gr.Row():
                msg_input = gr.Textbox(
                    placeholder="Type a message...",
                    show_label=False, scale=5, container=False,
                )
                send_btn  = gr.Button("Send", variant="primary", scale=1)
                clear_btn = gr.Button("🗑️", scale=1)

        with gr.Tab("🔬 Debug"):
            gr.Markdown(
                "See the exact messages sent to the model.\n"
                "`[0]` = system · Next = few-shot turns · Last = your message."
            )
            debug_input  = gr.Textbox(label="Test message", value="kya kar rhi h aaj")
            debug_btn    = gr.Button("Show full message list")
            debug_output = gr.Textbox(
                label="Messages sent to Groq", lines=45, interactive=False
            )

    init_btn.click(fn=initialise, outputs=[status_out])
    send_btn.click(
        fn=chat_with_persona,
        inputs=[msg_input, chat_state],
        outputs=[msg_input, chat_state, chatbot],
    )
    msg_input.submit(
        fn=chat_with_persona,
        inputs=[msg_input, chat_state],
        outputs=[msg_input, chat_state, chatbot],
    )
    clear_btn.click(fn=clear_chat, outputs=[chat_state, chatbot])
    debug_btn.click(fn=preview_messages, inputs=[debug_input], outputs=[debug_output])


if __name__ == "__main__":
    demo.launch(
        share=False,
        inbrowser=True,
        theme=gr.themes.Soft(
            primary_hue="violet",
            secondary_hue="purple",
            neutral_hue="slate",
        ),
    )