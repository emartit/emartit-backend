from fastapi import FastAPI, HTTPException, Request, BackgroundTasks
from datetime import datetime, timezone, timedelta
import httpx
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
import os
import uuid
import hashlib
import secrets as secrets_module
from security import (hash_password, verify_password, needs_upgrade, require_admin,
                      require_client_or_admin, is_admin, mask_contact_fields, mask_text, log_admin_access)

app = FastAPI(title="eMart IT Chatbot API", version="2.7.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================
# LIVE DEMO (website "Try it yourself" section)
# ============================================
from demo import router as demo_router
app.include_router(demo_router)

# ============================================
# KNOWLEDGE (document reading + AI training)
# ============================================
from knowledge import router as knowledge_router
app.include_router(knowledge_router)

# ============================================
# INBOX (leads & queries from chats)
# ============================================
from inbox import router as inbox_router
app.include_router(inbox_router)

@app.on_event("startup")
async def start_inbox_worker():
    import asyncio
    from inbox import worker_loop
    asyncio.create_task(worker_loop())

class Message(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    client_id: str
    message: str
    conversation_history: Optional[List[Message]] = []
    session_id: Optional[str] = None
    preview_token: Optional[str] = None   # sent only by the client dashboard's Chat Preview

class ChatResponse(BaseModel):
    reply: str
    success: bool
    session_id: Optional[str] = None

class ClientCreate(BaseModel):
    name: str
    email: str
    business_name: str
    business_type: str

class ClientSettings(BaseModel):
    client_id: str
    business_description: Optional[str] = None
    services: Optional[str] = None
    working_hours: Optional[str] = None
    location: Optional[str] = None
    phone: Optional[str] = None
    website: Optional[str] = ""
    bot_name: Optional[str] = "Assistant"
    bot_color: Optional[str] = "#1a569a"
    bubble_color: Optional[str] = "#1a569a"
    header_color: Optional[str] = "#1a569a"
    chat_position: Optional[str] = "right"
    bot_avatar: Optional[str] = "robot"
    welcome_message: Optional[str] = "Hi! How can I help you today? 😊"
    custom_prompt: Optional[str] = ""
    bot_avatar_url: Optional[str] = ""
    knowledge_base: Optional[str] = ""
    faq_items: Optional[list] = []
    proactive_enabled: Optional[bool] = False
    proactive_message: Optional[str] = "👋 Hi! Need help? I'm here!"
    proactive_delay: Optional[int] = 8
    notification_email: Optional[str] = ""
    notification_enabled: Optional[bool] = False
    # chat widget extras
    voice_input_enabled: Optional[bool] = None
    voice_language: Optional[str] = None
    read_aloud_enabled: Optional[bool] = None
    idle_reminders_enabled: Optional[bool] = None
    idle_message_1: Optional[str] = None
    idle_message_2: Optional[str] = None

class ClientLogin(BaseModel):
    email: str
    password: str

class ClientRegister(BaseModel):
    client_id: str
    email: str
    password: str

class GHLPayload(BaseModel):
    contact_name: Optional[str] = ""
    business_name: Optional[str] = ""
    business_type: Optional[str] = ""
    email: Optional[str] = ""
    phone: Optional[str] = ""
    location: Optional[str] = ""
    working_hours: Optional[str] = ""
    services: Optional[str] = ""
    client_id: Optional[str] = ""
    dashboard_url: Optional[str] = ""
    login_email: Optional[str] = ""
    login_password: Optional[str] = ""
    created_at: Optional[str] = ""
    account_type: Optional[str] = ""
    trial_end: Optional[str] = ""
    payment_link: Optional[str] = ""
    website: Optional[str] = ""

class TrialCheck(BaseModel):
    email: Optional[str] = ""
    phone: Optional[str] = ""
    website: Optional[str] = ""

class TrialSetup(BaseModel):
    trial_end: str

class PasswordChange(BaseModel):
    client_id: str
    email: str
    new_password: str
    current_password: Optional[str] = ""
    token: Optional[str] = ""

class PasswordResetRequest(BaseModel):
    email: str

class PasswordResetConfirm(BaseModel):
    token: str
    new_password: str

class LeadCapture(BaseModel):
    client_id: str
    visitor_name: Optional[str] = ""
    visitor_email: Optional[str] = ""
    visitor_phone: Optional[str] = ""
    message: Optional[str] = ""
    session_id: Optional[str] = None
    source: Optional[str] = None

class OfflineSettings(BaseModel):
    client_id: str
    lead_capture_enabled: Optional[bool] = False
    lead_capture_name: Optional[bool] = True
    lead_capture_email: Optional[bool] = True
    lead_capture_phone: Optional[bool] = False
    offline_mode_enabled: Optional[bool] = False
    offline_message: Optional[str] = "We are currently closed. Please leave your details and we will get back to you!"
    business_hours: Optional[dict] = None
    quick_replies: Optional[list] = []
    timezone: Optional[str] = "Asia/Dhaka"

class TrialRequest(BaseModel):
    name: Optional[str] = ""
    business_name: Optional[str] = ""
    business_type: Optional[str] = ""
    email: Optional[str] = ""
    phone: Optional[str] = ""
    website: Optional[str] = ""
    location: Optional[str] = ""
    working_hours: Optional[str] = ""
    services: Optional[str] = ""
    description: Optional[str] = ""
    price_range: Optional[str] = ""
    special_instructions: Optional[str] = ""
    request_type: Optional[str] = "trial"
    ghl_contact_id: Optional[str] = ""

class EmailStatus(BaseModel):
    email: str
    status: str

ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "ematity2024")
# Link sent in "trial ending / ended / approved" emails. Set PAYMENT_LINK in Railway to change it.
PAYMENT_LINK = os.environ.get("PAYMENT_LINK", "https://www.emartit.com/subscribe")

@app.get("/")
def root():
    return {"status": "eMart IT Chatbot API is running", "version": "2.7.0"}

@app.get("/health")
def health_check():
    return {"status": "healthy"}

def _auth_rows_by_email(supabase, email: str) -> list:
    """Login rows for this email, ignoring capital letters (Iqbal@Gmail.com == iqbal@gmail.com)."""
    email = (email or "").strip()
    if not email or len(email) > 320:
        return []
    # case-insensitive search; the exact check below removes anything that only looks similar
    rows = supabase.table("client_auth").select("*").ilike("email", email).execute().data or []
    return [r for r in rows if (r.get("email") or "").strip().lower() == email.lower()]

_reset_requests = {}

def _reset_rate_ok(email: str) -> bool:
    """At most 3 reset emails per address per hour."""
    import time as _time
    now = _time.time()
    key = (email or "").strip().lower()
    recent = [t for t in _reset_requests.get(key, []) if now - t < 3600]
    if len(recent) >= 3:
        _reset_requests[key] = recent
        return False
    recent.append(now)
    _reset_requests[key] = recent
    if len(_reset_requests) > 5000:
        _reset_requests.clear()
    return True

def _is_new_conversation(history) -> bool:
    """A chat is new when the visitor hasn't sent any earlier message in it."""
    for msg in history or []:
        role = msg.get("role") if isinstance(msg, dict) else getattr(msg, "role", "")
        if role == "user":
            return False
    return True

@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, background_tasks: BackgroundTasks):
    # A client ID is always a UUID. Anything else (e.g. "demo") is simply not found.
    try:
        uuid.UUID(str(request.client_id))
    except ValueError:
        raise HTTPException(status_code=404, detail="This chatbot is not set up yet.")
    try:
        from database import get_supabase_client
        supabase = get_supabase_client()
        client = supabase.table("clients").select("*").eq("id", request.client_id).execute()
        if not client.data:
            raise HTTPException(status_code=404, detail="Client not found")
        client_data = client.data[0]
        account_type = client_data.get("account_type", "paid")
        is_active = client_data.get("is_active", True)

        is_new = _is_new_conversation(request.conversation_history)
        session_id = (request.session_id or "").strip()[:64] or str(uuid.uuid4())

        # Dashboard test chats (Chat Preview) are not counted in usage or the free trial.
        # Only honoured with the client's own valid login token.
        is_preview = False
        if request.preview_token:
            from knowledge import verify_client_token
            is_preview = verify_client_token(request.preview_token) == str(request.client_id)

        if not is_active:
            return ChatResponse(
                reply="This chatbot is currently inactive. Please contact the business directly.",
                success=False,
                session_id=session_id
            )
        if account_type == "trial":
            trial_end = client_data.get("trial_end")
            trial_limit = client_data.get("trial_conversation_limit", 10)
            trial_used = client_data.get("trial_conversations_used", 0) or 0
            if trial_end:
                trial_end_dt = datetime.fromisoformat(trial_end.replace("Z", "+00:00"))
                if datetime.now(timezone.utc) > trial_end_dt:
                    supabase.table("clients").update({
                        "account_type": "expired",
                        "is_active": False
                    }).eq("id", request.client_id).execute()
                    background_tasks.add_task(notify_ghl_trial_expired, client_data, "expired_by_time")
                    return ChatResponse(
                        reply="Our free trial has ended. Please contact us to continue using this service.",
                        success=False,
                        session_id=session_id
                    )
            # Trial limit counts CONVERSATIONS (chats), not single messages.
            # A chat that has already started is allowed to finish. Test chats are not counted.
            if is_new and not is_preview:
                if trial_used >= trial_limit:
                    supabase.table("clients").update({
                        "account_type": "expired",
                        "is_active": False
                    }).eq("id", request.client_id).execute()
                    background_tasks.add_task(notify_ghl_trial_expired, client_data, "expired_by_usage")
                    return ChatResponse(
                        reply="Our free trial has ended. Please contact us to continue using this service.",
                        success=False,
                        session_id=session_id
                    )
                supabase.table("clients").update({
                    "trial_conversations_used": trial_used + 1
                }).eq("id", request.client_id).execute()
                if trial_used + 1 == trial_limit - 1:
                    background_tasks.add_task(notify_ghl_trial_warning, client_data)
        from chat_handler import handle_chat
        reply = await handle_chat(
            client_id=request.client_id,
            message=request.message,
            history=request.conversation_history,
            session_id=session_id,
            new_conversation=is_new and not is_preview,
            is_preview=is_preview
        )
        return ChatResponse(reply=reply, success=True, session_id=session_id)
    except HTTPException:
        raise
    except Exception as e:
        # Full error goes to the Railway logs only; visitors never see technical details
        print(f"Error in /chat endpoint: {str(e)}")
        raise HTTPException(status_code=500, detail="Sorry, something went wrong. Please try again.")

