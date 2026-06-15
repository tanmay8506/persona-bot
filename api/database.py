"""
api/database.py — Supabase stateless REST client interface for FastAPI backend.
"""

import os
import httpx
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL              = os.getenv("SUPABASE_URL", "")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
ACCESS_PASSCODE           = os.getenv("ACCESS_PASSCODE", "")

def get_headers() -> dict:
    if not SUPABASE_SERVICE_ROLE_KEY:
        raise ValueError("SUPABASE_SERVICE_ROLE_KEY not configured in environment variables.")
    return {
        "apikey": SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": "application/json"
    }

def get_supabase_rest_url(table: str) -> str:
    if not SUPABASE_URL:
        raise ValueError("SUPABASE_URL not configured in environment variables.")
    return f"{SUPABASE_URL.rstrip('/')}/rest/v1/{table}"


# Stateless helpers

def get_profile(name: str) -> dict | None:
    """Fetch profile row containing style DNA Card."""
    url = f"{get_supabase_rest_url('profiles')}?name=eq.{name}&select=*"
    try:
        with httpx.Client() as client:
            res = client.get(url, headers=get_headers())
            if res.status_code == 200:
                data = res.json()
                return data[0] if data else None
    except Exception as e:
        print(f"Database error in get_profile: {e}")
    return None


def get_profiles_list() -> list[dict]:
    """Fetch list of all profiles available."""
    url = f"{get_supabase_rest_url('profiles')}?select=name,created_at"
    try:
        with httpx.Client() as client:
            res = client.get(url, headers=get_headers())
            if res.status_code == 200:
                return res.json()
    except Exception as e:
        print(f"Database error in get_profiles_list: {e}")
    return []


def create_conversation(profile_name: str) -> str | None:
    """Create a new conversation session."""
    url = get_supabase_rest_url('conversations')
    headers = get_headers()
    headers["Prefer"] = "return=representation"
    payload = {"profile_name": profile_name}
    try:
        with httpx.Client() as client:
            res = client.post(url, json=payload, headers=headers)
            if res.status_code in (200, 201):
                data = res.json()
                return data[0]["id"] if data else None
    except Exception as e:
        print(f"Database error in create_conversation: {e}")
    return None


def get_conversation_history(convo_id: str, limit: int = 12) -> list[dict]:
    """Retrieve chat history sorted chronologically."""
    url = f"{get_supabase_rest_url('messages')}?conversation_id=eq.{convo_id}&order=created_at.asc&limit={limit}"
    try:
        with httpx.Client() as client:
            res = client.get(url, headers=get_headers())
            if res.status_code == 200:
                return res.json()
    except Exception as e:
        print(f"Database error in get_conversation_history: {e}")
    return []


def save_message(convo_id: str, role: str, content: str) -> bool:
    """Save a chat message in the session."""
    url = get_supabase_rest_url('messages')
    payload = {
        "conversation_id": convo_id,
        "role": role,
        "content": content
    }
    try:
        with httpx.Client() as client:
            res = client.post(url, json=payload, headers=get_headers())
            return res.status_code in (200, 201, 204)
    except Exception as e:
        print(f"Database error in save_message: {e}")
    return False
