import os

def get_supabase_client():
    from supabase import create_client
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SECRET_KEY")
    if not url or not key:
        raise Exception("Supabase credentials not set")
    return create_client(url, key)

def get_client_settings(client_id: str) -> dict:
    supabase = get_supabase_client()
    result = supabase.table("client_settings").select("*").eq("client_id", client_id).execute()
    if result.data:
        return result.data[0]
    return {}

def get_client(client_id: str) -> dict:
    supabase = get_supabase_client()
    result = supabase.table("clients").select("*").eq("id", client_id).eq("is_active", True).execute()
    if result.data:
        return result.data[0]
    return {}

def log_conversation(client_id: str, session_id: str, message: str, role: str):
    try:
        supabase = get_supabase_client()
        supabase.table("conversations").insert({
            "client_id": client_id,
            "session_id": session_id,
            "message": message,
            "role": role
        }).execute()
    except Exception as e:
        print(f"Log error: {e}")

def increment_usage(client_id: str, input_tokens: int = 0, output_tokens: int = 0):
    try:
        from datetime import datetime
        now = datetime.now()
        supabase = get_supabase_client()

        # Cost calculation
        # Claude API: ~$0.003 per 1K input tokens, ~$0.015 per 1K output tokens
        input_cost = (input_tokens / 1000) * 0.003
        output_cost = (output_tokens / 1000) * 0.015
        total_cost = input_cost + output_cost
        total_tokens = input_tokens + output_tokens

        existing = supabase.table("usage").select("*")\
            .eq("client_id", client_id)\
            .eq("month", now.month)\
            .eq("year", now.year)\
            .execute()

        if existing.data:
            usage_id = existing.data[0]["id"]
            current_count = existing.data[0]["conversation_count"]
            current_tokens = existing.data[0].get("token_count", 0)
            supabase.table("usage").update({
                "conversation_count": current_count + 1,
                "token_count": current_tokens + total_tokens
            }).eq("id", usage_id).execute()
        else:
            supabase.table("usage").insert({
                "client_id": client_id,
                "month": now.month,
                "year": now.year,
                "conversation_count": 1,
                "token_count": total_tokens
            }).execute()

        return round(total_cost, 6)

    except Exception as e:
        print(f"Usage error: {e}")
        return 0

def get_monthly_report() -> list:
    try:
        from datetime import datetime
        now = datetime.now()
        supabase = get_supabase_client()

        # Get all clients
        clients = supabase.table("clients").select("*").eq("is_active", True).execute()

        report = []
        for client in clients.data:
            # Get usage for this month
            usage = supabase.table("usage").select("*")\
                .eq("client_id", client["id"])\
                .eq("month", now.month)\
                .eq("year", now.year)\
                .execute()

            conversations = 0
            tokens = 0
            if usage.data:
                conversations = usage.data[0]["conversation_count"]
                tokens = usage.data[0].get("token_count", 0)

            # Cost calculations
            api_cost = round((tokens / 1000) * 0.009, 4)
            charge_to_client = round(conversations * 0.07, 2)
            monthly_minimum = 10.00
            total_charge = max(charge_to_client, monthly_minimum)
            profit = round(total_charge - api_cost, 2)

            report.append({
                "client_name": client["name"],
                "business_name": client["business_name"],
                "email": client["email"],
                "conversations": conversations,
                "tokens_used": tokens,
                "api_cost_usd": api_cost,
                "charge_to_client_usd": total_charge,
                "your_profit_usd": profit
            })

        return report

    except Exception as e:
        print(f"Report error: {e}")
        return []
