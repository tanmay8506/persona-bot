"""
build_persona.py  —  Run ONCE to process chat files.
Outputs persona_profile.json which app.py/backend loads at startup.

Usage:
    python execution/build_persona.py
"""

import re
import json
import os
import sys
from collections import Counter
from datetime import datetime
from bs4 import BeautifulSoup

# Fix Windows console UTF-8 issues
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except AttributeError:
        pass

# Resolve paths relative to project root
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)

def get_absolute_path(rel_path: str) -> str:
    if os.path.isabs(rel_path):
        return rel_path
    return os.path.join(PROJECT_ROOT, rel_path)

# ═══════════════════════════════════════════════════════
# CONFIG — edit before running
# ═══════════════════════════════════════════════════════

TARGET_NAME    = "Anvesha"          # display name used in the profile
TARGET_ALIASES = [                  # all names this person appears under in chat files
    "Anvesha/bhoomi PME P",         # WhatsApp name
    "Anvesha",                      # Messenger/Instagram name
]
OUTPUT_FILE  = get_absolute_path("persona_profile.json")

CHAT_FILES = [
    # (path, type)  — type is "whatsapp" or "html" or "json" or "transcript"
    (get_absolute_path("files/Atxt.txt"),       "whatsapp"),
    (get_absolute_path("files/Wapp.txt"),       "whatsapp"),
    (get_absolute_path("files/A2.txt"),         "whatsapp"),
    (get_absolute_path("files/message_1.html"), "html"),
    (get_absolute_path("files/message_2.html"), "html"),
    (get_absolute_path("files/chat_transcript.txt"), "transcript"),
]

MAX_SAME_RESPONSE   = 3    # max times same response kept (dedup)
MIN_PAIR_SCORE      = 5    # pairs below this score are dropped
RAW_SAMPLE_COUNT    = 200  # raw solo messages stored for tone reference

# Max gap allowed between context and response to form a pair (in seconds)
MAX_PAIR_GAP_SECONDS = 7200 # 2 hours
# Gap to merge consecutive messages from the same sender (in seconds)
MERGE_BURST_GAP_SECONDS = 120 # 2 minutes

# ═══════════════════════════════════════════════════════

# ── Timestamp Parser ─────────────────────────────────────────────────────────

DATE_FORMATS = [
    # Standard format formats
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
    # Seconds variations
    "%m/%d/%y, %I:%M:%S %p",
    "%d/%m/%Y, %H:%M:%S",
]

def parse_datetime(dt_str: str) -> datetime | None:
    """Try to parse a datetime string using a list of formats."""
    # Clean up standard variations in spacing and capitalization
    clean_str = re.sub(r'\s+', ' ', dt_str.strip())
    # Strip brackets if present
    clean_str = clean_str.strip('[]')
    
    # Try direct parse
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(clean_str, fmt)
        except ValueError:
            continue
            
    # Try parsing case-insensitively for months and AM/PM
    for fmt in DATE_FORMATS:
        try:
            # Reconstruct string capitalization to match format if it contains %b, %B, or %p
            test_str = clean_str
            if "%p" in fmt:
                # Ensure AM/PM is capitalized
                test_str = test_str.replace("am", "AM").replace("pm", "PM")
            if "%b" in fmt or "%B" in fmt:
                # Title-case first letters
                test_str = test_str.title()
            return datetime.strptime(test_str, fmt)
        except ValueError:
            continue
            
    return None

# ── Parsers ──────────────────────────────────────────────────────────────────

