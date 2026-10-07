# ============================================
# SECURITY & PRIVACY helpers
# eMart IT Chatbot backend
#
#   - Passwords: slow salted hash (PBKDF2). Old passwords still work and are
#     upgraded automatically the next time the client logs in.
#   - Access checks: admin-only, or "this client (login token) or admin".
#   - Privacy: visitor emails / phone numbers are masked in the admin panel.
#     Revealing them is recorded in the `admin_access_log` table.
# ============================================

import os
import re
import hmac
import hashlib
import secrets
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException

PBKDF2_ITERATIONS = 200_000


# --------------------------------------------
# Passwords
# --------------------------------------------

def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), PBKDF2_ITERATIONS).hex()
    return f"pbkdf2${PBKDF2_ITERATIONS}${salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    stored = stored or ""
    if stored.startswith("pbkdf2$"):
        try:
            _, iterations, salt, digest = stored.split("$", 3)
            check = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), int(iterations)).hex()
            return hmac.compare_digest(check, digest)
        except Exception:
            return False
    # older accounts: plain SHA-256
    return hmac.compare_digest(hashlib.sha256(password.encode()).hexdigest(), stored)


def needs_upgrade(stored: str) -> bool:
    return not (stored or "").startswith("pbkdf2$")


# --------------------------------------------
# Access checks
# --------------------------------------------

def is_admin(x_admin_token: Optional[str]) -> bool:
    expected = "admin_" + os.environ.get("ADMIN_PASSWORD", "ematity2024")
    return bool(x_admin_token) and hmac.compare_digest(x_admin_token, expected)


def require_admin(x_admin_token: Optional[str]):
    if not is_admin(x_admin_token):
        raise HTTPException(status_code=401, detail="Unauthorized")


def token_client(token: Optional[str]) -> Optional[str]:
    if not token:
        return None
    from knowledge import verify_client_token
    return verify_client_token(token)


def require_client_or_admin(client_id: str, token: Optional[str], x_admin_token: Optional[str]):
    """Allowed: the admin, or the client itself (valid login token for this client_id)."""
    if is_admin(x_admin_token):
        return
    owner = token_client(token)
    if not owner:
        raise HTTPException(status_code=401, detail="Your session has expired. Please log out and log in again.")
    if str(owner) != str(client_id):
        raise HTTPException(status_code=403, detail="Not allowed.")


# --------------------------------------------
# Privacy: masking visitor contact details for the admin
# --------------------------------------------

_EMAIL_RE = re.compile(r"([A-Za-z0-9._%+-]+)@([A-Za-z0-9.-]+\.[A-Za-z]{2,})")
_PHONE_RE = re.compile(r"\+?\d[\d\s().-]{6,}\d")


def mask_email(email: str) -> str:
    email = (email or "").strip()
    if "@" not in email:
        return email
    local, domain = email.split("@", 1)
    return (local[:2] if len(local) > 2 else local[:1]) + "•••@" + domain


def mask_phone(phone: str) -> str:
    phone = (phone or "").strip()
    digits = re.sub(r"\D", "", phone)
    if len(digits) < 5:
        return phone
    prefix = "+" if phone.startswith("+") else ""
    return prefix + digits[:3] + "•••••" + digits[-4:]


def mask_text(text: str) -> str:
    """Mask emails and phone numbers inside free text (chat messages)."""
    text = text or ""
    text = _EMAIL_RE.sub(lambda m: mask_email(m.group(0)), text)
    def _phone(m):
        return mask_phone(m.group(0)) if len(re.sub(r"\D", "", m.group(0))) >= 7 else m.group(0)
    return _PHONE_RE.sub(_phone, text)


def mask_contact_fields(row: dict) -> dict:
    row = dict(row)
    if row.get("visitor_email"):
        row["visitor_email"] = mask_email(row["visitor_email"])
    if row.get("visitor_phone"):
        row["visitor_phone"] = mask_phone(row["visitor_phone"])
    for key in ("summary", "message", "notes"):
        if row.get(key):
            row[key] = mask_text(row[key])
    row["masked"] = True
    return row


def log_admin_access(action: str, client_id: str, item_type: str, item_id: str, reason: str = ""):
    """Record that the admin revealed a client's private data."""
    try:
        from database import get_supabase_client
        get_supabase_client().table("admin_access_log").insert({
            "action": action,
            "client_id": str(client_id),
            "item_type": item_type,
            "item_id": str(item_id),
            "reason": (reason or "")[:300],
            "created_at": datetime.now(timezone.utc).isoformat(),
        }).execute()
    except Exception as e:
        print(f"Access log error: {e}")
