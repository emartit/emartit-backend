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
