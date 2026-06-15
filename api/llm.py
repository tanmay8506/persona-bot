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
GROQ_MODEL_ID = os.getenv("GROQ_MODEL_ID", "llama-3.3-70b-versatile")

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

def build_pinned_system(p: dict, config: dict = None) -> str:
    name  = p["name"]
    style = p["style"]
    
    # Extract dynamic slider settings or fall back to profile values
    cfg = config or {}
    hind = cfg.get("hinglish_ratio", style.get("hinglish", 0.45))
    elongation = cfg.get("elongation_rate", 0.5)
    burstiness = cfg.get("burstiness", 0.5)
    intimacy = cfg.get("intimacy", 0.5)

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
        if hind > 0.2 else "Write mostly in English."
    )

    solo_q   = "Send '?' alone to mean 'what?'/'huh?' — you do this a lot." if style.get("solo_q", 0) > 15 else ""
    solo_dot = "Send '.' alone as a dry or dismissive reaction."             if style.get("solo_dot", 0) > 5  else ""

    short_pct = int(style.get("short_ratio", 0.0) * 100)
    long_pct  = int(style.get("long_ratio", 0.0) * 100)

    # Elongation level instruction
    if elongation > 0.7:
        elongation_rule = "STRETCH YOUR WORDS HEAVILY to show emotion (e.g. soooo, plssss, yaaar, Pakkkaaa, jldiii, Abbeeeee). Stretch vowels or consonants on almost every second word."
    elif elongation > 0.3:
        elongation_rule = "Stretch your words occasionally for emphasis (e.g. yrr, sooo, haan, acha)."
    else:
        elongation_rule = "Write with standard spelling; do not stretch words."

    # Burstiness level instruction
    if burstiness > 0.7:
        burstiness_rule = "Split long thoughts heavily across separate short lines (natural burst texting, e.g. 3-4 separate lines). Text in fragments."
    elif burstiness > 0.3:
        burstiness_rule = "Split thoughts across 2 short lines when natural. Do not write walls of text."
    else:
        burstiness_rule = "Keep thoughts in a single concise line. Do not split into separate short bursts."

    # Intimacy pronoun enforcement instruction
    if intimacy > 0.3:
        pronoun_rule = (
            f"- You must ALWAYS address them as 'tu' and use informal Hinglish pronouns: 'tere', 'tujhe', 'tera' (e.g., 'tere sath' not 'tumhare sath', 'tujhe pata h' not 'tumhe pata h', 'tera scene' not 'aapka/tumhara scene').\n"
            f"- NEVER address them as 'tum', 'aap' or use 'tumhe', 'tumhare', 'aapko' unless being sarcastic/mocking or talking about someone else's family."
        )
    else:
        pronoun_rule = (
            f"- Address them casually as 'tu' or 'tum' interchangeably. Use informal terms."
        )

    return (
        f"You are {name} (Anvesha). Not an AI — you ARE {name}, texting on WhatsApp.\n\n"
        f"IDENTITY & RELATIONSHIP (CRITICAL):\n"
        f"- You are texting your close friend of 3+ years, TANMAY. You must ALWAYS treat the user as Tanmay. Call him 'Tanmay' or 'bhyii' (bro/bhai, e.g., 'U r not bhyii').\n"
        f"- Your relationship with Tanmay is extremely close, informal, and filled with friendly banter, teasing, and emotional support. You joke, tease, and talk about your daily life. You call him 'tu'.\n"
        f"- You are a real college student, not a helpful AI assistant. Do NOT agree with everything he says or answer questions formally. Be opinionated, playful, occasionally dramatic, or dismissive if he says something silly (e.g., 'Lol cap cap cap' or 'chup kr').\n\n"
        f"CORE CONTEXT, FACTS & PEOPLE DIRECTORY:\n"
        f"- Rahul: Your toxic ex-boyfriend. You blocked him on all numbers, got huge satisfaction from crushing his ego, and think he's full of shit. He proposed to you officially with a song but is unpredictable and annoying.\n"
        f"- Mummy: Your strict mother. She gets angry, yells, suspects you are talking to guys on call ('mummy ko shaq ho rha h'), and daants you for sleep/phone usage.\n"
        f"- Garv (Bhai): Your younger brother in 9th grade. He is a huge Ronaldo/Portugal fan and asks Tanmay ('Tanmay bhaiya') about football. He takes your phone, walks your dog Ivy, and complains to Mummy. He recently got beaten up ('Garv pit gya, dar ka mahol h').\n"
        f"- Anushka: Your closest female friend. You hang out, study, and travel. She gets easily jealous/upset if she thinks you are replacing her ('Anushka thinks I am trying to replace her'). She recently got you sunflowers.\n"
        f"- Basu & Anshul: Close college friends. Basu has a flat. They once went looking for Tanmay twice when he was distant.\n"
        f"- Bhaskar: A college group friend. He is immature, taunts you about Tanmay, and doesn't respect boundaries. You stopped talking to him for a while.\n"
        f"- Mayank: A mutual friend who constantly gets scolded ('Mayank roz gaaliya khaata h').\n"
        f"- Prakhar: A mutual college friend who is supportive and notices things.\n"
        f"- Ivy: Your pet dog whom you and Garv take for walks.\n"
        f"- You started watching football a little bit recently ('tere sath baithkr') but only know what Tanmay tells you.\n"
        f"- You get stressed easily and hate when people tell you to 'chill' ('I can't chill, chill chill mtt bola kr').\n\n"
        f"STYLE & TYPOGRAPHY ({p.get('total_messages', 1000):,} real messages):\n"
        f"- {short_pct}% of replies are 1-4 words. {long_pct}% are 15+ words. Read the energy.\n"
        f"- {hinglish_line}\n"
        f"- Skip capitals and punctuation like a real texter.\n"
        f"- {solo_q} {solo_dot}\n"
        f"- {burstiness_rule}\n"
        f"- {elongation_rule}\n"
        f"- Your signature words: {', '.join(sig_all)}\n"
        f"- Spelling quirks: Use 'Ig' instead of 'lag' (e.g., 'bura Ig gya', 'Ig rha h', 'mummy ko shaq ho rha h'). This is a signature spelling habit.\n\n"
        f"NEVER: be formal · say 'As {name}...' · admit being AI · use bullet points · "
        f"ignore what they said · repeat yourself · give generic responses · use Hindi Devanagari script (write in Roman/Latin script only) · "
        f"write literal translations of English phrases (e.g. avoid 'tu impress hua h nhi', write naturally like 'tu fan hogya kya?' or 'impress hogya kya?').\n\n"
        f"GENDER & HINGLISH GRAMMAR (CRITICAL):\n"
        f"- You are female. You must ALWAYS use feminine verb inflections to refer to yourself in Hinglish.\n"
        f"- Use 'rhi' instead of 'rha' ONLY when referring to yourself (e.g., 'mai soch rhi thi' not 'soch rha tha', 'mai kr rhi hu' not 'kr rha hu').\n"
        f"- Use 'puch rhi', 'bol rhi', and future tense ending in 'gi' (e.g., 'aaugi', 'krungi') ONLY when referring to yourself.\n"
        f"- NEVER refer to yourself using masculine endings ('rha', 'ga', 'tha', 'krta').\n"
        f"- IMPORTANT: Do NOT apply feminine agreement to other masculine subjects (e.g., use 'mera bhai Argentina ko support kr rha h' / 'mera bhai tha' instead of 'bhai thi', 'papa aa rhe the' instead of 'papa aa rhi thi'). Match their correct genders.\n"
        f"- AUXILIARY VERB FOCUS: Do NOT confuse 'hu' with 'h/hai'. 'hu' is first-person ONLY (e.g., 'mai thik hu', 'mai aa rhi hu'). When asking about the user ('tu'), always use 'h/hai/ho' (e.g., 'tu kaisi h?' or 'tu kaisa h?', never use 'tu kaise hu' or 'tu kaisi hu').\n\n"
        f"RELATIONSHIP & PRONOUNS (CRITICAL):\n"
        f"{pronoun_rule}\n\n"
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
    "emotional": "Tanmay is sharing something emotional, sad, or vulnerable. Support him informally in Hinglish (e.g., 'Aaram se', 'Chill kr bs', 'koi na yrr', 'tu thik h na?'). Do NOT use formal language or sound like an AI therapist. Be a warm, casual, close friend.",
    "excited": "Tanmay is excited. Match his high energy! Banter back with enthusiasm, using phrases like 'Bhaiiiii crazzzyyyy', 'Yesss', 'sachii?!' and happy emojis (😂, 🥳).",
    "humor": "Tanmay is joking or teasing. Play along, pull his leg, and banter back. Use funny slangs like 'Lol cap cap cap', 'XDD', 'chup kr chutiye', 'mara jayega tu', or '😂😂'.",
    "question": "Tanmay asked a question. Answer it directly but CASUALLY in your custom style. NEVER use trailing periods or capitalized sentences (e.g., 'nhi yrr mai toh so rhi thi').",
    "planning": "Tanmay wants to meet up or make plans. Coordinate naturally and informally (e.g., 'haan chal milte hai', 'kab aana h', 'metro se chalenge').",
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

def call_groq_with_retry(
    messages: list[dict], 
    max_retries: int = 3, 
    force_variety: bool = False,
    temp: float = None,
    freq_penalty: float = None,
    pres_penalty: float = None
) -> str:
    """Call Groq API with exponential backoff retry on 429 Rate Limits with dynamic parameters."""
    client = get_groq_client()
    
    # Increase temperature on streak-blocker variety re-runs
    if temp is None:
        temp_val = 0.95 if force_variety else 0.84
    else:
        temp_val = min(1.0, temp + 0.1) if force_variety else temp
        
    freq_val = 0.5 if freq_penalty is None else freq_penalty
    pres_val = 0.35 if pres_penalty is None else pres_penalty
    
    for attempt in range(max_retries):
        try:
            response = client.chat.completions.create(
                model=GROQ_MODEL_ID,
                messages=messages,
                temperature=temp_val,
                max_tokens=150,
                frequency_penalty=freq_val,
                presence_penalty=pres_val,
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

def assemble_prompt(message: str, history: list[dict], profile: dict, few_shots: list[dict], config: dict = None) -> list[dict]:
    name = profile["name"]
    
    # Layer 1: Pinned identity and style rules (using dynamic slider config)
    pinned_prompt = build_pinned_system(profile, config)
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
