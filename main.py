from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
import os

app = FastAPI(title="eMart IT Chatbot API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class Message(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    client_id: str
    message: str
    conversation_history: Optional[List[Message]] = []

class ChatResponse(BaseModel):
    reply: str
    success: bool

class ClientCreate(BaseModel):
    name: str
    email: str
    business_name: str
    business_type: str

class ClientSettings(BaseModel):
    client_id: str
    business_description: str
    services: str
    working_hours: str
    location: str
    phone: str
    website: Optional[str] = ""
    bot_name: Optional[str] = "Assistant"
    bot_color: Optional[str] = "#1a569a"
    custom_prompt: Optional[str] = ""

@app.get("/")
def root():
    return {"status": "eMart IT Chatbot API is running", "version": "1.0.0"}

@app.get("/health")
def health_check():
    return {"status": "healthy"}

@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    try:
        from chat_handler import handle_chat
        reply = await handle_chat(
            client_id=request.client_id,
            message=request.message,
            history=request.conversation_history
        )
        return ChatResponse(reply=reply, success=True)
    except Exception as e:
        print(f"Error in /chat endpoint: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/clients")
def create_client(client: ClientCreate):
    try:
        from database import get_supabase_client
        supabase = get_supabase_client()
        result = supabase.table("clients").insert({
            "name": client.name,
            "email": client.email,
            "business_name": client.business_name,
            "business_type": client.business_type
        }).execute()
        return {"success": True, "client": result.data[0]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/clients")
def list_clients():
    try:
        from database import get_supabase_client
        supabase = get_supabase_client()
        result = supabase.table("clients").select("*").execute()
        return {"clients": result.data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/clients/settings")
def save_client_settings(settings: ClientSettings):
    try:
        from database import get_supabase_client
        supabase = get_supabase_client()
        existing = supabase.table("client_settings")\
            .select("*")\
            .eq("client_id", settings.client_id)\
            .execute()
        data = {
            "client_id": settings.client_id,
            "business_description": settings.business_description,
            "services": settings.services,
            "working_hours": settings.working_hours,
            "location": settings.location,
            "phone": settings.phone,
            "website": settings.website,
            "bot_name": settings.bot_name,
            "bot_color": settings.bot_color,
            "custom_prompt": settings.custom_prompt
        }
        if existing.data:
            result = supabase.table("client_settings")\
                .update(data)\
                .eq("client_id", settings.client_id)\
                .execute()
        else:
            result = supabase.table("client_settings").insert(data).execute()
        return {"success": True, "settings": result.data[0]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/clients/{client_id}/usage")
def get_usage(client_id: str):
    try:
        from database import get_supabase_client
        supabase = get_supabase_client()
        result = supabase.table("usage")\
            .select("*")\
            .eq("client_id", client_id)\
            .execute()
        return {"usage": result.data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
