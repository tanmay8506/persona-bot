import os
import re
import json
import httpx
import hashlib
from datetime import datetime
from collections import Counter
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

COHERE_API_KEY = os.getenv("COHERE_API_KEY", "")
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")

DATE_FORMATS = [
    "%m/%d/%y, %I:%M %p",
    "%m/%d/%y, %H:%M",
    "%d/%m/%y, %H:%M",
    "%m/%d/%Y, %I:%M %p",
    "%d/%m/%Y, %H:%M",
    "%d.%m.%y, %H:%M",
    "%d.%m.%Y, %H:%M",
    "%b %d, %Y %I:%M %p",
    "%b %d, %Y %I:%M%p",
    "%B %d, %Y %I:%M %p",
    "%Y-%m-%d %H:%M:%S",
    "%m/%d/%y, %I:%M:%S %p",
    "%d/%m/%Y, %H:%M:%S",
]

def parse_datetime(dt_str: str) -> datetime | None:
    clean_str = re.sub(r'\s+', ' ', dt_str.strip()).strip('[]')
    for fmt in DATE_FORMATS:
        try:
            test_str = clean_str
            if "%p" in fmt:
                test_str = test_str.replace("am", "AM").replace("pm", "PM")
            if "%b" in fmt or "%B" in fmt:
                test_str = test_str.title()
            return datetime.strptime(test_str, fmt)
        except ValueError:
            continue
    return None

def mask_pii(text: str) -> str:
    email_pat = r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+"
    text = re.sub(email_pat, "[Email]", text)
    phone_pat = r"(\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4,6}\b"
    text = re.sub(phone_pat, "[Phone]", text)
    return text

# --- WhatsApp Parser ---
def parse_whatsapp_content(content_str: str) -> list[dict]:
    patterns = [
        re.compile(r"^(\d{1,2}/\d{1,2}/\d{2,4},\s*\d{1,2}:\d{2}(?:\s*[aApP][mM])?)\s*-\s*([^:]+):\s*(.+)"),
        re.compile(r"^(\d{1,2}\.\d{1,2}\.\d{2,4},\s*\d{1,2}:\d{2}(?:\s*[aApP][mM])?)\s*-\s*([^:]+):\s*(.+)"),
        re.compile(r"^\[(\d{1,2}/\d{1,2}/\d{2,4},\s*\d{1,2}:\d{2}(?::\d{2})?(?:\s*[aApP][mM])?)\]\s*([^:]+):\s*(.+)"),
        re.compile(r"^\[(\d{1,2}/\d{1,2}/\d{4},\s*\d{1,2}:\d{2}:\d{2})\]\s*([^:]+):\s*(.+)"),
    ]
    
    parsed_messages = []
    current_msg = None
    
    for line in content_str.splitlines():
        line_str = line.strip('\n')
        matched = False
        
        for pat in patterns:
            m = pat.match(line_str.strip())
            if m:
                if current_msg:
                    parsed_messages.append(current_msg)
                dt_str = m.group(1).strip()
                sender = m.group(2).strip()
                body = m.group(3).strip()
                dt = parse_datetime(dt_str) or datetime.now()
                current_msg = {"timestamp": dt, "sender": sender, "text": body}
                matched = True
                break
                
        if not matched and current_msg:
            current_msg["text"] += "\n" + line_str.strip()
            
    if current_msg:
        parsed_messages.append(current_msg)
        
    clean_messages = []
    for m in parsed_messages:
        msg = re.sub(r"<[Tt]his message was edited>", "", m["text"]).strip()
        if not msg or msg.lower() in ("<media omitted>", "this message was deleted", "null", "image omitted", "sticker omitted") or "end-to-end encrypted" in msg.lower():
            continue
        m["text"] = mask_pii(msg)
        clean_messages.append(m)
        
    return clean_messages

