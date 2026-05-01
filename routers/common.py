import logging
from typing import Optional
from datetime import datetime

from fastapi import Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi import Request

try:
    from database import supabase
except ImportError:
    supabase = None

logger = logging.getLogger("baba")
templates = Jinja2Templates(directory="templates")

def format_currency(value):
    try:
        return f"Rp {float(value):,.0f}".replace(",", ".")
    except (ValueError, TypeError):
        return "Rp 0"

# Daftarkan filter 'currency' ke mesin Jinja
templates.env.filters["currency"] = format_currency

def render_admin_template(request: Request, template_name: str, admin_data: dict = None, **kwargs):
    """
    Fungsi render super efisien.
    Otomatis masukin admin_role dan admin_name kalau ada admin_data.
    """
    context = {"request": request}
    
    # Kalo dikasih data admin dari dependencies, otomatis inject ke UI
    if admin_data:
        context["admin_name"] = admin_data.get("admin_name", "Admin")
        context["admin_role"] = admin_data.get("admin_role", "staff")
        
    # Masukin sisa data lainnya (metrics, top_products, dll)
    context.update(kwargs)
    
    return templates.TemplateResponse(template_name, context)

# Register custom Jinja2 filters
def format_currency_filter(value) -> str:
    try:
        return f"${float(value):,.2f}"
    except:
        return "$0.00"

def format_datetime_filter(value: str) -> str:
    if not value:
        return "-"
    try:
        dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return dt.strftime("%d %b %Y, %H:%M")
    except Exception:
        return value

templates.env.filters["currency"] = format_currency_filter
templates.env.filters["datetime"] = format_datetime_filter

ALLOWED_ADMIN_ROLES = {"super_admin", "marketing", "oprasional", "cs"}
SECRET_TOKEN = "baba-secret-token"
COOKIE_NAME = "baba_admin"
ADMIN_USER = "admin"
BOT_AVAILABLE = False


def sanitize_admin_role(role: Optional[str]) -> str:
    normalized = (role or "").strip().lower()
    return normalized if normalized in ALLOWED_ADMIN_ROLES else ""


async def verify_admin(request: Request):
    request.state.admin_role = getattr(request.state, "admin_role", "super_admin")
    return True


def require_admin_roles(*allowed_roles: str):
    normalized = {sanitize_admin_role(r) for r in allowed_roles}
    normalized.discard("")

    async def dependency(request: Request):
        await verify_admin(request)
        role = getattr(request.state, "admin_role", "")
        if normalized and role not in normalized:
            raise HTTPException(status_code=403, detail="Akses ditolak")
        return True

    return Depends(dependency)


def api_success(**kwargs):
    return {"status": "success", **kwargs}


def api_error(message: str, status_code: int = 400):
    return JSONResponse(status_code=status_code, content={"status": "error", "message": message})


def safe_array(value) -> list:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        return [x.strip() for x in value.split(",") if x.strip()]
    return []


def format_currency(value) -> str:
    try:
        return f"${float(value):,.2f}"
    except Exception:
        return "$0.00"


async def get_ai_recommendation(tele_id: int, message: str) -> str:
    from ai_agent import get_ai_recommendation as _fn

    return await _fn(tele_id, message)


def render_admin_template(request: Request, template_name: str, **context):
    context.setdefault("request", request)
    context.setdefault("pending_count", 0)
    context.setdefault("flashes", [])
    return templates.TemplateResponse(template_name, context)