def parse_whatsapp(path: str) -> list[dict]:
    """
    Parses WhatsApp exports supporting multiple formats,
    correctly buffering multi-line messages.
    """
    # Regex patterns to detect timestamps
    patterns = [
        # Standard: 12/31/23, 10:30 PM - Sender: msg
        re.compile(r"^(\d{1,2}/\d{1,2}/\d{2,4},\s*\d{1,2}:\d{2}(?:\s*[aApP][mM])?)\s*-\s*([^:]+):\s*(.+)"),
        # EU format: 31.12.23, 22:30 - Sender: msg
        re.compile(r"^(\d{1,2}\.\d{1,2}\.\d{2,4},\s*\d{1,2}:\d{2}(?:\s*[aApP][mM])?)\s*-\s*([^:]+):\s*(.+)"),
        # Bracket format: [12/31/23, 10:30:15 PM] Sender: msg
        re.compile(r"^\[(\d{1,2}/\d{1,2}/\d{2,4},\s*\d{1,2}:\d{2}(?::\d{2})?(?:\s*[aApP][mM])?)\]\s*([^:]+):\s*(.+)"),
        # 24hr EU bracket: [31/12/2023, 22:30:00] Sender: msg
        re.compile(r"^\[(\d{1,2}/\d{1,2}/\d{4},\s*\d{1,2}:\d{2}:\d{2})\]\s*([^:]+):\s*(.+)"),
    ]
    
    parsed_messages = []
    current_msg = None
    
    with open(path, encoding="utf-8", errors="ignore") as f:
        for line in f:
            line_str = line.strip('\n') # keep spacing but strip trailing newline
            matched = False
            
            # Check if this line is the start of a new message
            for pat in patterns:
                m = pat.match(line_str.strip())
                if m:
                    # Save current message if buffered
                    if current_msg:
                        parsed_messages.append(current_msg)
                        
                    dt_str = m.group(1).strip()
                    sender = m.group(2).strip()
                    body   = m.group(3).strip()
                    
                    dt = parse_datetime(dt_str)
                    if not dt:
                        # Fallback to current time if unparseable
                        dt = datetime.now()
                        
                    current_msg = {
                        "timestamp": dt,
                        "sender": sender,
                        "text": body
                    }
                    matched = True
                    break
            
            if not matched:
                # Continue last message if it exists
                if current_msg:
                    current_msg["text"] += "\n" + line_str.strip()
                # Otherwise ignore leading garbage
                
        # Append last message
        if current_msg:
            parsed_messages.append(current_msg)
            
    # Post-process filters
    clean_messages = []
    for m in parsed_messages:
        msg = re.sub(r"<[Tt]his message was edited>", "", m["text"]).strip()
        if not msg:
            continue
        if msg.lower() in ("<media omitted>", "this message was deleted", "null", "image omitted", "sticker omitted"):
            continue
        if "end-to-end encrypted" in msg.lower():
            continue
        # Mask PII
        msg = mask_pii(msg)
        m["text"] = msg
        clean_messages.append(m)
        
    return clean_messages


def parse_html(path: str) -> list[dict]:
    """
    Parses Instagram HTML logs extracting sender, message and timestamp.
    HTML exports are reverse-chronological, but sorting them in timeline_sorting
    ensures proper order.
    """
    with open(path, encoding="utf-8", errors="ignore") as f:
        html = f.read()
    soup = BeautifulSoup(html, "html.parser")
    parsed_messages = []
    
    blocks = soup.find_all(
        "div", class_=lambda c: c and "uiBoxWhite" in c and "noborder" in c
    )
    for block in blocks:
        sender_tag = block.find("h2")
        text_tag   = block.find(class_=lambda c: c and "_a6-p" in c)
        time_tag   = block.find(class_=lambda c: c and "_a6-o" in c)
        
        if sender_tag and text_tag:
            sender = sender_tag.get_text(strip=True)
            msg    = text_tag.get_text(separator=" ", strip=True).strip()
            
            dt = datetime.now()
            if time_tag:
                dt_str = time_tag.get_text(strip=True)
                parsed_dt = parse_datetime(dt_str)
                if parsed_dt:
                    dt = parsed_dt
            
            if msg and sender:
                # Filter IG forwards & system text
                if msg.lower() in ("sent an attachment.", "null", "liked a message"):
                    continue
                msg = mask_pii(msg)
                parsed_messages.append({
                    "timestamp": dt,
                    "sender": sender,
                    "text": msg
                })
                
    return parsed_messages