# --- HTML Parser ---
def parse_html_content(content_str: str) -> list[dict]:
    soup = BeautifulSoup(content_str, "html.parser")
    parsed_messages = []
    blocks = soup.find_all("div", class_=lambda c: c and "uiBoxWhite" in c and "noborder" in c)
    
    for block in blocks:
        sender_tag = block.find("h2")
        text_tag = block.find(class_=lambda c: c and "_a6-p" in c)
        time_tag = block.find(class_=lambda c: c and "_a6-o" in c)
        
        if sender_tag and text_tag:
            sender = sender_tag.get_text(strip=True)
            msg = text_tag.get_text(separator=" ", strip=True).strip()
            dt = datetime.now()
            if time_tag:
                dt_str = time_tag.get_text(strip=True)
                dt = parse_datetime(dt_str) or datetime.now()
            if msg and sender and msg.lower() not in ("sent an attachment.", "null", "liked a message"):
                parsed_messages.append({"timestamp": dt, "sender": sender, "text": mask_pii(msg)})
    return parsed_messages

# --- JSON Parser ---
def parse_json_content(content_str: str) -> list[dict]:
    parsed_messages = []
    data = json.loads(content_str)
    raw_msgs = data.get("messages", [])
    for m in raw_msgs:
        sender = m.get("sender_name")
        content = m.get("content")
        ts_ms = m.get("timestamp_ms")
        
        if sender and content and ts_ms:
            try:
                sender = sender.encode("latin1").decode("utf-8")
                content = content.encode("latin1").decode("utf-8")
            except Exception:
                pass
            dt = datetime.fromtimestamp(ts_ms / 1000.0)
            if content.lower() not in ("sent an attachment.", "null", "liked a message"):
                parsed_messages.append({"timestamp": dt, "sender": sender, "text": mask_pii(content)})
    return parsed_messages

# --- Processor ---
HINDI_WORDS = {
    "yr", "arre", "kya", "ni", "mein", "kr", "bhi", "hn", "rhi", "rha", "hun",
    "fir", "toh", "yaar", "nhi", "aur", "haan", "nahi", "abhi", "kuch", "acha",
    "matlab", "chal", "theek", "bilkul", "bata", "sun", "kal", "aaj", "kyun",
    "waise", "sach", "bas", "phir", "accha",
}

STOPWORDS = {
    "the", "and", "for", "you", "but", "was", "with", "that", "this",
    "are", "have", "not", "from", "they", "will", "been", "what", "when",
    "who", "how", "him", "her", "his", "she", "he", "we", "our", "your", "just",
}

FILLER_RESPONSES = {
    "hm", "haan", "ok", "okay", "haha", "lol", "ha", "hmm", "oh", "achha",
    "accha", "thik h", "theek h", "h", "ni", "ya", "yaar", "hn", "k", "dem",
    "ohh", "acha", "same", "idk", "yea", "yeah", "hi", "hello", "bye", "tc",
    "", "hn ok", "shi h", "hm ok", "oo", "oof", "bruh", "bru", "lmao",
}

EMOTIONAL_WORDS = {
    "sad", "miss", "love", "hate", "angry", "worried", "happy", "lonely",
    "hurt", "sorry", "dil", "yaad", "pyaar", "dard", "khush", "cry", "feel",
    "feeling", "scared", "excited", "bored", "care", "ro", "rona", "dukh",
}

def info_score(pair: dict) -> int:
    ctx_words = len(pair["ctx"].split())
    resp_words = len(pair["resp"].split())
    resp_norm = re.sub(r"[^\w\s]", "", pair["resp"].lower().strip())
    
    if resp_norm in FILLER_RESPONSES or resp_words <= 1:
        return 0
    if ctx_words <= 1 or "click for audio" in pair["ctx"].lower():
        return 1
    if "sent an attachment" in pair["ctx"].lower() and resp_words < 5:
        return 0
    if "#viral" in pair["resp"] or "#fyp" in pair["resp"]:
        return 0
        
    score = min(ctx_words, 20) + min(resp_words * 2, 40)
    if resp_words > 10: score += 20
    if resp_words > 25: score += 30
    if "?" in pair["ctx"]: score += 15
    combined = (pair["ctx"] + " " + pair["resp"]).lower()
    if any(w in combined for w in EMOTIONAL_WORDS): score += 25
    resp_word_set = set(pair["resp"].lower().split())
    hinglish_hits = sum(1 for w in HINDI_WORDS if w in resp_word_set)
    score += hinglish_hits * 5
    if "\n" in pair["resp"] and pair["resp"].count("\n") >= 2: score += 10
    return score

