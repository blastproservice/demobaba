from datetime import datetime
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

try:
    from database import supabase
except ImportError:
    supabase = None

router = APIRouter(prefix="/admin", tags=["Admin Core"])
templates = Jinja2Templates(directory="templates")

# ==============================================================================
# JINJA2 FILTERS (Sihir Format Uang & Waktu)
# ==============================================================================
def format_currency(value) -> str:
    try:
        return f"${float(value):,.2f}"
    except:
        return "$0.00"

def format_datetime(value: str) -> str:
    if not value: return "-"
    try:
        dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return dt.strftime("%d %b %Y, %H:%M")
    except Exception:
        return value

# Daftarkan sihirnya ke templates
templates.env.filters["currency"] = format_currency
templates.env.filters["datetime"] = format_datetime

# ==============================================================================
# HELPER FUNCTIONS
# ==============================================================================
def get_pending_count() -> int:
    if not supabase: return 0
    try:
        res = supabase.table("orders").select("id").eq("status", "Menunggu Pembayaran").execute()
        return len(res.data or [])
    except:
        return 0

# ==============================================================================
# JALUR RENDER DASHBOARD UTAMA
# ==============================================================================
@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def admin_dashboard(request: Request):
    # Ubah nama variabel dari 'stats' jadi 'metrics' biar cocok sama HTML lu
    metrics = {
        "total_revenue": 0.0, 
        "pending_revenue": 0.0, 
        "total_products": 0, 
        "total_customers": 0, 
        "total_orders": 0, 
        "stok_kritis": 0,
        "recent_orders": [], 
        "top_products": []
    }
    
    if supabase:
        try:
            res_produk = supabase.table("products").select("*").order("stock_quantity").execute()
            res_orders = supabase.table("orders").select("*, customers(full_name)").order("created_at", desc=True).execute()
            res_cust = supabase.table("customers").select("id").execute()

            produk_data = res_produk.data or []
            orders_data = res_orders.data or []
            cust_data = res_cust.data or []

            for order in orders_data:
                amount = float(order.get('total_amount', 0))
                status = order.get('status', '')
                
                if status == 'Selesai' or status == 'Dikirim':
                    metrics["total_revenue"] += amount
                elif status == 'Menunggu Pembayaran':
                    metrics["pending_revenue"] += amount

            metrics["total_products"] = len(produk_data)
            metrics["total_customers"] = len(cust_data)
            metrics["total_orders"] = len(orders_data)
            metrics["stok_kritis"] = sum(1 for p in produk_data if int(p.get('stock_quantity', 0)) <= 10)
            metrics["recent_orders"] = orders_data[:5]
            metrics["top_products"] = sorted(produk_data, key=lambda x: int(x.get('stock_quantity', 0)))[:5]

        except Exception as e:
            print(f"❌ [ERROR DASHBOARD CORE]: {e}")

    # Kirim datanya pakai nama 'metrics'
    return templates.TemplateResponse("admin/dashboard.html", {
        "request": request, 
        "metrics": metrics, 
        "pending_count": get_pending_count()
    })