def parse_json(path: str) -> list[dict]:
    """
    Optional Instagram JSON parser for compatibility.
    """
    parsed_messages = []
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        
        # Expecting Instagram Messages format: {"messages": [{"sender_name": "...", "content": "...", "timestamp_ms": ...}]}
        raw_msgs = data.get("messages", [])
        for m in raw_msgs:
            sender = m.get("sender_name")
            content = m.get("content")
            ts_ms = m.get("timestamp_ms")
            
            if sender and content and ts_ms:
                # Decode latin1 to utf-8 (Instagram JSON export quirk)
                try:
                    sender = sender.encode("latin1").decode("utf-8")
                    content = content.encode("latin1").decode("utf-8")
                except (UnicodeEncodeError, UnicodeDecodeError):
                    pass
                
                dt = datetime.fromtimestamp(ts_ms / 1000.0)
                content = mask_pii(content)
                parsed_messages.append({
                    "timestamp": dt,
                    "sender": sender,
                    "text": content
                })
    except Exception as e:
        print(f"  ⚠️  JSON parse error on {path}: {e}")
        
    return parsed_messages


def parse_transcript(path: str) -> list[dict]:
    """
    Parses hand-compiled chat logs matching:
      Sender (Time): Message
      e.g., Anvesha (7:53 PM): Aaram se
    """
    parsed_messages = []
    # Match: Name (time): Message
    pat = re.compile(r"^([^(\n]+)\s*\(([^)]+)\):\s*(.+)")
    with open(path, encoding="utf-8", errors="ignore") as f:
        for line in f:
            line_str = line.strip()
            # Ignore section dividers or blank lines
            if line_str.startswith("---") or line_str.startswith("===") or not line_str:
                continue
                
            m = pat.match(line_str)
            if m:
                sender = m.group(1).strip()
                time_str = m.group(2).strip()
                body = m.group(3).strip()
                
                # Parse timestamp
                try:
                    dt = datetime.strptime(time_str, "%I:%M %p")
                except ValueError:
                    dt = datetime.now()
                    
                body = mask_pii(body)
                parsed_messages.append({
                    "timestamp": dt,
                    "sender": sender,
                    "text": body
                })
    return parsed_messages


# ── PII Masker ────────────────────────────────────────────────────────────────

def mask_pii(text: str) -> str:
    """Masks phone numbers and emails to preserve privacy."""
    # Email pattern
    email_pat = r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+"
    text = re.sub(email_pat, "[Email]", text)
    
    # Phone pattern (various international/national layouts, 10+ digits)
    phone_pat = r"(\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4,6}\b"
    text = re.sub(phone_pat, "[Phone]", text)
    
    return text

# ── Chronological Timeline Sorting & Burst Merging ─────────────────────────────

def sort_and_merge_bursts(messages: list[dict]) -> list[dict]:
    """
    Sorts all parsed messages chronologically.
    Then merges bursts (messages from the same sender within 2 minutes).
    """
    # Sort chronologically by actual timestamp
    messages.sort(key=lambda x: x["timestamp"])
    
    merged = []
    for m in messages:
        if not merged:
            merged.append(m)
            continue
            
        prev = merged[-1]
        time_diff = (m["timestamp"] - prev["timestamp"]).total_seconds()
        
        if m["sender"] == prev["sender"] and time_diff <= MERGE_BURST_GAP_SECONDS:
            # Merge with newline
            prev["text"] += "\n" + m["text"]
            # Keep the last timestamp as the latest in burst
            prev["timestamp"] = m["timestamp"]
        else:
            merged.append(m)
            
    return merged

# ── Turn + pair builder ───────────────────────────────────────────────────────

def build_turns(messages: list[dict]) -> list[dict]:
    """Alternate consecutive messages into conversation turns."""
    turns = []
    for m in messages:
        turns.append({
            "sender": m["sender"],
            "text": m["text"],
            "timestamp": m["timestamp"]
        })
    return turns


