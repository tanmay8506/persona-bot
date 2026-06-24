"""
api/index.py — FastAPI serverless endpoints for Next.js monorepo routing.
"""

import os
import datetime
from fastapi import FastAPI, Header, HTTPException, Depends, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

from api.database import (
    get_profile,
    get_profiles_list,
    create_conversation,
    get_conversation_history,
    save_message,
    ACCESS_PASSCODE
)
from api.retriever import retrieve_few_shots
from api.llm import (
    assemble_prompt,
    call_groq_with_retry,
    is_repeat,
    is_bad_response,
    clean_response,
    detect_tone,
    introduce_typo,
    build_pinned_system,
    fix_gender_slips
)

load_dotenv()

app = FastAPI(title="Persona Bot Serverless API")

# Add CORS middleware for local development cross-origin requests
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


import traceback
from fastapi.responses import JSONResponse

@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    return JSONResponse(
        status_code=500,
        content={
            "detail": str(exc),
            "traceback": traceback.format_exc()
        }
    )


# ── Passcode Hashing and Verification Middleware ───────────────────────────────

import hashlib

def hash_passcode(passcode: str) -> str:
    return hashlib.sha256(passcode.encode("utf-8")).hexdigest()

ADMIN_PASSCODE = os.getenv("ACCESS_PASSCODE", "12345")
ADMIN_HASH = hash_passcode(ADMIN_PASSCODE)

async def verify_passcode(authorization: str = Header(None)) -> str:
    """
    Extracts the authorization token (passcode), hashes it, and returns the owner_hash.
    If no passcode is provided, raises 401.
    """
    token = ""
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ")[1]
        
    token = token.strip()
    if not token:
        raise HTTPException(
            status_code=401,
            detail="Unauthorized. Passcode is required."
        )
    return hash_passcode(token)



# ── Request Models ────────────────────────────────────────────────────────────

class ConversationCreate(BaseModel):
    profile_name: str

class PersonaConfig(BaseModel):
    hinglish_ratio: float = 0.45
    elongation_rate: float = 0.5
    burstiness: float = 0.5
    intimacy: float = 0.5

class ChatRequest(BaseModel):
    conversation_id: str
    message: str
    config: PersonaConfig = PersonaConfig()


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/api/health")
def health_check():
    return {"status": "ok", "message": "Persona Bot API is running."}


@app.get("/api/profiles")
def list_profiles(owner_hash: str = Depends(verify_passcode)):
    """Returns list of available personas in Supabase filtered by owner."""
    profiles = get_profiles_list(owner_hash, ADMIN_HASH)
    # If Supabase is empty and user is admin, check if we have a local persona_profile.json
    # and upload it dynamically if found. This bootstraps first-time local setup.
    if not profiles and owner_hash == ADMIN_HASH:
        import json
        local_profile_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "persona_profile.json")
        if os.path.exists(local_profile_path):
            try:
                with open(local_profile_path, encoding="utf-8") as f:
                    p_data = json.load(f)
                
                # Check if it has embeddings sync, if not sync is needed but we return it as fallback
                return [{"name": p_data["name"], "created_at": "local_file"}]
            except Exception:
                pass
    return profiles


@app.post("/api/conversations")
def start_chat(data: ConversationCreate, owner_hash: str = Depends(verify_passcode)):
    """Creates a persistent chat session in database."""
    # Verify profile ownership/access
    profile = get_profile(data.profile_name, owner_hash, ADMIN_HASH)
    if not profile:
        raise HTTPException(status_code=403, detail="Access denied. You do not own this profile.")
        
    convo_id = create_conversation(data.profile_name, owner_hash)
    if not convo_id:
        raise HTTPException(status_code=500, detail="Failed to initialize conversation session.")
    return {"conversation_id": convo_id}


