from fastapi import FastAPI, HTTPException, Request
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