def is_target(sender: str) -> bool:
    """Match sender against all aliases."""
    s = sender.lower()
    return any(a.lower() in s or s in a.lower() for a in TARGET_ALIASES)


def build_pairs(turns: list) -> list[dict]:
    """
    Build context-response pairs. Context is Q, Response is Target's reply.
    Only form a pair if context and response are from alternating speakers
    and occurred within 2 hours of each other (prevents chronological leakage).
    """
    pairs = []
    for i in range(1, len(turns)):
        prev = turns[i - 1]
        curr = turns[i]
        
        # We need the response to be by the target, and context by someone else
        if is_target(curr["sender"]) and not is_target(prev["sender"]):
            gap = (curr["timestamp"] - prev["timestamp"]).total_seconds()
            if gap <= MAX_PAIR_GAP_SECONDS:
                pairs.append({
                    "ctx": prev["text"].strip(),
                    "resp": curr["text"].strip()
                })
    return pairs

# ── Normaliser ────────────────────────────────────────────────────────────────

def normalise(text: str) -> str:
    t = text.lower().strip()
    t = re.sub(r"[^\w\s]", "", t)
    t = re.sub(r"\s+", " ", t)
    return t

# ── Information Scorer ────────────────────────────────────────────────────────

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

HINDI_WORDS = {
    "yr", "arre", "kya", "ni", "mein", "kr", "bhi", "hn", "rhi", "rha", "hun",
    "fir", "toh", "yaar", "nhi", "aur", "haan", "nahi", "abhi", "kuch", "acha",
    "matlab", "chal", "theek", "bilkul", "bata", "sun", "kal", "aaj", "kyun",
    "waise", "sach", "bas", "phir", "accha",
}


def info_score(pair: dict) -> int:
    ctx_words  = len(pair["ctx"].split())
    resp_words = len(pair["resp"].split())
    resp_norm  = normalise(pair["resp"])

    # Drop pure filler responses
    if resp_norm in FILLER_RESPONSES or resp_words <= 1:
        return 0

    # Drop empty/audio-only contexts
    if ctx_words <= 1 or "click for audio" in pair["ctx"].lower():
        return 1

    # Drop pairs that are just reel/attachment forwards
    if "sent an attachment" in pair["ctx"].lower() and resp_words < 5:
        return 0
    if "#viral" in pair["resp"] or "#fyp" in pair["resp"]:
        return 0

    # Base: length signal
    score = min(ctx_words, 20) + min(resp_words * 2, 40)

    # Boost: substantial response
    if resp_words > 10:  score += 20
    if resp_words > 25:  score += 30
    if resp_words > 50:  score += 20

    # Boost: question in context (model learns how she answers things)
    if "?" in pair["ctx"]:
        score += 15

    # Boost: emotional exchanges (rare but very characterful)
    combined = (pair["ctx"] + " " + pair["resp"]).lower()
    if any(w in combined for w in EMOTIONAL_WORDS):
        score += 25

    # Boost: authentic Hinglish in response
    resp_word_set = set(pair["resp"].lower().split())
    hinglish_hits = sum(1 for w in HINDI_WORDS if w in resp_word_set)
    score += hinglish_hits * 5

    # Boost: multi-message burst response (authentic texting pattern)
    if "\n" in pair["resp"] and pair["resp"].count("\n") >= 2:
        score += 10

    return score

# ── Smart deduplicator ────────────────────────────────────────────────────────

def deduplicate(scored_pairs: list[tuple[int, dict]]) -> list[dict]:
    """
    Keep highest-scoring unique pairs.
    """
    seen_exact   = set()
    resp_counter = {}
    final        = []

    for score, pair in scored_pairs:
        if score < MIN_PAIR_SCORE:
            continue

        # Exact dedup
        exact_key = normalise(pair["ctx"])[:80] + "||" + normalise(pair["resp"])[:80]
        if exact_key in seen_exact:
            continue
        seen_exact.add(exact_key)

        # Cap same response
        resp_key = normalise(pair["resp"])[:50]
        count = resp_counter.get(resp_key, 0)
        if count >= MAX_SAME_RESPONSE:
            continue
        resp_counter[resp_key] = count + 1

        final.append(pair)

    return final

