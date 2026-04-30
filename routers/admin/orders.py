from fastapi import APIRouter, Request, Form, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

# Import koneksi Supabase murni
try:
    from database import supabase
except ImportError:
    print("❌ [SYSTEM] File database.py tidak ditemukan!")
    supabase = None

# Inisiasi Router khusus Admin CRM (Pesanan)
router = APIRouter(prefix="/admin", tags=["Admin CRM"])
templates = Jinja2Templates(directory="templates")

# Helper buat notif lonceng merah
def get_pending_count() -> int:
    if not supabase: return 0
    try:
        res = supabase.table("orders").select("id").eq("status", "Menunggu Pembayaran").execute()
        return len(res.data or [])
    except:
        return 0

# ==============================================================================
# JALUR RENDER HALAMAN HTML
# ==============================================================================
@router.get("/orders", response_class=HTMLResponse)
async def admin_orders(request: Request):
    pesanan = []
    if supabase:
        try:
            # Tarik data order sekalian di-join sama data customers
            res = supabase.table("orders").select("*, customers(full_name, phone, username, default_address)").order("created_at", desc=True).execute()
            pesanan = res.data or []
        except Exception as e:
            print(f"❌ [ERROR PESANAN]: {e}")
            
    return templates.TemplateResponse("admin/orders.html", {
        "request": request, 
        "pesanan": pesanan, 
        "pending_count": get_pending_count()
    })

# ==============================================================================
# JALUR API / LOGIKA BISNIS (CRUD)
# ==============================================================================
@router.post("/update-order-status")
async def update_order_status(order_id: str = Form(...), status_order: str = Form(..., alias="status")):
    try:
        supabase.table("orders").update({"status": status_order}).eq("id", order_id).execute()
        return RedirectResponse(url="/admin/orders", status_code=status.HTTP_303_SEE_OTHER)
    except Exception as e:
        print(f"❌ [ERROR UPDATE STATUS]: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# 🔥 FITUR TAMBAHAN (LEVERAGE): Hapus Pesanan Fiktif/Batal
@router.get("/orders/delete/{order_id}")
async def delete_order(order_id: str):
    try:
        supabase.table("orders").delete().eq("id", order_id).execute()
        return RedirectResponse(url="/admin/orders", status_code=status.HTTP_303_SEE_OTHER)
    except Exception as e:
        print(f"❌ [ERROR HAPUS PESANAN]: {e}")
        raise HTTPException(status_code=500, detail=str(e))