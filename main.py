from fastapi import FastAPI, HTTPException, Request, BackgroundTasks
from datetime import datetime, timezone
import httpx
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
import os
import hashlib

app = FastAPI(title="eMart IT Chatbot API", version="2.0.0")

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

ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "ematity2024")

@app.get("/")
def root():
    return {"status": "eMart IT Chatbot API is running", "version": "2.0.0"}

@app.get("/health")
def health_check():
    return {"status": "healthy"}

@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, background_tasks: BackgroundTasks):
    try:
        from database import get_supabase_client
        supabase = get_supabase_client()
        client = supabase.table("clients").select("*").eq("id", request.client_id).execute()
        if not client.data:
            raise HTTPException(status_code=404, detail="Client not found")
        client_data = client.data[0]
        account_type = client_data.get("account_type", "paid")
        is_active = client_data.get("is_active", True)
        if not is_active:
            return ChatResponse(
                reply="This chatbot is currently inactive. Please contact the business directly.",
                success=False
            )
        if account_type == "trial":
            trial_end = client_data.get("trial_end")
            trial_limit = client_data.get("trial_conversation_limit", 10)
            trial_used = client_data.get("trial_conversations_used", 0)
            if trial_end:
                trial_end_dt = datetime.fromisoformat(trial_end.replace("Z", "+00:00"))
                if datetime.now(timezone.utc) > trial_end_dt:
                    supabase.table("clients").update({
                        "account_type": "expired",
                        "is_active": False
                    }).eq("id", request.client_id).execute()
                    background_tasks.add_task(notify_ghl_trial_expired, client_data, "expired_by_time")
                    return ChatResponse(
                        reply="Our free trial has ended. Please contact us to continue using this service. 😊",
                        success=False
                    )
            if trial_used >= trial_limit:
                supabase.table("clients").update({
                    "account_type": "expired",
                    "is_active": False
                }).eq("id", request.client_id).execute()
                background_tasks.add_task(notify_ghl_trial_expired, client_data, "expired_by_usage")
                return ChatResponse(
                    reply="Our free trial has ended. Please contact us to continue using this service. 😊",
                    success=False
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
            history=request.conversation_history
        )
        return ChatResponse(reply=reply, success=True)
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error in /chat endpoint: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

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
        from datetime import datetime, timedelta, timezone
        supabase = get_supabase_client()

        # Get ALL user conversations at once
        all_convos = supabase.table("conversations").select("client_id,role,created_at").execute()
        convos = [c for c in (all_convos.data or []) if c.get("role") == "user"]

        # Build daily counts for last 30 days
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

        # Per client totals
        clients = supabase.table("clients").select("*").execute()
        client_stats = []
        for c in clients.data:
            total = sum(1 for conv in convos if conv.get("client_id") == c["id"])
            client_stats.append({
                "business_name": c.get("business_name", ""),
                "total_conversations": total
            })
        client_stats.sort(key=lambda x: x["total_conversations"], reverse=True)

        # Peak hours
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
            hours_data.append({
                "hour": f"{h:02d}:00",
                "count": count
            })

        return {
            "daily": days_data,
            "per_client": client_stats,
            "peak_hours": hours_data
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/analytics/{client_id}")
def client_analytics(client_id: str):
    try:
        from database import get_supabase_client
        from datetime import datetime, timedelta, timezone
        supabase = get_supabase_client()

        # Daily conversations last 30 days for this client
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

        # All time total
        total = supabase.table("conversations").select("id", count="exact").eq("client_id", client_id).eq("role", "user").execute()

        # This month total
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
                    "payment_link": "https://ematity.com/subscribe",
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
                    "payment_link": "https://ematity.com/subscribe",
                    "message": "Only 1 free conversation remaining!"
                },
                timeout=10.0
            )
    except Exception as e:
        print(f"GHL warning notification error: {str(e)}")

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
        existing = supabase.table("client_settings").select("*").eq("client_id", settings.client_id).execute()


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
    "bubble_color": settings.bubble_color,
    "header_color": settings.header_color,
    "chat_position": settings.chat_position,
    "bot_avatar": settings.bot_avatar,
    "welcome_message": settings.welcome_message,
    "custom_prompt": settings.custom_prompt,
    "bot_avatar_url": settings.bot_avatar_url,
    "knowledge_base": settings.knowledge_base,