def process_file_data(content: str, filename: str, target_name: str, aliases: list[str]) -> dict:
    lower_fn = filename.lower()
    if lower_fn.endswith(".json"):
        msgs = parse_json_content(content)
    elif lower_fn.endswith(".html") or lower_fn.endswith(".htm"):
        msgs = parse_html_content(content)
    else:
        msgs = parse_whatsapp_content(content)
        
    msgs.sort(key=lambda x: x["timestamp"])
    merged = []
    for m in msgs:
        if not merged:
            merged.append(m)
            continue
        prev = merged[-1]
        time_diff = (m["timestamp"] - prev["timestamp"]).total_seconds()
        if m["sender"] == prev["sender"] and time_diff <= 120:
            prev["text"] += "\n" + m["text"]
            prev["timestamp"] = m["timestamp"]
        else:
            merged.append(m)
            
    target_aliases_lower = [a.lower() for a in aliases] + [target_name.lower()]
    def is_target_sender(sender: str) -> bool:
        s = sender.lower()
        return any(a in s or s in a for a in target_aliases_lower)
        
    pairs = []
    for i in range(1, len(merged)):
        prev = merged[i-1]
        curr = merged[i]
        if is_target_sender(curr["sender"]) and not is_target_sender(prev["sender"]):
            gap = (curr["timestamp"] - prev["timestamp"]).total_seconds()
            if gap <= 7200:
                pairs.append({"ctx": prev["text"].strip(), "resp": curr["text"].strip()})
                
    scored_pairs = []
    for p in pairs:
        score = info_score(p)
        if score >= 5:
            scored_pairs.append((score, p))
            
    scored_pairs.sort(key=lambda x: x[0], reverse=True)
    
    seen_exact = set()
    resp_counter = {}
    final_pairs = []
    for score, pair in scored_pairs:
        exact_key = pair["ctx"].lower().strip() + "||" + pair["resp"].lower().strip()
        if exact_key in seen_exact:
            continue
        seen_exact.add(exact_key)
        
        resp_key = pair["resp"].lower().strip()[:50]
        count = resp_counter.get(resp_key, 0)
        if count >= 3:
            continue
        resp_counter[resp_key] = count + 1
        final_pairs.append(pair)
        
    # Cap to 300 pairs for speed
    final_pairs = final_pairs[:300]
    
    target_msgs = [m["text"] for m in msgs if is_target_sender(m["sender"])]
    lengths = [len(m.split()) for m in target_msgs]
    avg_len = sum(lengths) / max(len(lengths), 1)
    short_ratio = sum(1 for l in lengths if l <= 3) / max(len(lengths), 1)
    long_ratio = sum(1 for l in lengths if l > 15) / max(len(lengths), 1)
    emoji_ratio = sum(1 for m in target_msgs if any(ord(c) > 127 for c in m)) / max(len(target_msgs), 1)
    hinglish = sum(1 for m in target_msgs if any(w in HINDI_WORDS for w in m.lower().split())) / max(len(target_msgs), 1)
    
    all_words = []
    for m in target_msgs:
        all_words.extend(w for w in re.findall(r"[a-zA-Z']+", m.lower()) if w not in STOPWORDS and len(w) > 1)
    top_words = [w for w, _ in Counter(all_words).most_common(40)]
    openers = [w for w, _ in Counter(m.strip().split()[0].lower() for m in target_msgs if m.strip()).most_common(15)]
    
    solo_q = sum(1 for m in target_msgs if m.strip() in ("?", "??", "???"))
    solo_dot = sum(1 for m in target_msgs if m.strip() in (".", "..", "..."))
    uses_caps = sum(1 for m in target_msgs if m and m[0].isupper()) / max(len(target_msgs), 1)
    
    style_card = {
        "total": len(target_msgs),
        "avg_len": round(avg_len, 1),
        "short_ratio": round(short_ratio, 2),
        "long_ratio": round(long_ratio, 2),
        "emoji_ratio": round(emoji_ratio, 2),
        "hinglish": round(hinglish, 2),
        "top_words": top_words,
        "solo_q": solo_q,
        "solo_dot": solo_dot,
        "uses_caps": round(uses_caps, 2),
        "openers": openers,
    }
    
    good_samples = [m for m in target_msgs if re.sub(r"[^\w\s]", "", m.lower().strip()) not in FILLER_RESPONSES and len(m.split()) > 1]
    raw_samples = good_samples[:150]
    
    return {
        "name": target_name,
        "style": style_card,
        "pairs": final_pairs,
        "raw_samples": raw_samples
    }