@app.post("/api/chat")
def send_chat_message(data: ChatRequest, owner_hash: str = Depends(verify_passcode)):
    """
    Main conversational loop.
    Assembles prompt, retrieve matched pairs, calls Groq, saves and returns message.
    """
    convo_id = data.conversation_id
    message = data.message.strip()
    
    if not message:
        raise HTTPException(status_code=400, detail="Message cannot be empty.")
        
    # Verify caller owns this conversation session
    from api.database import get_conversation_owner
    convo_owner = get_conversation_owner(convo_id)
    
    is_owner = False
    if owner_hash == ADMIN_HASH:
        is_owner = (convo_owner == ADMIN_HASH or not convo_owner)
    else:
        is_owner = (convo_owner == owner_hash)
        
    if not is_owner:
        raise HTTPException(status_code=403, detail="Access denied. You do not own this conversation.")
        
    # 1. Retrieve Conversation history (last 12 messages for full context)
    history = get_conversation_history(convo_id, limit=12)
    
    # Identify profile name
    profile_name = None
    if history:
        # If history exists, extract profile name (from table relation) or we lookup the conversation record.
        # But to be fast, we query conversations table to find the profile it connects to.
        # PostgREST URL lookup for conversation row
        from api.database import get_supabase_rest_url, get_headers
        import httpx
        url = f"{get_supabase_rest_url('conversations')}?id=eq.{convo_id}&select=profile_name"
        try:
            with httpx.Client() as client:
                res = client.get(url, headers=get_headers())
                if res.status_code == 200:
                    c_data = res.json()
                    if c_data:
                        profile_name = c_data[0]["profile_name"]
        except Exception:
            pass
            
    if not profile_name:
        # Default fallback (look at folders or assume first loaded profile name)
        profiles = get_profiles_list(owner_hash, ADMIN_HASH)
        if profiles:
            profile_name = profiles[0]["name"]
        else:
            profile_name = "Anvesha" # absolute hardcoded default
            
    # 2. Fetch profile card
    profile = get_profile(profile_name, owner_hash, ADMIN_HASH)
    if not profile and owner_hash == ADMIN_HASH:
        # Check if local profile receipt can bootstrap it
        import json
        local_profile_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "persona_profile.json")
        if os.path.exists(local_profile_path):
            with open(local_profile_path, encoding="utf-8") as f:
                profile = json.load(f)
                
    if not profile:
         raise HTTPException(status_code=404, detail="Target profile not found. Run preprocessors first.")
         
    # Format history structure to match assembling prompt format
    formatted_history = []
    for h in history:
        formatted_history.append({
            "role": "assistant" if h["role"] == "assistant" else "user",
            "content": h["content"]
        })
        
    # 3. Save User message to Database immediately
    save_message(convo_id, "user", message)
    
    # 4. Fetch semantic few-shots (context-aware transition RAG)
    # Check if message is a short dead zone filler word to preserve raw sample fallback
    import re
    clean = re.sub(r'[^\w\s]', '', message.lower()).strip()
    words = set(clean.split())
    dead_zone_words = {
        "ok","okay","k","hm","hmm","what","why","how","hi","hey","hello","bye",
        "yes","no","sure","fine","nice","good","bad","lol","haha","omg","really",
        "oh","ah","ugh","bro","man","dude","wait","stop","go","come","see",
    }
    is_dz = len(words) <= 2 and words.issubset(dead_zone_words)
    
    retrieval_query = message
    if not is_dz:
        last_assistant_content = ""
        for h in reversed(formatted_history):
            if h["role"] == "assistant":
                last_assistant_content = h["content"]
                break
        if last_assistant_content:
            last_line = last_assistant_content.split("\n")[-1].strip()
            retrieval_query = f"{last_line} -> {message}"
            
    few_shots = retrieve_few_shots(profile_name, retrieval_query, limit=6)
    
    # Detect tone/vibe
    tone = detect_tone(message, formatted_history)

    # 5. Assemble Prompt layers
    prompt_msgs = assemble_prompt(message, formatted_history, profile, few_shots, config=data.config.dict() if data.config else None)
    
    # Calculate custom parameters based on live config and tone
    temp_override = None
    freq_override = None
    pres_override = None
    if data.config:
        temp_override = 0.65 + (data.config.elongation_rate * 0.20)
        freq_override = 0.25 + (data.config.elongation_rate * 0.45)
        pres_override = 0.15 + (data.config.intimacy * 0.4)
        
    # Tone-based overrides for Groq hyperparameters
    if tone == "emotional":
        temp_override = 0.88 if temp_override is None else min(1.0, temp_override + 0.06)
        pres_override = 0.6 if pres_override is None else min(1.0, pres_override + 0.25)
    elif tone == "tired":
        temp_override = 0.62 if temp_override is None else max(0.5, temp_override - 0.12)
        pres_override = 0.1 if pres_override is None else max(0.0, pres_override - 0.2)
    elif tone == "annoyed":
        temp_override = 0.70 if temp_override is None else max(0.6, temp_override - 0.08)
        pres_override = 0.15 if pres_override is None else max(0.0, pres_override - 0.15)

    # 6. Generate reply with retry logic
    # Tweak Groq variety based on elongation slider (higher elongation -> higher variety/temperature)
    force_variety = False
    if data.config and data.config.elongation_rate > 0.7:
        force_variety = True
    reply = call_groq_with_retry(
        prompt_msgs, 
        force_variety=force_variety, 
        temp=temp_override, 
        freq_penalty=freq_override, 
        pres_penalty=pres_override
    )
    
    # 7. Safeguard 1: AI Bleed-through Filter Retry
    if is_bad_response(reply):
        retry_prompt = prompt_msgs + [{
            "role": "system",
            "content": f"Stay in character as {profile_name}. Do not output AI metadata, disclaimers, or introductory headings. Just text back."
        }]
        reply = call_groq_with_retry(
            retry_prompt, 
            temp=temp_override, 
            freq_penalty=freq_override, 
            pres_penalty=pres_override
        )
        
    # 8. Safeguard 2: Repetition / Streak Blocker Retry
    if is_repeat(reply, formatted_history):
        variety_prompt = prompt_msgs + [{
            "role": "system",
            "content": "Say something different this time. You are repeating the same phrasing as before."
        }]
        reply = call_groq_with_retry(
            variety_prompt, 
            force_variety=True, 
            temp=temp_override, 
            freq_penalty=freq_override, 
            pres_penalty=pres_override
        )
        
    # 9. Clean up final response text
    reply = clean_response(reply)
    
    # Correct Hinglish first-person gender slips (masculine endings)
    reply = fix_gender_slips(reply)
    
    # Apply Pointer 3: Emulated Typos and Correction Bursts
    reply = introduce_typo(reply)
    
    # 10. Save Assistant reply to Database
    save_message(convo_id, "assistant", reply)
    
    return {"role": "assistant", "content": reply, "vibe": tone}


