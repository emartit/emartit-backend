import anthropic
import os
from typing import List

DEFAULT_SYSTEM_PROMPT = """You are a helpful, friendly AI assistant for a business website.
You answer customer questions clearly and professionally.
Keep your answers concise — 2 to 4 sentences when possible.
If you don't know something specific about the business, say:
'I don't have that information right now — please contact us directly and we'll be happy to help.'
Always be warm, polite, and helpful."""

async def handle_chat(client_id: str, message: str, history: list) -> str:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    
    if not api_key:
        raise Exception("ANTHROPIC_API_KEY is not set in environment variables")
    
    client = anthropic.Anthropic(api_key=api_key)
    
    messages = []
    
    for msg in history:
        messages.append({
            "role": msg.role,
            "content": msg.content
        })
    
    messages.append({
        "role": "user",
        "content": message
    })
    
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=500,
        system=DEFAULT_SYSTEM_PROMPT,
        messages=messages
    )
    
    reply = response.content[0].text
    
    return reply
