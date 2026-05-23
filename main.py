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
    custom_prompt: Optional[str] = ""

class ClientLogin(BaseModel):
    email: str
    password: str

class ClientRegister(BaseModel):
    client_id: str
    email: str
    password: str

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

        # Get client info
        client = supabase.table("clients").select("*").eq("id", request.client_id).execute()
        if not client.data:
            raise HTTPException(status_code=404, detail="Client not found")

        client_data = client.data[0]
        account_type = client_data.get("account_type", "paid")
        is_active = client_data.get("is_active", True)

        # Check if client is active
        if not is_active:
            return ChatResponse(
                reply="This chatbot is currently inactive. Please contact the business directly.",
                success=False
            )

        # Trial checks
        if account_type == "trial":
            trial_end = client_data.get("trial_end")
            trial_limit = client_data.get("trial_conversation_limit", 10)
            trial_used = client_data.get("trial_conversations_used", 0)

            # Check trial expiry by date
            if trial_end:
                trial_end_dt = datetime.fromisoformat(trial_end.replace("Z", "+00:00"))
                if datetime.now(timezone.utc) > trial_end_dt:
                    # Trial expired by date — update account
                    supabase.table("clients").update({
                        "account_type": "expired",
                        "is_active": False
                    }).eq("id", request.client_id).execute()
                    # Notify GHL
                    background_tasks.add_task(notify_ghl_trial_expired, client_data, "expired_by_time")
                    return ChatResponse(
                        reply="Our free trial has ended. Please contact us to continue using this service. 😊",
                        success=False
                    )

            # Check trial expiry by conversation limit
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

            # Increment trial conversation count
            supabase.table("clients").update({
                "trial_conversations_used": trial_used + 1
            }).eq("id", request.client_id).execute()

            # Send warning when 1 conversation left
            if trial_used + 1 == trial_limit - 1:
                background_tasks.add_task(notify_ghl_trial_warning, client_data)

        # Process chat normally
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
            "custom_prompt": settings.custom_prompt
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

ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "ematity2024")

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
        from datetime import datetime
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
        from datetime import datetime
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

@app.post("/admin/notify-ghl")
async def notify_ghl(payload: GHLPayload):
    import httpx
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


# ============================================
# TRIAL MANAGEMENT ENDPOINTS
# ============================================

class TrialCheck(BaseModel):
    email: Optional[str] = ""
    phone: Optional[str] = ""
    website: Optional[str] = ""

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

@app.get("/clients/{client_id}/trial-status")
def get_trial_status(client_id: str):
    try:
        from database import get_supabase_client
        from datetime import datetime, timezone
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


class TrialSetup(BaseModel):
    trial_end: str

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