# ── Style analyser ────────────────────────────────────────────────────────────

STOPWORDS = {
    "the", "and", "for", "you", "but", "was", "with", "that", "this",
    "are", "have", "not", "from", "they", "will", "been", "what", "when",
    "who", "how", "him", "her", "his", "she", "he", "we", "our", "your", "just",
}


def analyse_style(messages: list[str]) -> dict:
    lengths     = [len(m.split()) for m in messages]
    avg_len     = sum(lengths) / max(len(lengths), 1)
    short_ratio = sum(1 for l in lengths if l <= 3) / max(len(lengths), 1)
    long_ratio  = sum(1 for l in lengths if l > 15) / max(len(lengths), 1)
    emoji_ratio = sum(1 for m in messages if any(ord(c) > 127 for c in m)) / max(len(messages), 1)
    hinglish    = sum(
        1 for m in messages if any(w in HINDI_WORDS for w in m.lower().split())
    ) / max(len(messages), 1)

    all_words = []
    for m in messages:
        all_words.extend(
            w for w in re.findall(r"[a-zA-Z']+", m.lower())
            if w not in STOPWORDS and len(w) > 1
        )
    top_words = [w for w, _ in Counter(all_words).most_common(40)]
    openers   = [
        w for w, _ in Counter(
            m.strip().split()[0].lower() for m in messages if m.strip()
        ).most_common(15)
    ]

    solo_q   = sum(1 for m in messages if m.strip() in ("?", "??", "???"))
    solo_dot = sum(1 for m in messages if m.strip() in (".", "..", "..."))
    uses_caps = sum(1 for m in messages if m and m[0].isupper()) / max(len(messages), 1)

    return {
        "total":       len(messages),
        "avg_len":     round(avg_len, 1),
        "short_ratio": round(short_ratio, 2),
        "long_ratio":  round(long_ratio, 2),
        "emoji_ratio": round(emoji_ratio, 2),
        "hinglish":    round(hinglish, 2),
        "top_words":   top_words,
        "solo_q":      solo_q,
        "solo_dot":    solo_dot,
        "uses_caps":   round(uses_caps, 2),
        "openers":     openers,
    }

# ── Keyword index ─────────────────────────────────────────────────────────────

def build_keyword_index(pairs: list[dict]) -> dict[str, list[int]]:
    """Map keyword → list of pair indices for fast local RAG lookup fallback."""
    index: dict[str, list[int]] = {}
    for i, pair in enumerate(pairs):
        text  = pair["ctx"] + " " + pair["resp"]
        words = set(
            w for w in re.findall(r"[a-zA-Z']+", text.lower())
            if len(w) > 2 and w not in STOPWORDS
        )
        # Also index Hindi words
        words |= set(
            w for w in text.lower().split()
            if w in HINDI_WORDS and len(w) > 1
        )
        for w in words:
            index.setdefault(w, []).append(i)
    return index

# ── Raw sample selector ───────────────────────────────────────────────────────