def embed_batch(texts: list[str]) -> list[list[float]] | None:
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
    try:
        with httpx.Client(timeout=30.0) as client:
            res = client.post(url, json=payload, headers=headers)
            if res.status_code == 200:
                return res.json()["embeddings"]["float"]
    except Exception as e:
        print(f"Cohere embedding failed: {e}")
    return None

def upload_processed_persona(profile_data: dict, owner_hash: str) -> bool:
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        raise ValueError("Supabase keys not configured.")
        
    name = profile_data["name"]
    style = profile_data["style"]
    pairs = profile_data["pairs"]
    raw_samples = profile_data["raw_samples"]
    
    headers = {
        "apikey": SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates"
    }
    
    # 1. Upsert Profile
    profile_url = f"{SUPABASE_URL.rstrip('/')}/rest/v1/profiles"
    style_with_samples = {**style, "raw_samples": raw_samples}
    profile_payload = {
        "name": name,
        "style": style_with_samples,
        "owner": owner_hash
    }
    
    res = httpx.post(f"{profile_url}?on_conflict=name", json=profile_payload, headers=headers, timeout=15.0)
    if res.status_code not in (200, 201):
        print(f"Supabase profile upload failed: {res.text}")
        return False
        
    # 2. Clear old database pairs for this profile
    pairs_url = f"{SUPABASE_URL.rstrip('/')}/rest/v1/pairs"
    httpx.delete(f"{pairs_url}?profile_name=eq.{name}", headers=headers, timeout=15.0)
    
    # 3. Vectorize and upload pairs
    batch_size = 96
    db_insert_batch_size = 150
    cohere_batches = [pairs[i:i + batch_size] for i in range(0, len(pairs), batch_size)]
    pending_inserts = []
    
    for batch in cohere_batches:
        texts = [p["ctx"] + " " + p["resp"] for p in batch]
        vectors = embed_batch(texts)
        if not vectors or len(vectors) != len(batch):
            print("Vectorization batch failed.")
            return False
            
        for pair, vec in zip(batch, vectors):
            pending_inserts.append({
                "profile_name": name,
                "context": pair["ctx"],
                "response": pair["resp"],
                "embedding": vec
            })
            
        if len(pending_inserts) >= db_insert_batch_size:
            res = httpx.post(pairs_url, json=pending_inserts, headers=headers, timeout=30.0)
            if res.status_code not in (200, 201, 204):
                print(f"Supabase pairs upload failed: {res.text}")
                return False
            pending_inserts = []
            
    if pending_inserts:
        res = httpx.post(pairs_url, json=pending_inserts, headers=headers, timeout=30.0)
        if res.status_code not in (200, 201, 204):
            print(f"Supabase pairs final upload failed: {res.text}")
            return False
            
    return True