"faq_items": settings.faq_items,
"proactive_enabled": settings.proactive_enabled,
"proactive_message": settings.proactive_message,
"proactive_delay": settings.proactive_delay,
"notification_email": settings.notification_email,
"notification_enabled": settings.notification_enabled,
}
        
        if existing.data:
            result = supabase.table("client_settings").update(data).eq("client_id", settings.client_id).execute()
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
        result = supabase.table("usage").select("*").eq("client_id", client_id).execute()
        return {"usage": result.data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/clients/{client_id}/settings")
def get_client_settings(client_id: str):
    try:
        from database import get_supabase_client
        supabase = get_supabase_client()
        result = supabase.table("client_settings").select("*").eq("client_id", client_id).execute()
        client = supabase.table("clients").select("*").eq("id", client_id).execute()
        return {
            "settings": result.data[0] if result.data else {},
            "client": client.data[0] if client.data else {}
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

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
def get_monthly_report():
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
def toggle_client_status(client_id: str, is_active: bool):
    try:
        from database import get_supabase_client
        supabase = get_supabase_client()
        result = supabase.table("clients").update({"is_active": is_active}).eq("id", client_id).execute()
        return {"success": True, "client": result.data[0]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/auth/register")
def register_client(data: ClientRegister):
    try:
        from database import get_supabase_client
        supabase = get_supabase_client()
        password_hash = hashlib.sha256(data.password.encode()).hexdigest()
        result = supabase.table("client_auth").insert({
            "client_id": data.client_id,
            "email": data.email,
            "password_hash": password_hash
        }).execute()
        return {"success": True, "message": "Account created successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/auth/login")
def login_client(data: ClientLogin):
    try:
        from database import get_supabase_client
        supabase = get_supabase_client()
        password_hash = hashlib.sha256(data.password.encode()).hexdigest()
        result = supabase.table("client_auth").select("*").eq("email", data.email).eq("password_hash", password_hash).execute()
        if not result.data:
            raise HTTPException(status_code=401, detail="Invalid email or password")
        auth = result.data[0]
        client = supabase.table("clients").select("*").eq("id", auth["client_id"]).execute()
        if not client.data or not client.data[0]["is_active"]:
            raise HTTPException(status_code=403, detail="Account is inactive")
        return {
            "success": True,
            "client_id": auth["client_id"],
            "client": client.data[0]
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

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
        return {"conversations": convos.data}
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
async def notify_ghl(payload: GHLPayload):
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


class PasswordChange(BaseModel):
    client_id: str
    email: str
    new_password: str

@app.post("/auth/change-password")
def change_password(data: PasswordChange):
    try:
        from database import get_supabase_client
        supabase = get_supabase_client()
        new_hash = hashlib.sha256(data.new_password.encode()).hexdigest()
        supabase.table("client_auth").update({
            "password_hash": new_hash
        }).eq("client_id", data.client_id).eq("email", data.email).execute()
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# PHASE B/C/D/E — LEADS & OFFLINE MODE
# ============================================

class LeadCapture(BaseModel):
    client_id: str
    visitor_name: Optional[str] = ""
    visitor_email: Optional[str] = ""
    visitor_phone: Optional[str] = ""
    message: Optional[str] = ""

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

@app.post("/leads/capture")
async def capture_lead(data: LeadCapture):
    try:
        from database import get_supabase_client
        supabase = get_supabase_client()
        result = supabase.table("leads").insert({
            "client_id": data.client_id,
            "visitor_name": data.visitor_name,
            "visitor_email": data.visitor_email,
            "visitor_phone": data.visitor_phone,
            "message": data.message
        }).execute()
        return {"success": True, "lead": result.data[0]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/leads/{client_id}")
def get_leads(client_id: str):
    try:
        from database import get_supabase_client
        supabase = get_supabase_client()
        result = supabase.table("leads").select("*").eq("client_id", client_id).order("created_at", desc=True).execute()
        return {"leads": result.data}
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
        return {"leads": result.data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/clients/offline-settings")
def save_offline_settings(data: OfflineSettings):
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
async def upload_avatar(client_id: str, file: bytes = None, request: Request = None):
    try:
        from database import get_supabase_client
        import base64
        supabase = get_supabase_client()
        body = await request.body()
        data = await request.json()
        image_data = data.get("image_data", "")
        file_name = data.get("file_name", "avatar.png")
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

@app.post("/requests/incoming")
async def incoming_request(request: Request):
    try:
        from database import get_supabase_client
        supabase = get_supabase_client()
        data = await request.json()

        # Save to trial_requests table
        result = supabase.table("trial_requests").insert({
            "name": data.get("name", ""),
            "business_name": data.get("business_name", ""),
            "business_type": data.get("business_type", ""),
            "email": data.get("email", ""),
            "phone": data.get("phone", ""),
            "website": data.get("website", ""),
            "location": data.get("location", ""),
            "working_hours": data.get("working_hours", ""),
            "services": data.get("services", ""),
            "description": data.get("description", ""),
            "price_range": data.get("price_range", ""),
            "special_instructions": data.get("special_instructions", ""),
            "request_type": data.get("request_type", "trial"),
            "ghl_contact_id": data.get("contact_id", ""),
            "document_url": data.get("document_url", ""),
            "status": "pending"
        }).execute()
# Forward to GHL
        try:
            async with httpx.AsyncClient() as client:
                await client.post(
                    "https://services.leadconnectorhq.com/hooks/gc3cLEwwg5coVvb6yiOD/webhook-trigger/a1e70441-b76b-4a2a-b91f-d1b1ac4db821",
                    json=data,
                    timeout=10.0
                )
        except Exception as e:
            print(f"GHL forward error: {str(e)}")
            
        return {"success": True, "message": "Request received"}
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

@app.post("/admin/requests/{request_id}/approve")
async def approve_request(request_id: str, x_admin_token: str = None):
    expected = "admin_" + ADMIN_PASSWORD
    if not x_admin_token or x_admin_token != expected:
        raise HTTPException(status_code=401, detail="Unauthorized")
    try:
        from database import get_supabase_client
        import hashlib
        import secrets
        supabase = get_supabase_client()

        # Get the request
        req = supabase.table("trial_requests").select("*").eq("id", request_id).execute()
        if not req.data:
            raise HTTPException(status_code=404, detail="Request not found")
        r = req.data[0]

        # Generate password
        password = secrets.token_urlsafe(8)

        # Check if email already exists
        existing_client = supabase.table("clients").select("*").eq("email", r["email"]).execute()
        if existing_client.data:
            existing = existing_client.data[0]
            existing_type = existing.get("account_type", "paid")

            # Already paid — block
            if existing_type == "paid":
                raise HTTPException(status_code=400, detail="This email already has an active paid account.")

            # Existing trial or expired — convert to paid
            if existing_type in ["trial", "expired"]:
                supabase.table("clients").update({
                    "account_type": "paid",
                    "is_active": True,
                    "trial_start": None,
                    "trial_end": None,
                    "trial_conversations_used": 0
                }).eq("id", existing["id"]).execute()
                supabase.table("trial_requests").update({
                    "status": "approved"
                }).eq("id", request_id).execute()
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
                                "payment_link": "https://www.emartit.com/subscribe"
                            },
                            timeout=10.0
                        )
                except Exception as e:
                    print(f"GHL error: {str(e)}")
                return {
                    "success": True,
                    "client_id": existing["id"],
                    "password": "Use existing password",
                    "message": "✅ Existing trial client successfully converted to PAID!"
                }

        # Create new client
        client_result = supabase.table("clients").insert({
            "name": r["name"],
            "email": r["email"],
            "business_name": r["business_name"],
            "business_type": r["business_type"]
        }).execute()
        client_id = client_result.data[0]["id"]

        # Set trial or paid
        if r["request_type"] == "trial":
            from datetime import datetime, timedelta, timezone
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

        # Create login
        password_hash = hashlib.sha256(password.encode()).hexdigest()
        supabase.table("client_auth").insert({
            "client_id": client_id,
            "email": r["email"],
            "password_hash": password_hash
        }).execute()

        # Save settings
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

        # Update request status
        supabase.table("trial_requests").update({
            "status": "approved"
        }).eq("id", request_id).execute()

        # Notify GHL
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
                        "payment_link": "https://www.emartit.com/subscribe"
                    },
                    timeout=10.0
                )
        except Exception as e:
            print(f"GHL notification error: {str(e)}")

        return {
            "success": True,
            "client_id": client_id,
            "password": password,
            "message": f"Account created successfully"
        }
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
        supabase.table("trial_requests").update({
            "status": "rejected"
        }).eq("id", request_id).execute()
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
@app.post("/requests/upload-doc")
async def upload_doc(request: Request):
    try:
        from database import get_supabase_client
        import base64
        supabase = get_supabase_client()
        data = await request.json()
        file_data = data.get("file_data", "")
        file_name = data.get("file_name", "document.pdf")
        content_type = data.get("content_type", "application/pdf")
        request_email = data.get("email", "unknown")
        if not file_data:
            raise HTTPException(status_code=400, detail="No file data provided")
        # Decode base64
        file_bytes = base64.b64decode(file_data.split(",")[-1])
        # Check file size — max 5MB
        if len(file_bytes) > 5 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="File too large. Maximum size is 5MB.")
        # Create unique file path
        import uuid
        file_path = f"{request_email}/{uuid.uuid4()}_{file_name}"
        # Upload to Supabase storage
        supabase.storage.from_("business-docs").upload(
            file_path,
            file_bytes,
            {"content-type": content_type, "upsert": "true"}
        )
        # Get public URL
        public_url = supabase.storage.from_("business-docs").get_public_url(file_path)
        return {"success": True, "url": public_url, "file_name": file_name}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