# ── Pointer 4: Reactive Opening Cron Helpers & Endpoint ───────────────────────

def parse_supabase_time(time_str: str) -> datetime.datetime:
    import datetime
    # Remove Z suffix if present
    clean_str = time_str.replace("Z", "")
    # Split by + offset if present
    clean_str = clean_str.split("+")[0]
    # Split subseconds if present
    clean_str = clean_str.split(".")[0]
    return datetime.datetime.strptime(clean_str, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=datetime.timezone.utc)


@app.get("/api/cron/reactive_open")
def cron_reactive_open(x_vercel_cron: str = Header(None)):
    """Vercel cron endpoint called periodically to trigger reactive openers on idle chats."""
    import datetime
    import httpx
    
    # Verify header if VERCEL environment is set
    if os.getenv("VERCEL") and x_vercel_cron != "1":
        raise HTTPException(status_code=401, detail="Unauthorized cron trigger.")

    headers = get_headers()
    convos_url = f"{get_supabase_rest_url('conversations')}?select=id,profile_name"
    triggered = []

    try:
        with httpx.Client() as client:
            res = client.get(convos_url, headers=headers)
            if res.status_code != 200:
                raise HTTPException(status_code=500, detail=f"Failed to fetch conversations: {res.text}")
            
            conversations = res.json()
            for c in conversations:
                convo_id = c["id"]
                profile_name = c["profile_name"]
                
                # Fetch last message in this conversation
                msg_url = f"{get_supabase_rest_url('messages')}?conversation_id=eq.{convo_id}&order=created_at.desc&limit=1"
                m_res = client.get(msg_url, headers=headers)
                if m_res.status_code == 200:
                    messages = m_res.json()
                    if not messages:
                        continue
                    
                    last_msg = messages[0]
                    # Parse timestamp using clean parsing utility
                    last_time = parse_supabase_time(last_msg["created_at"])
                    now_utc = datetime.datetime.now(datetime.timezone.utc)
                    gap_hours = (now_utc - last_time).total_seconds() / 3600.0
                    
                    # Only trigger if the user sent the last message and the gap is > 18 hours
                    if gap_hours > 18.0 and last_msg["role"] == "user":
                        # Generate reactive opener
                        # Fetch conversation history (last 8 messages)
                        hist_url = f"{get_supabase_rest_url('messages')}?conversation_id=eq.{convo_id}&order=created_at.asc&limit=8"
                        h_res = client.get(hist_url, headers=headers)
                        history = []
                        if h_res.status_code == 200:
                            for h in h_res.json():
                                history.append({
                                    "role": "assistant" if h["role"] == "assistant" else "user",
                                    "content": h["content"]
                                })
                        
                        # Fetch profile style
                        profile = get_profile(profile_name)
                        if not profile:
                            continue
                            
                        # Build system instructions
                        pinned_prompt = build_pinned_system(profile, active_vibe="casual")
                        
                        prompt_msgs = [
                            {"role": "system", "content": pinned_prompt},
                            {"role": "system", "content": "[Context: You haven't texted Tanmay in 18+ hours. You are initiating a conversation out of the blue. Write a short, casual starting text in Hinglish like 'kya kr rha h?', 'sunnn', or tease him based on the last conversation topic. Do NOT reply to his last question or repeat yourself. Keep it under 6 words, lowercase only, no punctuation.]"}
                        ]
                        
                        for h in history:
                            prompt_msgs.append({"role": h["role"], "content": h["content"]})
                            
                        reply = call_groq_with_retry(prompt_msgs, temp=0.85, pres_penalty=0.4)
                        reply = clean_response(reply)
                        reply = fix_gender_slips(reply)
                        
                        if reply and not reply.startswith("⚠️"):
                            save_message(convo_id, "assistant", reply)
                            triggered.append({"convo_id": convo_id, "message": reply})
                            
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {"status": "ok", "triggered": triggered}


