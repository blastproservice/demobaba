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

@router.get("/customers", response_class=HTMLResponse, tags=["Admin CRM"], dependencies=[require_admin_roles("super_admin", "marketing")])
async def admin_customers(request: Request):
    """Menampilkan direktori klien/pelanggan beserta rekam jejak LTV (Lifetime Value)"""
    pelanggan = []
    if supabase:
        try:
            res_cust = supabase.table("customers").select("*").order("created_at", desc=True).execute()
            pelanggan = res_cust.data or []
            
            res_orders = supabase.table("orders").select("customer_id, total_amount").neq("status", "Menunggu Pembayaran").execute()
            orders_data = res_orders.data or []

            # Mapping LTV Data manual
            for c in pelanggan:
                c_orders = [o for o in orders_data if o['customer_id'] == c['id']]
                c['calc_total_orders'] = len(c_orders)
                c['calc_total_spent'] = sum(float(o['total_amount']) for o in c_orders)
                
        except Exception as e:
            logger.error(f"❌ [ADMIN CUSTOMERS ERROR]: {e}")
            
    return render_admin_template(request, "admin/customers.html", pelanggan=pelanggan)

@router.get("/customers/edit/{cid}", response_class=HTMLResponse)tags=["Admin CRM"], dependencies=[require_admin_roles("super_admin", "marketing")])
async def edit_customer(
    cid: str, 
    full_name: str = Form(...), 
    phone: str = Form(""), 
    default_address: str = Form("")
):
    try:
        supabase.table("customers").update({
            "full_name": full_name,
            "phone": phone,
            "default_address": default_address
        }).eq("id", cid).execute()
        return RedirectResponse(url="/admin/customers", status_code=status.HTTP_303_SEE_OTHER)
    except Exception as e:
        logger.error(f"❌ [EDIT CUSTOMER ERROR]: {e}")
        raise HTTPException(status_code=500, detail=str(e))
