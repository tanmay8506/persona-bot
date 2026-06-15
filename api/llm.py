"""
api/llm.py — Dynamic prompt assembler, Groq client caller, memory summaries and safeguards.
"""

import os
import re
import time
import random
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

GROQ_API_KEY  = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL_ID = os.getenv("GROQ_MODEL_ID", "llama-3.3-70b-specdec")

# Initialize client
def get_groq_client():
    if not GROQ_API_KEY:
        raise ValueError("GROQ_API_KEY is not configured in environment variables.")
    return Groq(api_key=GROQ_API_KEY)


# ── Language & Dead Zone Detectors ────────────────────────────────────────────

HINDI_SET = {
    "yr","yaar","arre","kya","kuch","nahi","nhi","haan","hn","mein","abhi",
    "chal","theek","acha","bata","sun","kal","aaj","kyun","matlab","bas","phir",
    "rhi","rha","hun","fir","toh","aur","kr","bhi","ni","hu","mai","tu","vo",
    "tha","thi","woh","usse","tujhe","mujhe","hum","unhe","inhe","kisi","sab",
    "isko","usko","apna","apni","kyunki","isliye","waise","accha","sach",
}

DEAD_ZONE_MSGS = {
    "ok","okay","k","hm","hmm","what","why","how","hi","hey","hello","bye",
    "yes","no","sure","fine","nice","good","bad","lol","haha","omg","really",
    "oh","ah","ugh","bro","man","dude","wait","stop","go","come","see",
}

def is_dead_zone(message: str) -> bool:
    clean = re.sub(r'[^\w\s]', '', message.lower()).strip()
    words = set(clean.split())
    return len(words) <= 2 and words.issubset(DEAD_ZONE_MSGS)

def message_lang_ratio(message: str) -> float:
    words = message.lower().split()
    if not words:
        return 0.0
    hindi_count = sum(1 for w in words if w in HINDI_SET)
    return hindi_count / len(words)


# ── Layer 1: System Prompt DNA ────────────────────────────────────────────────

def build_pinned_system(p: dict) -> str:
    name  = p["name"]
    style = p["style"]
    hind  = style.get("hinglish", 0.0)

    hindi_vocab = {
        "yr","arre","kya","ni","mein","kr","bhi","hn","rhi","rha","hun",
        "fir","toh","yaar","nhi","aur","haan","nahi","abhi","kuch","acha",
        "matlab","chal","theek","mai","hu","thi","tha","isliye","becoz","usse",
    }
    sig_hindi = [w for w in style.get("top_words", [])[:20] if w in hindi_vocab]
    sig_all   = style.get("top_words", [])[:10]

    hinglish_line = (
        f"Mix Hindi+English mid-sentence naturally ({hind*100:.0f}% of your messages do). "
        f"Hindi words you use a lot: {', '.join(sig_hindi[:10])}"
        if hind > 0.3 else "Write mostly in English."
    )

    solo_q   = "Send '?' alone to mean 'what?'/'huh?' — you do this a lot." if style.get("solo_q", 0) > 15 else ""
    solo_dot = "Send '.' alone as a dry or dismissive reaction."             if style.get("solo_dot", 0) > 5  else ""

    short_pct = int(style.get("short_ratio", 0.0) * 100)
    long_pct  = int(style.get("long_ratio", 0.0) * 100)

    return (
        f"You are {name}. Not an AI — you ARE {name}, texting on WhatsApp.\n\n"
        f"STYLE ({p.get('total_messages', 1000):,} real messages):\n"
        f"- {short_pct}% of replies are 1-4 words. {long_pct}% are 15+ words. Read the energy.\n"
        f"- {hinglish_line}\n"
        f"- Skip capitals and punctuation like a real texter\n"
        f"- {solo_q} {solo_dot}\n"
        f"- Split long thoughts across separate short lines (natural burst texting)\n"
        f"- Your signature words: {', '.join(sig_all)}\n\n"
        f"NEVER: be formal · say 'As {name}...' · admit being AI · use bullet points · "
        f"ignore what they said · repeat yourself · give generic responses · use Hindi Devanagari script (write in Roman/Latin script only)\n\n"
        f"Real examples of how you text are injected below as conversation turns."
    )


# ── Layer 3: Tonal Context Hints ──────────────────────────────────────────────

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
    "emotional": "They're going through something emotional. Respond with genuine care, ask what happened, acknowledge their feelings. Don't brush it off.",
    "excited": "They're excited. Match that energy — be enthusiastic back.",
    "humor":   "They're being funny or joking around. Play along, banter back.",
    "question": "They asked you something specific. Actually answer it in your texting style.",
    "planning": "They're talking about meeting up or making plans. Respond naturally to that.",
}

def detect_tone(message: str, history: list[dict]) -> str:
    text = message.lower()
    recent = " ".join(h["content"].lower() for h in history[-4:] if h["role"] == "user")
    combined = text + " " + recent

    for tone, keywords in TONE_PATTERNS.items():
        if tone == "question":
            if "?" in message: return "question"
        elif any(w in combined for w in keywords):
            return tone
    return "casual"


# ── Layer 4: Conversational Memory Summary ────────────────────────────────────

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

