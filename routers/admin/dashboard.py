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
@router.get("", response_class=HTMLResponse, tags=["Admin Core"], dependencies=[Depends(verify_admin)])
@router.get("/", response_class=HTMLResponse, tags=["Admin Core"], dependencies=[Depends(verify_admin)])
async def admin_dashboard(request: Request):
    """Pusat Komando: Kalkulasi metrik omset, jumlah order, dan pelanggan"""
    metrics = {
        "total_revenue": 0.0, "revenue_growth": 0.0, 
        "total_orders": 0, "completed_orders": 0,
        "total_customers": 0, "new_customers": 0,
        "low_stock_count": 0,
        "cat_man": 0, "cat_woman": 0, "cat_netral": 0
    }
    recent_orders = []
    top_products = []
    
    if supabase:
        try:
            # Ambil Raw Data
            res_produk = supabase.table("products").select("*").execute()
            res_orders = supabase.table("orders").select("*, customers(full_name)").order("created_at", desc=True).execute()
            res_cust = supabase.table("customers").select("id, created_at").execute()

            produk_data = res_produk.data or []
            orders_data = res_orders.data or []
            cust_data = res_cust.data or []

            # 1. Analisis Inventaris (Kategori & Alert Stok)
            for p in produk_data:
                tags = [t.upper() for t in safe_array(p.get("tags"))]
                stok = int(p.get("stock_quantity", 0))
                
                if stok <= 5 and p.get("is_active", True): 
                    metrics["low_stock_count"] += 1

                if "MAN" in tags and "WOMAN" not in tags: metrics["cat_man"] += stok
                elif "WOMAN" in tags: metrics["cat_woman"] += stok
                elif "NETRAL" in tags or "UNISEX" in tags: metrics["cat_netral"] += stok

            # 2. Analisis Finansial
            metrics["total_orders"] = len(orders_data)
            for o in orders_data:
                if o.get("status") in ["Selesai", "Dikirim", "Diproses"]: # Hitung omset dari yang udah jalan
                    metrics["completed_orders"] += 1
                    metrics["total_revenue"] += float(o.get("total_amount", 0))

            # 3. Analisis Demografi
            metrics["total_customers"] = len(cust_data)
            current_month = datetime.now().month
            new_cust = [c for c in cust_data if datetime.fromisoformat(c['created_at'].replace('Z', '+00:00')).month == current_month]
            metrics["new_customers"] = len(new_cust)

            # Slicing untuk tampilan UI
            recent_orders = orders_data[:5] # Tampilkan 5 terbaru
            top_products = sorted(produk_data, key=lambda x: x.get('stock_quantity', 0))[:4] # 4 Barang stok menipis

        except Exception as e:
            logger.error(f"❌ [ADMIN DASHBOARD ERROR]: {e}")

    return render_admin_template(
        request,
        "admin/dashboard.html",
        metrics=metrics,
        recent_orders=recent_orders,
        top_products=top_products
    )
