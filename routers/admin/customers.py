from typing import Optional
from datetime import datetime
import uuid, base64, asyncio

try:
    import google.genai
except ImportError:
    google = None

from fastapi import APIRouter, Request, Depends, HTTPException, status, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from database import supabase
from routers.common import logger, render_admin_template, require_admin_roles

router = APIRouter(prefix="/admin", tags=["Admin CRM"])

@router.get("/customers", response_class=HTMLResponse, dependencies=[require_admin_roles("super_admin", "marketing")])
async def admin_customers(request: Request):
    pelanggan = []
    if supabase:
        try:
            res_cust = supabase.table("customers").select("*").order("created_at", desc=True).execute()
            pelanggan = res_cust.data or []
        except Exception as e:
            logger.error(f"[ADMIN CUSTOMERS ERROR]: {e}")
    return render_admin_template(request, "admin/customers.html", pelanggan=pelanggan)

@router.post("/customers/edit/{cid}", dependencies=[require_admin_roles("super_admin", "marketing")])
async def edit_customer(
    cid: str,
    full_name: str = Form(...),
    phone: str = Form(""),
    default_address: str = Form(""),
):
    try:
        supabase.table("customers").update({
            "full_name": full_name,
            "phone": phone,
            "default_address": default_address,
        }).eq("id", cid).execute()
        return RedirectResponse(url="/admin/customers", status_code=status.HTTP_303_SEE_OTHER)
    except Exception as e:
        logger.error(f"[EDIT CUSTOMER ERROR]: {e}")
        raise HTTPException(status_code=500, detail=str(e))