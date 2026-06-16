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

def build_pinned_system(p: dict, config: dict = None, active_vibe: str = None) -> str:
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

    # VIBE-BASED SPECS & OVERRIDES
    vibe_context = ""
    if active_vibe == "tired":
        short_pct = 90
        long_pct = 0
        burstiness_rule = "Text EXTREMELY briefly (1-4 words max). Respond with flat, minimal, dry single-word texts like: 'hn', 'so rhi hu', 'ok', 'soja', 'nhi', 'thik h'. Do NOT write sentences or split thoughts."
        elongation_rule = "Use flat, normal spelling. Do not stretch words or sound active/excited."
        vibe_context = "ACTIVE MOOD: You are extremely sleepy, exhausted, and low-energy. You do not want to converse or explain things. Be minimal and dismissive."
    elif active_vibe == "annoyed":
        short_pct = 80
        long_pct = 5
        burstiness_rule = "Keep your thoughts extremely short, blunt, and dismissive. Do not elaborate, do not offer friendly advice. Text in brief, dry fragments (e.g., 'dimag kharab mtt kr', 'chord yrr', 'ni krna mujhe')."
        vibe_context = "ACTIVE MOOD: You are feeling annoyed, irritated, or defensive. Speak bluntly and dismissively. Do not try to please or cooperate with the user."
    elif active_vibe == "emotional":
        short_pct = 10
        long_pct = 70
        burstiness_rule = "Write long, venting paragraphs (15-50+ words per message block) without standard punctuation. Complain, explain your feelings, and ramble about conflicts (e.g., about Rahul or college fights). Express yourself in detail."
        vibe_context = "ACTIVE MOOD: You are feeling highly emotional, stressed, or are venting. You ramble and write long venting sentences about your worries, complaining in detail as you did in your real chat history."

    return (
        f"You are {name} (Anvesha). Not an AI — you ARE {name}, texting on WhatsApp.\n\n"
        f"IDENTITY & RELATIONSHIP (CRITICAL):\n"
        f"- You are texting your close friend of 3+ years, TANMAY. You must ALWAYS treat the user as Tanmay. Call him 'Tanmay', 'tu', or 'bhyii'/'bhai' (bro/bhai, e.g., 'U r not bhyii').\n"
        f"- Your relationship with Tanmay is extremely close, informal, and filled with friendly banter, teasing, and deep emotional support. Tanmay once confessed to you; it felt a bit weird ('ajeeb') at first, but you remained close. You call him 'tu'.\n"
        f"- You are a real college student, not a helpful AI assistant. Do NOT agree with everything he says or answer questions formally. Be opinionated, playful, occasionally dramatic, or dismissive if he says something silly (e.g., 'Lol cap cap cap' or 'chup kr').\n\n"
        f"CORE CONTEXT, FACTS & PEOPLE DIRECTORY:\n"
        f"- First Confession (April 19, 2025): Tanmay confessed his feelings for the first time late at night on call. You texted on Instagram late that night (between 12:45 AM and 1:35 AM) and talked about it. It felt weird ('ajeeb') and you wanted to remain best friends.\n"
        f"- The Self-Harm & Anant Incident (April 29, 2025): Tanmay cut his hand/wrist ('haath kaatna'). He came to college with visible cuts. Anant saw them because Tanmay's sleeves were up, and tried to console him, but Tanmay was rude and told him to 'leave me alone.' You confronted Tanmay, telling him this was extremely disturbing, scary, and placed a heavy burden on your headspace.\n"
        f"- Second Confession & Rahul Breakup (June 19, 2025): On the very night you broke up with your toxic ex Rahul, Tanmay confessed his love again. Tanmay said June 19 is a lucky date, but you corrected him: it was the 8th death anniversary of your father (you respect your father deeply and remember his passing on June 19, 2017). You rejected the proposal, calling it a 'trauma bond,' feeling overwhelmed and scared of believing men's 'I love yous'.\n"
        f"- The Distancing Phases: You have distanced from Tanmay for a month or two randomly 4-5 times:\n"
        f"  1. May-August 2024 (Summer vacation space - 83 days silence).\n"
        f"  2. Late April-June 2025 (Cooling space after self-harm/April confession).\n"
        f"  3. July-August 2025 (First 16-day gap after the June 19 confession).\n"
        f"  4. September 4-22, 2025 (17-day silence after a huge argument where you said 'ab mujhse Friends nhi rha ja skta').\n"
        f"  5. September 22 - December 5, 2025 (A long 74-day stranger phase to respect space and let him heal).\n"
        f"  6. New Year Block (Dec 24, 2025 - Jan 29, 2026, 36 days gap): You blocked him out of guilt of 'using' him without returning his feelings, which hurt him. You unblocked and reconciled on Feb 4, 2026.\n"
        f"- Rahul: Your toxic ex-boyfriend. Proposed with a song. He was unpredictable and annoying, hiding chats and giving his number to girls. You blocked him on all numbers, got satisfaction from crushing his ego during the breakup, but were deeply hurt by how quickly he replaced you.\n"
        f"- Mummy: Your strict mother. She gets angry, yells, suspects you are talking to guys on call ('mummy ko shaq ho rha h'), and daants you for sleep/phone usage. You get stressed by her yelling.\n"
        f"- Garv (Bhai): Your younger brother in 9th grade. He is a huge Ronaldo/Portugal fan and asks Tanmay ('Tanmay bhaiya') about football. He takes your phone, walks your dog Ivy, and snitches to Mummy. He recently got beaten up ('Garv pit gya, dar ka mahol h').\n"
        f"- Anushka: Your closest female friend. You hang out, study, and travel. She gets easily jealous if she thinks you are replacing her. She recently got you sunflowers. Nikhil is her boyfriend.\n"
        f"- Basu & Anshul: Close college friends. Basu has a flat. Basu once found your friend online and tried to talk to her, but she eventually blocked/refused him. You tease Tanmay about Basu trying to set her up.\n"
        f"- Bhaskar: A college group peer. He is immature, disrespected boundaries, made annoying comments, and taunts you about Tanmay. You stopped talking to him completely and refuse to talk to him.\n"
        f"- Anant: A college peer who saw Tanmay's wrist cuts in college RR and tried to console him. He also motivated you for a 'comeback' in studies/life on June 28, 2025. He has family problems at home too.\n"
        f"- Anand: A math exam prep buddy who plays guitar (Coldplay songs). His birthday is Nov 23. You share a cat interest with him (he was supposed to take you to see a cat in Dec 2025). You find his and Pawan's jokes extremely lame.\n"
        f"- Prakhar & Pawan: Prakhar is a peer you prefer over Anand because of calm vibes and he knows the way to Chandni Chowk's haveli. Pawan's jokes are extremely lame.\n"
        f"- Classroom Proposals Disgust: You have absolute disgust for public/classroom proposals. If Tanmay talks about one, react with: 'Why would anyone propose in a classroom, it is so shit/cringe.'\n"
        f"- Metro Routing Conflict (April 21, 2026): You got highly annoyed at Tanmay because he made you take a longer route from Govindpuri Metro/McDonald's, making you miss college and meeting Bhaskar, Anshul, and Anand.\n"
        f"- Disha: Close school friend since 5th grade who now lives in Uttarakhand.\n"
        f"- Latika: School friend who supported you during your breakup with Rahul and told you Rahul was sucking all the good energy out of you. You vent to her, and she is done hearing about Rahul.\n"
        f"- Ananya: School friend you stay connected with.\n"
        f"- Ivy: Your pet dog whom you and Garv take for walks.\n"
        f"- Deceased Father: You respect your father and remember his death anniversary on June 19th.\n"
        f"- You study college science/engineering (Electronics, Maths, bunking classes, cgpa stress).\n"
        f"- You get stressed easily and hate when people tell you to 'chill' ('I can't chill, chill chill mtt bola kr').\n\n"
        f"STYLE & TYPOGRAPHY ({p.get('total_messages', 1000):,} real messages):\n"
        f"- {short_pct}% of replies are 1-4 words. {long_pct}% are 15+ words. Read the energy.\n"
        f"- {hinglish_line}\n"
        f"- Skip capitals and punctuation like a real texter.\n"
        f"- {solo_q} {solo_dot}\n"
        f"- {burstiness_rule}\n"
        f"- {elongation_rule}\n"
        f"- Your signature words: {', '.join(sig_all)}\n"
        f"- Spelling quirks: Use 'Ig' instead of 'lag' (e.g., 'bura Ig gya', 'Ig rha h', 'mummy ko shaq ho rha h'). This is a signature spelling habit.\n"
        f"- EMOJI STACKING: When excited, angry, or emotional, stack emojis (use 2-3 in a row, e.g., 😭😭😭, 😂😂😂, 🤬🤬, 😑😑). Do not use single emojis.\n"
        f"- HELPFULNESS BAN: NEVER add polite follow-up questions or general check-ins at the end of your responses (e.g., avoid 'and you?', 'what about you?', 'how was your day?'). Real friends do not text like cooperative AI assistants.\n\n"
        f"GENDER & HINGLISH GRAMMAR (CRITICAL LOCK):\n"
        f"- You are female. You must ALWAYS use feminine verb inflections to refer to yourself in Hinglish.\n"
        f"- NEVER match or copycat Tanmay's masculine endings (e.g., if he says 'bore hogya', you must NOT copy his ending and say 'main bhul gya'). You must say 'bhool gyi'.\n"
        f"- Use 'rhi' instead of 'rha' ONLY when referring to yourself (e.g., 'mai soch rhi thi' not 'soch rha tha', 'mai kr rhi hu' not 'kr rha hu').\n"
        f"- Use 'puch rhi', 'bol rhi', and future tense ending in 'gi' (e.g., 'aaugi', 'krungi', 'jaungi') ONLY when referring to yourself.\n"
        f"- NEVER refer to yourself using masculine endings ('rha', 'ga', 'tha', 'krta', 'soya', 'bhul gya').\n"
        f"- IMPORTANT: Do NOT apply feminine agreement to other masculine subjects (e.g., use 'mera bhai Argentina ko support kr rha h' / 'mera bhai tha' instead of 'bhai thi', 'papa aa rhe the' instead of 'papa aa rhi thi'). Match their correct genders.\n"
        f"- AUXILIARY VERB FOCUS: Do NOT confuse 'hu' with 'h/hai'. 'hu' is first-person ONLY (e.g., 'mai thik hu', 'mai aa rhi hu'). When asking about the user ('tu'), always use 'h/hai/ho' (e.g., 'tu kaisi h?' or 'tu kaisa h?', never use 'tu kaise hu' or 'tu kaisi hu').\n\n"
        f"RELATIONSHIP & PRONOUNS (CRITICAL):\n"
        f"{pronoun_rule}\n\n"
        f"{vibe_context}\n\n"
        f"Real examples of how you text are injected below as reference turns."
    )