def generate_compressed_summary(history: list[dict], name: str) -> str:
    """Trigger a fast synchronous Llama summary of the conversation topics so far."""
    if len(history) < 6:
        return ""
    
    # Format message log for LLM summarizer
    transcript = ""
    for msg in history[:-2]: # summarize up to the last turn
        role_label = name if msg["role"] == "assistant" else "User"
        transcript += f"{role_label}: {msg['content']}\n"
        
    summary_prompt = [
        {"role": "system", "content": "You are a concise memory assistant. Summarize the main topics discussed in the following chat segment in exactly one line of 15 words or less (e.g. 'Discussing upcoming college exams and plans for lunch tomorrow'). Do not prefix with labels or intros."},
        {"role": "user", "content": f"Chat Transcript:\n{transcript}"}
    ]
    
    try:
        client = get_groq_client()
        res = client.chat.completions.create(
            model=GROQ_MODEL_ID,
            messages=summary_prompt,
            temperature=0.3,
            max_tokens=40
        )
        summary = res.choices[0].message.content.strip()
        topics = extract_topics(history)
        
        last_user = next((h["content"][:80] for h in reversed(history) if h["role"] == "user"), "")
        last_self = next((h["content"][:80] for h in reversed(history) if h["role"] == "assistant"), "")
        
        return (
            f"[Conversation Memory: {summary} "
            f"· Topics: {', '.join(topics) if topics else 'general chat'}]\n"
            f"Last exchange:\n"
            f"User said: {last_user}\n"
            f"You replied: {last_self}"
        )
    except Exception as e:
        print(f"Summarizer error: {e}")
        
    return ""


# ── AI Bleed-Through & Labelling Filters ──────────────────────────────────────

BAD_PATTERNS = [
    re.compile(r"^(As |I am |I'm )", re.I),
    re.compile(r"\b(language model|I am an AI|artificial intelligence|I cannot|I don't have access)\b", re.I),
    re.compile(r"^\*\w"),                         # asterisk action prefix: *laughs*
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


# ── Streak/Repetition Blocker ─────────────────────────────────────────────────

def is_repeat(new_reply: str, history: list[dict]) -> bool:
    """Compare with last assistant reply to avoid repeating similar wording."""
    last_assistant_reply = ""
    for h in reversed(history):
        if h["role"] == "assistant":
            last_assistant_reply = h["content"]
            break
            
    if not last_assistant_reply:
        return False
        
    a = re.sub(r'[^\w]', '', new_reply.lower())[:60]
    b = re.sub(r'[^\w]', '', last_assistant_reply.lower())[:60]
    
    if a == b:
        return True
        
    min_len = min(len(a), len(b))
    if min_len == 0:
        return False
        
    overlap = sum(1 for ca, cb in zip(a, b) if ca == cb)
    return (overlap / min_len) > 0.82


# ── Groq API Calling with Retry Backoff ────────────────────────────────────────

def call_groq_with_retry(messages: list[dict], max_retries: int = 3, force_variety: bool = False) -> str:
    """Call Groq API with exponential backoff retry on 429 Rate Limits."""
    client = get_groq_client()
    
    # Increase temperature on streak-blocker variety re-runs
    temp = 0.95 if force_variety else 0.84
    
    for attempt in range(max_retries):
        try:
            response = client.chat.completions.create(
                model=GROQ_MODEL_ID,
                messages=messages,
                temperature=temp,
                max_tokens=150,
                frequency_penalty=0.5,
                presence_penalty=0.35,
            )
            return response.choices[0].message.content.strip()
            
        except Exception as e:
            err = str(e)
            if "rate_limit" in err.lower() or "429" in err:
                wait = (2 ** attempt) + random.uniform(0.5, 1.5)
                if attempt < max_retries - 1:
                    time.sleep(wait)
                    continue
                else:
                    return "⚠️ rate limit hit. type again in a second."
            elif "context_length" in err.lower():
                return "⚠️ text too long for memory."
            else:
                return f"⚠️ error: {err[:60]}"
                
    return "⚠️ api connection error."


# ── Message Assembler (6-Layer Architecture) ──────────────────────────────────

def assemble_prompt(message: str, history: list[dict], profile: dict, few_shots: list[dict]) -> list[dict]:
    name = profile["name"]
    
    # Layer 1: Pinned identity and style rules
    pinned_prompt = build_pinned_system(profile)
    msgs = [{"role": "system", "content": pinned_prompt}]
    
    # Layer 2: Few-shot context turns (from RAG or Dead-zone)
    for pair in few_shots:
        ctx = pair.get("ctx", "").strip()
        resp = pair.get("resp", "").strip()
        if ctx and resp:
            msgs.append({"role": "user", "content": ctx})
            msgs.append({"role": "assistant", "content": resp})
            
    # Layer 3: Tonal Context Hint
    tone = detect_tone(message, history)
    hint = TONE_HINTS.get(tone, "")
    if hint:
        msgs.append({"role": "system", "content": f"[Tonal Hint: {hint}]"})
        
    # Layer 4: Session Memory Summary
    if len(history) >= 6:
        summary = generate_compressed_summary(history, name)
        if summary:
            msgs.append({"role": "system", "content": summary})
            
    # Layer 5: Live Active History (Last 8 turns)
    active_history = history[-8:] if len(history) > 8 else history
    for h in active_history:
        msgs.append({"role": h["role"], "content": h["content"]})
        
    # Layer 6: Current Message
    msgs.append({"role": "user", "content": message})
    
    return msgs
