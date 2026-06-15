"""
api/index.py — FastAPI serverless endpoints for Next.js monorepo routing.
"""

import os
from fastapi import FastAPI, Header, HTTPException, Depends
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
    clean_response
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


# ── Passcode Verification Middleware ──────────────────────────────────────────

async def verify_passcode(authorization: str = Header(None)):
    """Verifies access passcode if ACCESS_PASSCODE is set in environments."""
    if not ACCESS_PASSCODE:
        return
        
    # Expect format "Bearer passcode"
    token = ""
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ")[1]
        
    if token != ACCESS_PASSCODE:
        raise HTTPException(
            status_code=401,
            detail="Unauthorized. Invalid access passcode."
        )


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


@app.get("/api/profiles", dependencies=[Depends(verify_passcode)])
def list_profiles():
    """Returns list of available personas in Supabase."""
    profiles = get_profiles_list()
    # If Supabase is empty, check if we have a local persona_profile.json
    # and upload it dynamically if found. This bootstraps first-time local setup.
    if not profiles:
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


@app.post("/api/conversations", dependencies=[Depends(verify_passcode)])
def start_chat(data: ConversationCreate):
    """Creates a persistent chat session in database."""
    convo_id = create_conversation(data.profile_name)
    if not convo_id:
        raise HTTPException(status_code=500, detail="Failed to initialize conversation session.")
    return {"conversation_id": convo_id}


@app.post("/api/chat", dependencies=[Depends(verify_passcode)])
def send_chat_message(data: ChatRequest):
    """
    Main conversational loop.
    Assembles prompt, retrieve matched pairs, calls Groq, saves and returns message.
    """
    convo_id = data.conversation_id
    message = data.message.strip()
    
    if not message:
        raise HTTPException(status_code=400, detail="Message cannot be empty.")
        
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
        profiles = get_profiles_list()
        if profiles:
            profile_name = profiles[0]["name"]
        else:
            profile_name = "Anvesha" # absolute hardcoded default
            
    # 2. Fetch profile card
    profile = get_profile(profile_name)
    if not profile:
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
    
    # 4. Fetch semantic few-shots (biased by language/dead zones)
    few_shots = retrieve_few_shots(profile_name, message, limit=6)
    
    # 5. Assemble Prompt layers
    prompt_msgs = assemble_prompt(message, formatted_history, profile, few_shots, config=data.config.dict() if data.config else None)
    
    # 6. Generate reply with retry logic
    # Tweak Groq variety based on elongation slider (higher elongation -> higher variety/temperature)
    force_variety = False
    if data.config and data.config.elongation_rate > 0.7:
        force_variety = True
    reply = call_groq_with_retry(prompt_msgs, force_variety=force_variety)
    
    # 7. Safeguard 1: AI Bleed-through Filter Retry
    if is_bad_response(reply):
        retry_prompt = prompt_msgs + [{
            "role": "system",
            "content": f"Stay in character as {profile_name}. Do not output AI metadata, disclaimers, or introductory headings. Just text back."
        }]
        reply = call_groq_with_retry(retry_prompt)
        
    # 8. Safeguard 2: Repetition / Streak Blocker Retry
    if is_repeat(reply, formatted_history):
        variety_prompt = prompt_msgs + [{
            "role": "system",
            "content": "Say something different this time. You are repeating the same phrasing as before."
        }]
        reply = call_groq_with_retry(variety_prompt, force_variety=True)
        
    # 9. Clean up final response text
    reply = clean_response(reply)
    
    # 10. Save Assistant reply to Database
    save_message(convo_id, "assistant", reply)
    
    return {"role": "assistant", "content": reply}