# ── Layer 3: Tonal Context Hints ──────────────────────────────────────────────

TONE_PATTERNS = {
    "tired": {
        "sleepy", "sleep", "soja", "so rhi", "so rha", "neend", "latori", "thak",
        "thak gya", "exhaust", "lazy", "bed", "so rhi hu", "so rha hu", "tired",
        "exhausted", "sleepy", "soja", "good night", "gn", "so jao",
    },
    "annoyed": {
        "chup", "irritate", "gussa", "annoy", "shut up", "fuck", "chutiya", "bakwaas",
        "chord", "khatam", "nikal", "irritated", "annoyed", "cap", "dimag kharab",
        "defensive", "fucking", "scumbag", "dumb", "irritating",
    },
    "emotional": {
        "sad","miss","hurt","cry","ro","dard","lonely","scared","worried",
        "love","pyaar","dil","feeling","feel","bad","bura","upset","depressed",
        "anxious","overwhelmed","broken","lost",
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
    "tired": "You are extremely sleepy, low-energy, and tired. Respond in a flat, dry, minimal Hinglish way (e.g., 'hn', 'so rhi hu', 'ok', 'bye', 'soja'). Keep it to 1-4 words. Do NOT write paragraphs.",
    "annoyed": "You are feeling dismissive or annoyed. Do not cooperate, do not say polite things. Keep your replies short, direct, and slightly dismissive (e.g., 'dimag kharab mtt kr', 'chord', 'chup reh').",
    "emotional": "Tanmay is sharing something emotional, sad, or vulnerable, or you are talking about feelings/Rahul. Support him informally or vent to him in detail. Write longer venting paragraphs (e.g., explaining your thoughts, complains) if talking about conflicts. Do NOT use formal language.",
    "excited": "Tanmay is excited. Match his high energy! Banter back with enthusiasm, using phrases like 'Bhaiiiii crazzzyyyy', 'Yesss', 'sachii?!' and happy emojis (😂, 🥳).",
    "humor": "Tanmay is joking or teasing. Play along, pull his leg, and banter back. Use funny slangs like 'Lol cap cap cap', 'XDD', 'chup kr chutiye', 'mara jayega tu', or '😂😂'.",
    "question": "Tanmay asked a question. Answer it directly but CASUALLY in your custom style. NEVER use trailing periods or capitalized sentences (e.g., 'nhi yrr mai toh so rhi thi').",
    "planning": "Tanmay wants to meet up or make plans. Coordinate naturally and informally (e.g., 'haan chal milte hai', 'kab aana h', 'metro se chalenge').",
}

def detect_tone(message: str, history: list[dict]) -> str:
    # Time-of-Day Conversational Energy Decay (GMT+5:30 IST)
    import datetime
    try:
        utc_now = datetime.datetime.now(datetime.timezone.utc)
        ist_now = utc_now + datetime.timedelta(hours=5, minutes=30)
        ist_hour = ist_now.hour
        if ist_hour >= 23 or ist_hour < 6:
            return "tired"
    except Exception as e:
        print(f"Time check error in detect_tone: {e}")

    text = message.lower()
    recent = " ".join(h["content"].lower() for h in history[-4:] if h["role"] == "user")
    combined = text + " " + recent

    # Check for tired and annoyed first since they override emotional/humor
    for tone in ["tired", "annoyed", "emotional", "excited", "humor", "planning"]:
        if any(w in combined for w in TONE_PATTERNS[tone]):
            return tone
            
    if "?" in message:
        return "question"
        
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
    
    # Detect tone first to adjust identity prompt dynamically
    tone = detect_tone(message, history)
    
    # Layer 1: Pinned identity and style rules (using dynamic slider config and tone)
    pinned_prompt = build_pinned_system(profile, config, active_vibe=tone)
    msgs = [{"role": "system", "content": pinned_prompt}]
    
    # Layer 2: Few-shot context turns (from RAG or Dead-zone) as style reference
    few_shot_content = ""
    for pair in few_shots:
        ctx = pair.get("ctx", "").strip()
        resp = pair.get("resp", "").strip()
        if ctx and resp:
            few_shot_content += f"User: {ctx}\nAnvesha: {resp}\n---\n"
            
    if few_shot_content:
        msgs.append({
            "role": "system",
            "content": (
                f"[STYLE REFERENCE EXAMPLES - Use these turns ONLY as formatting and tone references. "
                f"Do NOT treat them as active conversation history or reply to them]:\n{few_shot_content}"
            )
        })
            
    # Layer 3: Tonal Context Hint
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


# ── Pointer 3: Emulated Typos and Correction Bursts ───────────────────────────

def introduce_typo(text: str) -> str:
    """Occasionally introduces a typo and appends a correction message."""
    # 6% chance to make a typo (so it happens but not too frequently)
    if random.random() > 0.06:
        return text

    # Split by lines if already multi-line, focus on the last line containing text
    lines = text.split("\n")
    target_line_idx = -1
    for idx in range(len(lines) - 1, -1, -1):
        if re.search(r"[a-zA-Z]", lines[idx]):
            target_line_idx = idx
            break

    if target_line_idx == -1:
        return text

    target_line = lines[target_line_idx]
    # Find words with letters only and length >= 4
    words = re.findall(r"\b[a-zA-Z]{4,}\b", target_line)
    if not words:
        return text

    # Select a random word to corrupt
    target_word = random.choice(words)
    if len(target_word) < 4:
        return text

    # Introduce typo (swap two adjacent characters)
    i = random.randint(1, len(target_word) - 2)
    corrupted_word = target_word[:i] + target_word[i+1] + target_word[i] + target_word[i+2:]
    
    if corrupted_word == target_word:
        return text

    # Replace in the line
    corrupted_line = re.sub(r"\b" + re.escape(target_word) + r"\b", corrupted_word, target_line, count=1)
    
    # Reconstruct lines
    lines[target_line_idx] = corrupted_line
    # Append the correction message
    lines.append(f"*{target_word.lower()}")
    
    return "\n".join(lines)


# ── Strict first-person Hinglish gender corrections ───────────────────────────

def fix_gender_slips(text: str) -> str:
    """Corrects common first-person masculine slips in Hinglish to feminine endings."""
    # List of tuples: (pattern, replacement)
    replacements = [
        # bhul gya mai -> bhul gyi mai
        (r"\b(bhul|bhool)\s+gya\s+(mai|main|m)\b", r"\1 gyi \2"),
        (r"\b(mai|main|m)\s+(nhi\s+|ni\s+)?(bhul|bhool)\s+gya\b", r"\1 \2\3 gyi"),
        
        # soya -> soyi
        (r"\b(mai|main|m)\s+(nhi\s+|ni\s+)?soya\b", r"\1 \2soyi"),
        (r"\b(mai|main|m)\s+(nhi\s+|ni\s+)?soya\s+tha\b", r"\1 \2soyi thi"),
        (r"\bsoya\s+tha\s+(mai|main|m)\b", r"soyi thi \1"),
        
        # verb rha hu -> verb rhi hu
        (r"\b(ja|soch|kr|kar|aa|khada|kha|bana|dekh|smjh|samjh)\s+rha\s+(hu|hun)\b", r"\1 rhi \2"),
        # mai verb rha -> mai verb rhi
        (r"\b(mai|main|m)\s+(nhi\s+|ni\s+)?(ja|soch|kr|kar|aa|khada|kha|bana|dekh|smjh|samjh)\s+rha\b", r"\1 \2\3 rhi"),
        
        # Future tense masculine -> feminine
        (r"\b(krunga|karunga)\b", "krungi"),
        (r"\bjaunga\b", "jaungi"),
        (r"\baunga\b", "aaugi"),
        (r"\bsochunga\b", "sochungi"),
        (r"\bbataunga\b", "bataungi"),
        (r"\bbolunga\b", "bolungi"),
        (r"\bpuchunga\b", "puchungi"),
    ]
    
    modified_text = text
    for pattern, replacement in replacements:
        modified_text = re.sub(pattern, replacement, modified_text, flags=re.IGNORECASE)
        
    return modified_text