def select_raw_samples(messages: list[str], n: int) -> list[str]:
    good = [m for m in messages if normalise(m) not in FILLER_RESPONSES and len(m.split()) > 1]
    if len(good) <= n:
        return good
    step = len(good) / n
    return [good[int(i * step)] for i in range(n)]

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("  Persona Preprocessor (Chronological & Buffered)")
    print("=" * 60)

    # Load files
    all_msgs: list[dict] = []
    for path, ftype in CHAT_FILES:
        if not os.path.exists(path):
            print(f"  ⚠️  Not found: {path} — skipping")
            continue
        try:
            if ftype == "whatsapp":
                msgs = parse_whatsapp(path)
            elif ftype == "html":
                msgs = parse_html(path)
            elif ftype == "json":
                msgs = parse_json(path)
            elif ftype == "transcript":
                msgs = parse_transcript(path)
            else:
                continue
            print(f"  ✅  {path}: {len(msgs)} messages")
            all_msgs.extend(msgs)
        except Exception as e:
            print(f"  ❌  {path}: {e}")

    if not all_msgs:
        print("No messages loaded. Check CHAT_FILES paths.")
        return

    # Normalise all aliases → TARGET_NAME for consistent processing
    for m in all_msgs:
        if is_target(m["sender"]):
            m["sender"] = TARGET_NAME

    senders = list(dict.fromkeys(s["sender"] for s in all_msgs))
    print(f"\nSenders found: {senders}")
    print(f"Target aliases merged into: '{TARGET_NAME}'")

    if TARGET_NAME not in senders:
        print(f"❌ '{TARGET_NAME}' not found after alias merging. Check TARGET_ALIASES.")
        return

    # Timeline sorting and message burst merging
    print("\nSorting chronologically and merging message bursts...")
    merged_msgs = sort_and_merge_bursts(all_msgs)
    print(f"  Before merge: {len(all_msgs):,} messages")
    print(f"  After merge:  {len(merged_msgs):,} messages")

    target_msgs = [m["text"] for m in merged_msgs if m["sender"] == TARGET_NAME]
    print(f"Target messages: {len(target_msgs):,}")

    # Build turns and pairs
    turns     = build_turns(merged_msgs)
    all_pairs = build_pairs(turns)
    print(f"Conversation pairs: {len(all_pairs):,}")

    # Score
    print("\nScoring pairs by information value...")
    scored = [(info_score(p), p) for p in all_pairs]
    scored.sort(key=lambda x: x[0], reverse=True)

    dist = Counter(
        "zero" if s == 0 else "low" if s < 21 else "medium" if s < 51 else "high" if s < 81 else "very_high"
        for s, _ in scored
    )
    for label in ["zero", "low", "medium", "high", "very_high"]:
        print(f"  {label:10}: {dist.get(label, 0):4} pairs")

    # Dedup
    print("\nDeduplicating...")
    final_pairs = deduplicate(scored)
    print(f"  Before dedup: {sum(1 for s,_ in scored if s >= MIN_PAIR_SCORE):,}")
    print(f"  After dedup:  {len(final_pairs):,}")

    # Style
    print("\nAnalysing style...")
    style = analyse_style(target_msgs)
    print(f"  Avg length    : {style['avg_len']} words")
    print(f"  Short ratio   : {style['short_ratio']*100:.0f}%")
    print(f"  Long ratio    : {style['long_ratio']*100:.0f}%")
    print(f"  Hinglish      : {style['hinglish']*100:.0f}%")
    print(f"  Top words     : {style['top_words'][:12]}")

    # Keyword index
    print("\nBuilding keyword index...")
    kw_index = build_keyword_index(final_pairs)
    print(f"  Keywords: {len(kw_index):,}")

    # Raw samples
    raw_samples = select_raw_samples(target_msgs, RAW_SAMPLE_COUNT)

    # Assemble
    profile = {
        "name":           TARGET_NAME,
        "style":          style,
        "pairs":          final_pairs,
        "keyword_index":  kw_index,
        "raw_samples":    raw_samples,
        "total_messages": len(target_msgs),
        "total_pairs":    len(all_pairs),
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(profile, f, ensure_ascii=False, indent=2)

    size_kb = os.path.getsize(OUTPUT_FILE) / 1024
    print(f"\n✅ Saved: {OUTPUT_FILE} ({size_kb:.0f} KB)")
    print(f"   {len(final_pairs):,} high-signal pairs  |  {len(kw_index):,} keywords  |  {len(raw_samples)} tone samples")
    print(f"\nNow run: python execution/build_embeddings.py")


if __name__ == "__main__":
    main()
