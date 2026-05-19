import os
from supabase import create_client, Client

def get_supabase_client() -> Client:
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SECRET_KEY")
    
    if not url or not key:
        raise Exception("Supabase credentials not set")
    
    return create_client(url, key)

def get_client_settings(client_id: str) -> dict:
    supabase = get_supabase_client()
    
    result = supabase.table("client_settings")\
        .select("*")\
        .eq("client_id", client_id)\
        .execute()
    
    if result.data:
        return result.data[0]
    return {}

def get_client(client_id: str) -> dict:
    supabase = get_supabase_client()
    
    result = supabase.table("clients")\
        .select("*")\
        .eq("id", client_id)\
        .eq("is_active", True)\
        .execute()
    
    if result.data:
        return result.data[0]
    return {}

def log_conversation(client_id: str, session_id: str, message: str, role: str):
    supabase = get_supabase_client()
    
    supabase.table("conversations").insert({
        "client_id": client_id,
        "session_id": session_id,
        "message": message,
        "role": role
    }).execute()

def increment_usage(client_id: str):
    from datetime import datetime
    now = datetime.now()
    supabase = get_supabase_client()
    
    existing = supabase.table("usage")\
        .select("*")\
        .eq("client_id", client_id)\
        .eq("month", now.month)\
        .eq("year", now.year)\
        .execute()
    
    if existing.data:
        usage_id = existing.data[0]["id"]
        current_count = existing.data[0]["conversation_count"]
        supabase.table("usage")\
            .update({"conversation_count": current_count + 1})\
            .eq("id", usage_id)\
            .execute()
    else:
        supabase.table("usage").insert({
            "client_id": client_id,
            "month": now.month,
            "year": now.year,
            "conversation_count": 1
        }).execute()
