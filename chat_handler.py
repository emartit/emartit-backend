import os
from typing import List
import anthropic

DEFAULT_SYSTEM_PROMPT = """You are a helpful, friendly AI assistant for a business website.
You answer customer questions clearly and professionally.
Keep your answers concise — 2 to 4 sentences when possible.
If you don't know something specific about the business, say:
'I don't have that information right now — please contact us directly and we'll be happy to help.'
Always be warm, polite, and helpful."""

def build_system_prompt(settings: dict) -> str:
    if not settings:
        return DEFAULT_SYSTEM_PROMPT
    
    prompt = f"""You are {settings.get('bot_name', 'Assistant')}, an AI assistant for {settings.get('business_description', 'this business')}.

"""
    if settings.get('services'):
        prompt += f"Services offered: {settings['services']}\n"
    if settings.get('working_hours'):
        prompt += f"Working hours: {settings['working_hours']}\n"
    if settings.get('location'):
        prompt += f"Location: {settings['location']}\n"
    if settings.get('phone'):
        prompt += f"Phone: {settings['phone']}\n"
    if settings.get('website'):
        prompt += f"Website: {settings['website']}\n"
    if settings.get('custom_prompt'):
        prompt += f"\n{settings['custom_prompt']}\n"
    
    prompt += "\nAlways be warm, polite, and helpful. Keep answers concise — 2 to 4 sentences when possible."
    return prompt

async def handle_chat(client_id: str, message: str, history: list) -> str:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    
    if not api_key:
        raise Exception("ANTHROPIC_API_KEY is not set")
    
    # Try to get client settings from database
    system_prompt = DEFAULT_SYSTEM_PROMPT
    try:
        from database import get_client_settings, log_conversation, increment_usage
        import uuid
        settings = get_client_settings(client_id)
        if settings:
            system_prompt = build_system_prompt(settings)
        
        # Log the user message
        session_id = str(uuid.uuid4())
        log_conversation(client_id, session_id, message, "user")
    except Exception as e:
        print(f"Database error (non-fatal): {e}")
    
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
        model="claude-sonnet-4-6",
        max_tokens=500,
        system=system_prompt,
        messages=messages
    )
    
    reply = response.content[0].text
    
    # Log the assistant reply and increment usage
    try:
        log_conversation(client_id, session_id, reply, "assistant")
        increment_usage(client_id)
    except Exception as e:
        print(f"Database logging error (non-fatal): {e}")
    
    return reply
