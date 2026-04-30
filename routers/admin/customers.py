from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

try:
    from database import supabase
except ImportError:
    supabase = None

# Inisiasi Router khusus Admin CRM (Pelanggan)
router = APIRouter(prefix="/admin", tags=["Admin CRM"])
templates = Jinja2Templates(directory="templates")

def get_pending_count() -> int:
    if not supabase: return 0
    try:
        res = supabase.table("orders").select("id").eq("status", "Menunggu Pembayaran").execute()
        return len(res.data or [])
    except:
        return 0

@router.get("/customers", response_class=HTMLResponse)
async def admin_customers(request: Request):
    pelanggan = []
    if supabase:
        try:
            res = supabase.table("customers").select("*").order("created_at", desc=True).execute()
            pelanggan = res.data or []
        except Exception as e:
            print(f"❌ [ERROR PELANGGAN]: {e}")
            
    return templates.TemplateResponse("admin/customers.html", {
        "request": request, 
        "pelanggan": pelanggan, 
        "pending_count": get_pending_count()
    })