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
            history=request.