# ============================================
# ANALYTICS ENDPOINTS
# ============================================

@app.get("/admin/analytics")
def admin_analytics(x_admin_token: str = None):
    expected = "admin_" + ADMIN_PASSWORD
    if not x_admin_token or x_admin_token != expected:
        raise HTTPException(status_code=401, detail="Unauthorized")
    try:
        from database import get_supabase_client
        supabase = get_supabase_client()
        all_convos = supabase.table("conversations").select("client_id,role,created_at").execute()
        convos = [c for c in (all_convos.data or []) if c.get("role") == "user"]
        days_data = []
        for i in range(29, -1, -1):
            day = datetime.now(timezone.utc) - timedelta(days=i)
            day_str = day.strftime("%Y-%m-%d")
            count = sum(1 for c in convos if c.get("created_at", "")[:10] == day_str)
            days_data.append({
                "date": day_str,
                "label": day.strftime("%b %d"),
                "conversations": count
            })
        clients = supabase.table("clients").select("*").execute()
        client_stats = []
        for c in clients.data:
            total = sum(1 for conv in convos if conv.get("client_id") == c["id"])
            client_stats.append({
                "business_name": c.get("business_name", ""),
                "total_conversations": total
            })
        client_stats.sort(key=lambda x: x["total_conversations"], reverse=True)
        hours_data = []
        for h in range(24):
            count = 0
            for c in convos:
                created = c.get("created_at", "")
                if len(created) >= 13:
                    try:
                        if int(created[11:13]) == h:
                            count += 1
                    except:
                        pass
            hours_data.append({"hour": f"{h:02d}:00", "count": count})
        return {"daily": days_data, "per_client": client_stats, "peak_hours": hours_data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/analytics/{client_id}")
def client_analytics(client_id: str):
    try:
        from database import get_supabase_client
        supabase = get_supabase_client()
        days_data = []
        for i in range(29, -1, -1):
            day = datetime.now(timezone.utc) - timedelta(days=i)
            day_str = day.strftime("%Y-%m-%d")
            day_start = day.strftime("%Y-%m-%dT00:00:00+00:00")
            day_end = day.strftime("%Y-%m-%dT23:59:59+00:00")
            count = supabase.table("conversations").select("id", count="exact").eq("client_id", client_id).eq("role", "user").gte("created_at", day_start).lte("created_at", day_end).execute()
            days_data.append({
                "date": day_str,
                "label": day.strftime("%b %d"),
                "conversations": count.count or 0
            })
        total = supabase.table("conversations").select("id", count="exact").eq("client_id", client_id).eq("role", "user").execute()
        now = datetime.now(timezone.utc)
        month_start = now.strftime("%Y-%m-01T00:00:00+00:00")
        month_total = supabase.table("conversations").select("id", count="exact").eq("client_id", client_id).eq("role", "user").gte("created_at", month_start).execute()
        return {
            "daily": days_data,
            "total_all_time": total.count or 0,
            "total_this_month": month_total.count or 0
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

async def notify_ghl_trial_expired(client_data: dict, reason: str):
    try:
        async with httpx.AsyncClient() as client:
            await client.post(
                "https://services.leadconnectorhq.com/hooks/gc3cLEwwg5coVvb6yiOD/webhook-trigger/b204372c-081f-4341-b1a8-710c6320375b",
                json={
                    "event": "trial_expired",
                    "reason": reason,
                    "business_name": client_data.get("business_name", ""),
                    "email": client_data.get("email", ""),
                    "client_id": client_data.get("id", ""),
                    "payment_link": PAYMENT_LINK,
                    "dashboard_url": "https://emartit.github.io/emartit-dashboard"
                },
                timeout=10.0
            )
    except Exception as e:
        print(f"GHL notification error: {str(e)}")

async def notify_ghl_trial_warning(client_data: dict):
    try:
        async with httpx.AsyncClient() as client:
            await client.post(
                "https://services.leadconnectorhq.com/hooks/gc3cLEwwg5coVvb6yiOD/webhook-trigger/b204372c-081f-4341-b1a8-710c6320375b",
                json={
                    "event": "trial_almost_used",
                    "business_name": client_data.get("business_name", ""),
                    "email": client_data.get("email", ""),
                    "client_id": client_data.get("id", ""),
                    "payment_link": PAYMENT_LINK,
                    "message": "Only 1 free conversation remaining!"
                },
                timeout=10.0
            )
    except Exception as e:
        print(f"GHL warning notification error: {str(e)}")

@app.post("/clients")
def create_client(client: ClientCreate, x_admin_token: str = None):
    require_admin(x_admin_token)
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
        print(f"Create client error: {e}")
        raise HTTPException(status_code=500, detail="Could not create the client.")

@app.get("/clients")
def list_clients(x_admin_token: str = None):
    require_admin(x_admin_token)
    from database import get_supabase_client
    result = get_supabase_client().table("clients").select("*").execute()
    return {"clients": result.data}

@app.post("/clients/settings")
def save_client_settings(settings: ClientSettings, token: str = None, x_admin_token: str = None):
    require_client_or_admin(settings.client_id, token, x_admin_token)
    try:
        from database import get_supabase_client
        supabase = get_supabase_client()
        existing = supabase.table("client_settings").select("client_id").eq("client_id", settings.client_id).execute()
        # Only the fields the page actually sent are saved. Fields it didn't send
        # (knowledge base, FAQs, logo, colours…) are left exactly as they were.
        data = settings.model_dump(exclude_unset=True)
        data["client_id"] = settings.client_id
        if existing.data:
            result = supabase.table("client_settings").update(data).eq("client_id", settings.client_id).execute()
        else:
            result = supabase.table("client_settings").insert(data).execute()
        return {"success": True}
    except Exception as e:
        print(f"Save settings error: {e}")
        raise HTTPException(status_code=500, detail="Could not save the settings.")

@app.get("/clients/{client_id}/usage")
def get_usage(client_id: str):
    try:
        from database import get_supabase_client
        supabase = get_supabase_client()
        result = supabase.table("usage").select("*").eq("client_id", client_id).execute()
        return {"usage": result.data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

PUBLIC_SETTING_KEYS = (
    "bot_name", "welcome_message", "bot_color", "bubble_color", "header_color", "chat_position",
    "bot_avatar", "bot_avatar_url", "lead_capture_enabled", "lead_capture_name", "lead_capture_email",
    "lead_capture_phone", "offline_mode_enabled", "offline_message", "business_hours", "timezone",
    "quick_replies", "proactive_enabled", "proactive_message", "proactive_delay",
    "voice_input_enabled", "voice_language", "read_aloud_enabled",
    "idle_reminders_enabled", "idle_message_1", "idle_message_2",
)

@app.get("/clients/{client_id}/settings")
def get_client_settings(client_id: str, token: str = None, x_admin_token: str = None):
    try:
        uuid.UUID(str(client_id))
    except ValueError:
        return {"settings": {}, "client": {}}
    from database import get_supabase_client
    supabase = get_supabase_client()
    result = supabase.table("client_settings").select("*").eq("client_id", client_id).execute()
    settings = result.data[0] if result.data else {}
    full_access = False
    if token or x_admin_token:
        require_client_or_admin(client_id, token, x_admin_token)
        full_access = True
    if not full_access:
        # Public (website widget): only what the chat window needs to look and behave right
        return {"settings": {k: settings.get(k) for k in PUBLIC_SETTING_KEYS if k in settings}, "client": {}}
    client = supabase.table("clients").select("*").eq("id", client_id).execute()
    return {"settings": settings, "client": client.data[0] if client.data else {}}

@app.get("/clients/{client_id}/trial-status")
def get_trial_status(client_id: str):
    try:
        from database import get_supabase_client
        supabase = get_supabase_client()
        client = supabase.table("clients").select("*").eq("id", client_id).execute()
        if not client.data:
            raise HTTPException(status_code=404, detail="Client not found")
        c = client.data[0]
        account_type = c.get("account_type", "paid")
        trial_end = c.get("trial_end")
        trial_limit = c.get("trial_conversation_limit", 10)
        trial_used = c.get("trial_conversations_used", 0)
        days_remaining = None
        hours_remaining = None
        if trial_end and account_type == "trial":
            trial_end_dt = datetime.fromisoformat(trial_end.replace("Z", "+00:00"))
            remaining = trial_end_dt - datetime.now(timezone.utc)
            if remaining.total_seconds() > 0:
                days_remaining = remaining.days
                hours_remaining = int(remaining.total_seconds() // 3600)
            else:
                days_remaining = 0
                hours_remaining = 0
        return {
            "account_type": account_type,
            "trial_end": trial_end,
            "days_remaining": days_remaining,
            "hours_remaining": hours_remaining,
            "conversations_used": trial_used,
            "conversations_limit": trial_limit,
            "conversations_remaining": max(0, trial_limit - trial_used)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/report")
def get_monthly_report(x_admin_token: str = None):
    require_admin(x_admin_token)
    try:
        from database import get_monthly_report
        report = get_monthly_report()
        total_profit = sum(r["your_profit_usd"] for r in report)
        total_revenue = sum(r["charge_to_client_usd"] for r in report)
        total_api_cost = sum(r["api_cost_usd"] for r in report)
        return {
            "month_summary": {
                "total_clients": len(report),
                "total_revenue_usd": round(total_revenue, 2),
                "total_api_cost_usd": round(total_api_cost, 4),
                "total_profit_usd": round(total_profit, 2)
            },
            "clients": report
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.patch("/clients/{client_id}/status")
def toggle_client_status(client_id: str, is_active: bool, x_admin_token: str = None):
    require_admin(x_admin_token)
    try:
        from database import get_supabase_client
        supabase = get_supabase_client()
        result = supabase.table("clients").update({"is_active": is_active}).eq("id", client_id).execute()
        return {"success": True, "client": result.data[0]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/auth/register")
def register_client(data: ClientRegister, x_admin_token: str = None):
    require_admin(x_admin_token)
    try:
        from database import get_supabase_client
        supabase = get_supabase_client()
        supabase.table("client_auth").insert({
            "client_id": data.client_id,
            "email": data.email,
            "password_hash": hash_password(data.password)
        }).execute()
        return {"success": True, "message": "Account created successfully"}
    except Exception as e:
        print(f"Register error: {e}")
        raise HTTPException(status_code=500, detail="Could not create the login.")

@app.post("/auth/login")
def login_client(data: ClientLogin):
    try:
        from database import get_supabase_client
        from knowledge import make_client_token
        supabase = get_supabase_client()
        rows = _auth_rows_by_email(supabase, data.email)
        auth = next((r for r in rows if verify_password(data.password, r.get("password_hash"))), None)
        if not auth:
            raise HTTPException(status_code=401, detail="Invalid email or password")
        # old-style password: upgrade it to the safe format now that we know it
        if needs_upgrade(auth.get("password_hash")):
            try:
                supabase.table("client_auth").update({"password_hash": hash_password(data.password)}).eq("client_id", auth["client_id"]).eq("email", auth["email"]).execute()
            except Exception as e:
                print(f"Password upgrade skipped: {e}")
        client = supabase.table("clients").select("*").eq("id", auth["client_id"]).execute()
        if not client.data or not client.data[0]["is_active"]:
            raise HTTPException(status_code=403, detail="Account is inactive")
        return {
            "success": True,
            "client_id": auth["client_id"],
            "client": client.data[0],
            "token": make_client_token(str(auth["client_id"]))
        }
    except HTTPException:
        raise
    except Exception as e:
        print(f"Login error: {e}")
        raise HTTPException(status_code=500, detail="Login failed. Please try again.")

# ============================================
# PHASE 6 — ADMIN PANEL ENDPOINTS
# ============================================

@app.post("/admin/login")
async def admin_login(request: Request):
    data = await request.json()
    password = data.get("password", "")
    if password != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="Invalid admin password")
    return {"success": True, "token": "admin_" + ADMIN_PASSWORD}

@app.get("/admin/clients")
def admin_get_all_clients(x_admin_token: str = None):
    from database import get_supabase_client
    expected = "admin_" + ADMIN_PASSWORD
    if not x_admin_token or x_admin_token != expected:
        raise HTTPException(status_code=401, detail="Unauthorized")
    try:
        supabase = get_supabase_client()
        clients = supabase.table("clients").select("*").execute()
        result = []
        for client in clients.data:
            cid = client["id"]
            usage = supabase.table("usage").select("conversation_count").eq("client_id", cid).execute()
            count = sum(u.get("conversation_count", 0) for u in usage.data) if usage.data else 0
            api_cost = round(count * 0.02, 2)
            charge = round(count * 0.07, 2)
            profit = round(charge - api_cost, 2)
            result.append({
                "id": cid,
                "business_name": client.get("business_name", ""),
                "email": client.get("email", ""),
                "status": "active" if client.get("is_active", True) else "inactive",
                "account_type": client.get("account_type", "paid"),
                "trial_end": client.get("trial_end", None),
                "trial_conversation_limit": client.get("trial_conversation_limit", 10),
                "trial_conversations_used": client.get("trial_conversations_used", 0),
                "conversations_this_month": count,
                "api_cost": api_cost,
                "charge_to_client": charge,
                "your_profit": profit
            })
        return {"clients": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/admin/billing")
def admin_billing_summary(x_admin_token: str = None):
    expected = "admin_" + ADMIN_PASSWORD
    if not x_admin_token or x_admin_token != expected:
        raise HTTPException(status_code=401, detail="Unauthorized")
    try:
        from database import get_supabase_client
        supabase = get_supabase_client()
        month = datetime.now().strftime("%Y-%m")
        clients = supabase.table("clients").select("*").execute()
        total_convos = 0
        total_api_cost = 0
        total_revenue = 0
        rows = []
        for client in clients.data:
            cid = client["id"]
            usage = supabase.table("usage").select("conversation_count").eq("client_id", cid).execute()
            count = sum(u.get("conversation_count", 0) for u in usage.data) if usage.data else 0
            api_cost = round(count * 0.02, 2)
            charge = round(count * 0.07, 2)
            profit = round(charge - api_cost, 2)
            total_convos += count
            total_api_cost += api_cost
            total_revenue += charge
            rows.append({
                "business_name": client.get("business_name", ""),
                "conversations": count,
                "api_cost": api_cost,
                "charge": charge,
                "profit": profit
            })
        return {
            "month": month,
            "rows": rows,
            "totals": {
                "conversations": total_convos,
                "api_cost": round(total_api_cost, 2),
                "revenue": round(total_revenue, 2),
                "profit": round(total_revenue - total_api_cost, 2)
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/admin/clients/{client_id}/toggle")
def admin_toggle_client(client_id: str, x_admin_token: str = None):
    expected = "admin_" + ADMIN_PASSWORD
    if not x_admin_token or x_admin_token != expected:
        raise HTTPException(status_code=401, detail="Unauthorized")
    try:
        from database import get_supabase_client
        supabase = get_supabase_client()
        client = supabase.table("clients").select("is_active").eq("id", client_id).execute()
        if not client.data:
            raise HTTPException(status_code=404, detail="Client not found")
        current = client.data[0].get("is_active", True)
        new_status = not current
        supabase.table("clients").update({"is_active": new_status}).eq("id", client_id).execute()
        return {"success": True, "new_status": "active" if new_status else "inactive"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/admin/clients/{client_id}/conversations")
def admin_view_conversations(client_id: str, x_admin_token: str = None):
    expected = "admin_" + ADMIN_PASSWORD
    if not x_admin_token or x_admin_token != expected:
        raise HTTPException(status_code=401, detail="Unauthorized")
    try:
        from database import get_supabase_client
        supabase = get_supabase_client()
        convos = supabase.table("conversations").select("*").eq("client_id", client_id).order("created_at", desc=True).limit(50).execute()
        rows = []
        for c in convos.data or []:
            c = dict(c)
            if c.get("role") == "user":
                c["message"] = mask_text(c.get("message") or "")
            rows.append(c)
        return {"conversations": rows}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/admin/billing/export")
def admin_export_csv(x_admin_token: str = None):
    expected = "admin_" + ADMIN_PASSWORD
    if not x_admin_token or x_admin_token != expected:
        raise HTTPException(status_code=401, detail="Unauthorized")
    try:
        from database import get_supabase_client
        from fastapi.responses import StreamingResponse
        import csv, io
        supabase = get_supabase_client()
        month = datetime.now().strftime("%Y-%m")
        clients = supabase.table("clients").select("*").execute()
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Business Name", "Email", "Conversations", "API Cost ($)", "Charge to Client ($)", "Your Profit ($)"])
        for client in clients.data:
            cid = client["id"]
            usage = supabase.table("usage").select("conversation_count").eq("client_id", cid).execute()
            count = sum(u.get("conversation_count", 0) for u in usage.data) if usage.data else 0
            api_cost = round(count * 0.02, 2)
            charge = round(count * 0.07, 2)
            profit = round(charge - api_cost, 2)
            writer.writerow([client.get("business_name",""), client.get("email",""), count, api_cost, charge, profit])
        output.seek(0)
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=billing_{month}.csv"}
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/admin/notify-ghl")
async def notify_ghl(payload: GHLPayload, x_admin_token: str = None):
    require_admin(x_admin_token)
    data = payload.dict()
    try:
        async with httpx.AsyncClient() as client:
            await client.post(
                "https://services.leadconnectorhq.com/hooks/gc3cLEwwg5coVvb6yiOD/webhook-trigger/b204372c-081f-4341-b1a8-710c6320375b",
                json=data,
                timeout=10.0
            )
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.delete("/admin/clients/{client_id}")
def admin_delete_client(client_id: str, x_admin_token: str = None):
    expected = "admin_" + ADMIN_PASSWORD
    if not x_admin_token or x_admin_token != expected:
        raise HTTPException(status_code=401, detail="Unauthorized")
    try:
        from database import get_supabase_client
        supabase = get_supabase_client()
        supabase.table("client_knowledge").delete().eq("client_id", client_id).execute()
        supabase.table("queries").delete().eq("client_id", client_id).execute()
        supabase.table("leads").delete().eq("client_id", client_id).execute()
        supabase.table("chat_sessions").delete().eq("client_id", client_id).execute()
        supabase.table("client_settings").delete().eq("client_id", client_id).execute()
        supabase.table("client_auth").delete().eq("client_id", client_id).execute()
        supabase.table("usage").delete().eq("client_id", client_id).execute()
        supabase.table("conversations").delete().eq("client_id", client_id).execute()
        supabase.table("clients").delete().eq("id", client_id).execute()
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/admin/check-duplicate-trial")
def check_duplicate_trial(data: TrialCheck, x_admin_token: str = None):
    expected = "admin_" + ADMIN_PASSWORD
    if not x_admin_token or x_admin_token != expected:
        raise HTTPException(status_code=401, detail="Unauthorized")
    try:
        from database import get_supabase_client
        supabase = get_supabase_client()
        matches = []
        if data.email:
            r = supabase.table("clients").select("*").eq("email", data.email).execute()
            for c in r.data:
                if c.get("account_type") in ["trial", "expired"]:
                    matches.append({"field": "email", "business": c.get("business_name"), "type": c.get("account_type")})
        if data.website:
            r = supabase.table("client_settings").select("*").eq("website", data.website).execute()
            for s in r.data:
                client = supabase.table("clients").select("*").eq("id", s.get("client_id")).execute()
                if client.data and client.data[0].get("account_type") in ["trial", "expired"]:
                    matches.append({"field": "website", "business": client.data[0].get("business_name"), "type": client.data[0].get("account_type")})
        if data.phone:
            r = supabase.table("client_settings").select("*").eq("phone", data.phone).execute()
            for s in r.data:
                client = supabase.table("clients").select("*").eq("id", s.get("client_id")).execute()
                if client.data and client.data[0].get("account_type") in ["trial", "expired"]:
                    matches.append({"field": "phone", "business": client.data[0].get("business_name"), "type": client.data[0].get("account_type")})
        return {"duplicate_found": len(matches) > 0, "matches": matches}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/admin/convert-to-paid/{client_id}")
def convert_to_paid(client_id: str, x_admin_token: str = None):
    expected = "admin_" + ADMIN_PASSWORD
    if not x_admin_token or x_admin_token != expected:
        raise HTTPException(status_code=401, detail="Unauthorized")
    try:
        from database import get_supabase_client
        supabase = get_supabase_client()
        supabase.table("clients").update({
            "account_type": "paid",
            "is_active": True,
            "trial_start": None,
            "trial_end": None
        }).eq("id", client_id).execute()
        return {"success": True, "message": "Client converted to paid successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/admin/set-trial/{client_id}")
def set_trial(client_id: str, data: TrialSetup, x_admin_token: str = None):
    expected = "admin_" + ADMIN_PASSWORD
    if not x_admin_token or x_admin_token != expected:
        raise HTTPException(status_code=401, detail="Unauthorized")
    try:
        from database import get_supabase_client
        supabase = get_supabase_client()
        supabase.table("clients").update({
            "account_type": "trial",
            "trial_start": datetime.now(timezone.utc).isoformat(),
            "trial_end": data.trial_end,
            "trial_conversation_limit": 10,
            "trial_conversations_used": 0
        }).eq("id", client_id).execute()
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/auth/change-password")
def change_password(data: PasswordChange):
    # Must be logged in as this client AND know the current password
    require_client_or_admin(data.client_id, data.token, None)
    if len(data.new_password or "") < 8:
        raise HTTPException(status_code=400, detail="New password must be at least 8 characters.")
    from database import get_supabase_client
    supabase = get_supabase_client()
    rows = supabase.table("client_auth").select("*").eq("client_id", data.client_id).eq("email", data.email).execute().data or []
    if not rows or not verify_password(data.current_password or "", rows[0].get("password_hash")):
        raise HTTPException(status_code=401, detail="Current password is incorrect.")
    supabase.table("client_auth").update({
        "password_hash": hash_password(data.new_password)
    }).eq("client_id", data.client_id).eq("email", data.email).execute()
    return {"success": True}

# ============================================
# LEADS & OFFLINE MODE
# ============================================

@app.post("/leads/capture")
async def capture_lead(data: LeadCapture):
    try:
        from database import get_supabase_client
        supabase = get_supabase_client()
        session_id = (data.session_id or "").strip()[:64] or None
        source = data.source if data.source in ("form", "offline_form", "chat") else "form"
        row = {
            "client_id": data.client_id,
            "visitor_name": (data.visitor_name or "")[:200],
            "visitor_email": (data.visitor_email or "")[:320],
            "visitor_phone": (data.visitor_phone or "")[:50],
            "message": (data.message or "")[:2000],
            "source": source,
            "status": "new",
        }
        existing = None
        if session_id:
            row["session_id"] = session_id
            existing = supabase.table("leads").select("id").eq("session_id", session_id).execute()
        if existing and existing.data:
            result = supabase.table("leads").update(row).eq("id", existing.data[0]["id"]).execute()
        else:
            result = supabase.table("leads").insert(row).execute()
        if session_id:
            try:
                from inbox import mark_form_lead_session
                mark_form_lead_session(data.client_id, session_id)
            except Exception as e:
                print(f"Lead session mark error (non-fatal): {e}")
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/admin/leads/{client_id}")
def admin_get_leads(client_id: str, x_admin_token: str = None):
    expected = "admin_" + ADMIN_PASSWORD
    if not x_admin_token or x_admin_token != expected:
        raise HTTPException(status_code=401, detail="Unauthorized")
    try:
        from database import get_supabase_client
        supabase = get_supabase_client()
        result = supabase.table("leads").select("*").eq("client_id", client_id).order("created_at", desc=True).execute()
        return {"leads": [mask_contact_fields(r) for r in (result.data or [])]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/clients/offline-settings")
def save_offline_settings(data: OfflineSettings, token: str = None, x_admin_token: str = None):
    require_client_or_admin(data.client_id, token, x_admin_token)
    try:
        from database import get_supabase_client
        supabase = get_supabase_client()
        update_data = {
            "lead_capture_enabled": data.lead_capture_enabled,
            "lead_capture_name": data.lead_capture_name,
            "lead_capture_email": data.lead_capture_email,
            "lead_capture_phone": data.lead_capture_phone,
            "offline_mode_enabled": data.offline_mode_enabled,
            "offline_message": data.offline_message,
            "quick_replies": data.quick_replies,
            "timezone": data.timezone
        }
        if data.business_hours:
            update_data["business_hours"] = data.business_hours
        existing = supabase.table("client_settings").select("*").eq("client_id", data.client_id).execute()
        if existing.data:
            supabase.table("client_settings").update(update_data).eq("client_id", data.client_id).execute()
        else:
            update_data["client_id"] = data.client_id
            supabase.table("client_settings").insert(update_data).execute()
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/clients/upload-avatar")
async def upload_avatar(client_id: str, request: Request, token: str = None, x_admin_token: str = None):
    require_client_or_admin(client_id, token, x_admin_token)
    try:
        from database import get_supabase_client
        import base64
        supabase = get_supabase_client()
        data = await request.json()
        image_data = data.get("image_data", "")
        import re as _re
        file_name = _re.sub(r"[^A-Za-z0-9._-]", "_", os.path.basename(str(data.get("file_name", "avatar.png"))))[-80:] or "avatar.png"
        content_type = data.get("content_type", "image/png")
        if not image_data:
            raise HTTPException(status_code=400, detail="No image data provided")
        image_bytes = base64.b64decode(image_data.split(",")[-1])
        file_path = f"{client_id}/{file_name}"
        supabase.storage.from_("avatars").upload(
            file_path,
            image_bytes,
            {"content-type": content_type, "upsert": "true"}
        )
        public_url = supabase.storage.from_("avatars").get_public_url(file_path)
        supabase.table("client_settings").update({
            "bot_avatar_url": public_url
        }).eq("client_id", client_id).execute()
        return {"success": True, "url": public_url}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ============================================
# TRIAL REQUESTS ENDPOINTS
# ============================================

def _clip(value, limit: int = 5000) -> str:
    return str(value or "").strip()[:limit]

@app.post("/requests/incoming")
async def incoming_request(request: Request, background_tasks: BackgroundTasks):
    try:
        from database import get_supabase_client
        from knowledge import save_entry, rebuild_request_sheet, MAX_DOC_CHARS
        supabase = get_supabase_client()
        data = await request.json()

        document_text = _clip(data.get("document_text"), MAX_DOC_CHARS)
        document_name = _clip(data.get("document_name"), 200)
        services = _clip(data.get("services"))
        description = _clip(data.get("description"))
        email = _clip(data.get("email"), 320)

        result = supabase.table("trial_requests").insert({
            "name": _clip(data.get("name"), 200),
            "business_name": _clip(data.get("business_name"), 200),
            "business_type": _clip(data.get("business_type"), 200),
            "email": email,
            "phone": _clip(data.get("phone"), 50),
            "website": _clip(data.get("website"), 500),
            "location": _clip(data.get("location"), 300),
            "working_hours": _clip(data.get("working_hours"), 500),
            "services": services,
            "description": description,
            "price_range": _clip(data.get("price_range"), 500),
            "special_instructions": _clip(data.get("special_instructions"), 3000),
            "request_type": data.get("request_type", "trial") if data.get("request_type") in ("trial", "paid") else "trial",
            "ghl_contact_id": _clip(data.get("contact_id"), 200),
            "document_url": "",
            "status": "pending"
        }).execute()
        request_id = result.data[0]["id"] if result.data else None

        # Save the business knowledge from the form (text only — no files stored)
        has_knowledge = False
        if request_id:
            try:
                if document_text:
                    save_entry(document_text, "upload", title=document_name or "Uploaded document",
                               file_name=document_name, request_id=request_id, email=email)
                    has_knowledge = True
                if services or description:
                    typed = ""
                    if description:
                        typed += f"About the business:\n{description}\n\n"
                    if services:
                        typed += f"Services and prices:\n{services}\n"
                    price_range = _clip(data.get("price_range"), 500)
                    if price_range:
                        typed += f"\nPrice range: {price_range}\n"
                    save_entry(typed, "form", title="Typed on the request form",
                               request_id=request_id, email=email)
                    has_knowledge = True
                if has_knowledge:
                    background_tasks.add_task(rebuild_request_sheet, request_id)
            except Exception as e:
                print(f"Knowledge save error (non-fatal): {e}")

        # Forward to GHL without the long document text
        ghl_data = {k: v for k, v in data.items() if k != "document_text"}
        ghl_data["has_document"] = "yes" if document_text else "no"
        try:
            async with httpx.AsyncClient() as client:
                await client.post(
                    "https://services.leadconnectorhq.com/hooks/gc3cLEwwg5coVvb6yiOD/webhook-trigger/a1e70441-b76b-4a2a-b91f-d1b1ac4db821",
                    json=ghl_data,
                    timeout=10.0
                )
        except Exception as e:
            print(f"GHL forward error: {str(e)}")
        return {"success": True, "message": "Request received"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/requests/email-status")
def set_email_status(data: EmailStatus, key: str = ""):
    """Called by the GHL request-form workflow after its Verify Email step."""
    secret = os.environ.get("GHL_WEBHOOK_SECRET", "")
    if not secret or key != secret:
        raise HTTPException(status_code=401, detail="Unauthorized")
    email = (data.email or "").strip().lower()
    if not email:
        raise HTTPException(status_code=400, detail="Email is required")
    status = (data.status or "").strip().lower()
    if status not in ("valid", "invalid", "risky"):
        status = "unknown"
    try:
        from database import get_supabase_client
        supabase = get_supabase_client()
        supabase.table("email_verifications").upsert({
            "email": email,
            "status": status,
            "checked_at": datetime.now(timezone.utc).isoformat()
        }).execute()
        return {"success": True, "email": email, "status": status}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/admin/requests")
def get_all_requests(x_admin_token: str = None):
    expected = "admin_" + ADMIN_PASSWORD
    if not x_admin_token or x_admin_token != expected:
        raise HTTPException(status_code=401, detail="Unauthorized")
    try:
        from database import get_supabase_client
        supabase = get_supabase_client()
        result = supabase.table("trial_requests").select("*").order("created_at", desc=True).execute()
        return {"requests": result.data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

def _attach_knowledge(request_id: str, client_id: str, background_tasks: BackgroundTasks):
    """Move the request's documents/notes to the client and update the bot's knowledge."""
    try:
        from knowledge import attach_request_knowledge, rebuild_client_sheet
        if attach_request_knowledge(request_id, client_id):
            background_tasks.add_task(rebuild_client_sheet, client_id)
    except Exception as e:
        print(f"Knowledge attach error (non-fatal): {e}")

@app.post("/admin/requests/{request_id}/approve")
async def approve_request(request_id: str, background_tasks: BackgroundTasks, x_admin_token: str = None):
    expected = "admin_" + ADMIN_PASSWORD
    if not x_admin_token or x_admin_token != expected:
        raise HTTPException(status_code=401, detail="Unauthorized")
    try:
        from database import get_supabase_client
        import secrets
        supabase = get_supabase_client()
        req = supabase.table("trial_requests").select("*").eq("id", request_id).execute()
        if not req.data:
            raise HTTPException(status_code=404, detail="Request not found")
        r = req.data[0]
        request_email = (r.get("email") or "").strip().lower()
        try:
            from demo import validate_email
            email_check = validate_email(request_email)
        except Exception as e:
            print(f"Email check skipped: {e}")
            email_check = {"ok": True}
        if not email_check.get("ok"):
            raise HTTPException(status_code=400, detail=f"⚠️ This request's email failed our email check ({email_check.get('message', 'invalid email')}). Please REJECT this request.")
        verification = supabase.table("email_verifications").select("status").eq("email", request_email).execute()
        if verification.data and verification.data[0].get("status") == "invalid":
            raise HTTPException(status_code=400, detail="⚠️ GoHighLevel marked this email as INVALID. Please REJECT this request.")
        password = secrets.token_urlsafe(8)
        existing_client = supabase.table("clients").select("*").eq("email", r["email"]).execute()
        if existing_client.data:
            existing = existing_client.data[0]
            existing_type = existing.get("account_type", "paid")
            if existing_type == "paid":
                raise HTTPException(status_code=400, detail="This email already has an active PAID account.")
            if existing_type in ["trial", "expired"] and r["request_type"] == "trial":
                raise HTTPException(status_code=400, detail="⚠️ This client already used their free trial. You can only CONVERT TO PAID — click Approve as Paid instead.")
            if existing_type in ["trial", "expired"] and r["request_type"] == "paid":
                supabase.table("clients").update({
                    "account_type": "paid",
                    "is_active": True,
                    "trial_start": None,
                    "trial_end": None,
                    "trial_conversations_used": 0
                }).eq("id", existing["id"]).execute()
                supabase.table("trial_requests").update({"status": "approved"}).eq("id", request_id).execute()
                _attach_knowledge(request_id, existing["id"], background_tasks)
                try:
                    async with httpx.AsyncClient() as client:
                        await client.post(
                            "https://services.leadconnectorhq.com/hooks/gc3cLEwwg5coVvb6yiOD/webhook-trigger/b204372c-081f-4341-b1a8-710c6320375b",
                            json={
                                "event": "request_approved",
                                "account_type": "paid",
                                "business_name": existing.get("business_name", ""),
                                "email": existing.get("email", ""),
                                "client_id": existing["id"],
                                "login_email": existing.get("email", ""),
                                "login_password": "Use your existing password",
                                "dashboard_url": "https://emartit.github.io/emartit-dashboard",
                                "payment_link": PAYMENT_LINK
                            },
                            timeout=10.0
                        )
                except Exception as e:
                    print(f"GHL error: {str(e)}")
                return {
                    "success": True,
                    "client_id": existing["id"],
                    "password": "Use existing password",
                    "message": "✅ Trial client successfully converted to PAID!"
                }
        client_result = supabase.table("clients").insert({
            "name": r["name"],
            "email": r["email"],
            "business_name": r["business_name"],
            "business_type": r["business_type"]
        }).execute()
        client_id = client_result.data[0]["id"]
        if r["request_type"] == "trial":
            trial_end = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
            supabase.table("clients").update({
                "account_type": "trial",
                "trial_start": datetime.now(timezone.utc).isoformat(),
                "trial_end": trial_end,
                "trial_conversation_limit": 10,
                "trial_conversations_used": 0
            }).eq("id", client_id).execute()
        else:
            supabase.table("clients").update({
                "account_type": "paid",
                "is_active": True
            }).eq("id", client_id).execute()
        password_hash = hash_password(password)
        supabase.table("client_auth").insert({
            "client_id": client_id,
            "email": r["email"],
            "password_hash": password_hash
        }).execute()
        supabase.table("client_settings").insert({
            "client_id": client_id,
            "business_description": r["description"] or r["business_name"],
            "services": r["services"] or "",
            "working_hours": r["working_hours"] or "",
            "location": r["location"] or "",
            "phone": r["phone"] or "",
            "website": r["website"] or "",
            "bot_name": "Assistant",
            "bot_color": "#1a569a",
            "custom_prompt": r["special_instructions"] or ""
        }).execute()
        supabase.table("trial_requests").update({"status": "approved"}).eq("id", request_id).execute()
        _attach_knowledge(request_id, client_id, background_tasks)
        try:
            async with httpx.AsyncClient() as client:
                await client.post(
                    "https://services.leadconnectorhq.com/hooks/gc3cLEwwg5coVvb6yiOD/webhook-trigger/b204372c-081f-4341-b1a8-710c6320375b",
                    json={
                        "event": "request_approved",
                        "account_type": r["request_type"],
                        "business_name": r["business_name"],
                        "email": r["email"],
                        "client_id": client_id,
                        "login_email": r["email"],
                        "login_password": password,
                        "dashboard_url": "https://emartit.github.io/emartit-dashboard",
                        "payment_link": PAYMENT_LINK
                    },
                    timeout=10.0
                )
        except Exception as e:
            print(f"GHL notification error: {str(e)}")
        return {
            "success": True,
            "client_id": client_id,
            "password": password,
            "message": "Account created successfully"
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/admin/requests/{request_id}/reject")
def reject_request(request_id: str, x_admin_token: str = None):
    expected = "admin_" + ADMIN_PASSWORD
    if not x_admin_token or x_admin_token != expected:
        raise HTTPException(status_code=401, detail="Unauthorized")
    try:
        from database import get_supabase_client
        supabase = get_supabase_client()
        supabase.table("trial_requests").update({"status": "rejected"}).eq("id", request_id).execute()
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/admin/requests/{request_id}/set-type")
def set_request_type(request_id: str, request_type: str, x_admin_token: str = None):
    expected = "admin_" + ADMIN_PASSWORD
    if not x_admin_token or x_admin_token != expected:
        raise HTTPException(status_code=401, detail="Unauthorized")
    try:
        from database import get_supabase_client
        supabase = get_supabase_client()
        supabase.table("trial_requests").update({"request_type": request_type}).eq("id", request_id).execute()
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ============================================
# PASSWORD RESET ENDPOINTS
# ============================================

@app.post("/auth/forgot-password")
async def forgot_password(data: PasswordResetRequest):
    try:
        from database import get_supabase_client
        supabase = get_supabase_client()
        generic = {"success": True, "message": "If this email is registered, we've sent a reset link to it."}
        rows = _auth_rows_by_email(supabase, data.email)
        # Unknown email: send nothing, but answer the same way (never reveal which emails are registered)
        if not rows or not _reset_rate_ok(data.email):
            return generic
        registered_email = rows[0]["email"]   # the link only ever goes to the registered address
        token = secrets_module.token_urlsafe(32)
        expires_at = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        supabase.table("password_reset_tokens").delete().eq("email", registered_email).eq("used", False).execute()
        supabase.table("password_reset_tokens").insert({
            "email": registered_email,
            "token": token,
            "expires_at": expires_at,
            "used": False
        }).execute()
        reset_link = f"https://emartit.github.io/emartit-dashboard/?reset_token={token}"
        try:
            async with httpx.AsyncClient() as client:
                await client.post(
                    "https://services.leadconnectorhq.com/hooks/gc3cLEwwg5coVvb6yiOD/webhook-trigger/db1e5b80-2edd-4780-99cc-e7e0defe1473",
                    json={
                        "event": "password_reset_requested",
                        "email": registered_email,
                        "reset_link": reset_link,
                        "expires_in": "1 hour"
                    },
                    timeout=10.0
                )
        except Exception as e:
            print(f"GHL reset email error: {str(e)}")
        return generic
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/auth/reset-password")
def reset_password(data: PasswordResetConfirm):
    try:
        from database import get_supabase_client
        supabase = get_supabase_client()
        result = supabase.table("password_reset_tokens").select("*").eq("token", data.token).eq("used", False).execute()
        if not result.data:
            raise HTTPException(status_code=400, detail="Invalid or expired reset link.")
        token_row = result.data[0]
        expires_at = datetime.fromisoformat(token_row["expires_at"].replace("Z", "+00:00"))
        if datetime.now(timezone.utc) > expires_at:
            raise HTTPException(status_code=400, detail="Reset link has expired. Please request a new one.")
        new_hash = hash_password(data.new_password)
        supabase.table("client_auth").update({
            "password_hash": new_hash
        }).eq("email", token_row["email"]).execute()
        supabase.table("password_reset_tokens").update({
            "used": True
        }).eq("token", data.token).execute()
        return {"success": True, "message": "Password updated successfully. You can now log in."}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/auth/verify-reset-token/{token}")
def verify_reset_token(token: str):
    try:
        from database import get_supabase_client
        supabase = get_supabase_client()
        result = supabase.table("password_reset_tokens").select("*").eq("token", token).eq("used", False).execute()
        if not result.data:
            return {"valid": False, "message": "Invalid or already used reset link."}
        expires_at = datetime.fromisoformat(result.data[0]["expires_at"].replace("Z", "+00:00"))
        if datetime.now(timezone.utc) > expires_at:
            return {"valid": False, "message": "Reset link has expired."}
        return {"valid": True, "email": result.data[0]["email"]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