@app.post("/api/upload_chat")
async def upload_chat(
    file: UploadFile = File(...),
    name: str = Form(...),
    aliases: str = Form(""),
    owner_hash: str = Depends(verify_passcode)
):
    target_name = name.strip()
    if not target_name:
        raise HTTPException(status_code=400, detail="Persona name cannot be empty.")
        
    if target_name.lower() == "anvesha" and owner_hash != ADMIN_HASH:
        raise HTTPException(status_code=403, detail="The name 'Anvesha' is reserved.")
        
    alias_list = [a.strip() for a in aliases.split(",") if a.strip()]
    
    try:
        content = await file.read()
        content_str = content.decode("utf-8", errors="ignore")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to read file: {str(e)}")
        
    # Check if profile already exists and check ownership (bypass owner filter for check)
    existing_profile = get_profile(target_name)
    if existing_profile:
        existing_owner = existing_profile.get("owner")
        is_owner = False
        if owner_hash == ADMIN_HASH:
            is_owner = (existing_owner == ADMIN_HASH or not existing_owner)
        else:
            is_owner = (existing_owner == owner_hash)
            
        if not is_owner:
            raise HTTPException(status_code=403, detail="Persona name already taken. Please choose a different name.")
            
    from api.uploader import process_file_data, upload_processed_persona
    try:
        profile_data = process_file_data(content_str, file.filename, target_name, alias_list)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to parse chat data: {str(e)}")
        
    if not profile_data["pairs"]:
        raise HTTPException(
            status_code=400, 
            detail="No valid chat turns could be parsed from the file. Make sure the file format is supported and aliases/name are correct."
        )
        
    try:
        success = upload_processed_persona(profile_data, owner_hash)
        if not success:
            raise HTTPException(status_code=500, detail="Failed to upload vectorized persona to database.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database upload error: {str(e)}")
        
    return {"status": "success", "message": f"Successfully created and vectorized persona '{target_name}' with {len(profile_data['pairs'])} pairs."}


