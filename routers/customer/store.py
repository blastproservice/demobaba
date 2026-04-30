from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

# Import koneksi Supabase murni dari root
try:
    from database import supabase
except ImportError:
    print("❌ [SYSTEM] File database.py tidak ditemukan!")
    supabase = None

# Inisiasi Router khusus toko customer (tanpa prefix biar langsung jalan di domain utama)
router = APIRouter(tags=["Customer Front End"])
templates = Jinja2Templates(directory="templates")

# ==============================================================================
# HELPER KHUSUS FRONTEND (Pembersih Data)
# ==============================================================================
def safe_array(value) -> list:
    if isinstance(value, list): return value
    if isinstance(value, str): 
        return [x.strip() for x in value.split(",") if x.strip()]
    return []

def normalize_product(item: dict) -> dict:
    return {
        "id": item.get("id"),
        "name": item.get("name") or "Tanpa Nama",
        "tagline": item.get("tagline") or "-",
        "description": item.get("description") or "",
        "image_url": item.get("image_url") or "https://placehold.co/80x80/101010/D4AF37?text=BABA",
        "original_price": float(item.get("original_price") or 0.0),
        "discounted_price": float(item.get("discounted_price") or 0.0),
        "stock_quantity": int(item.get("stock_quantity") or 0),
        "tags": safe_array(item.get("tags")),
        "top_notes": safe_array(item.get("top_notes")),
        "heart_notes": safe_array(item.get("heart_notes")),
        "base_notes": safe_array(item.get("base_notes")),
        "longevity": item.get("longevity") or "-",
        "recommendation": item.get("recommendation") or "-",
        "is_active": bool(item.get("is_active", True))
    }

# ==============================================================================
# JALUR HTML (WEB APP)
# ==============================================================================
@router.get("/", response_class=HTMLResponse)
async def halaman_utama(request: Request):
    return templates.TemplateResponse("customer/index.html", {"request": request})

@router.get("/profile", response_class=HTMLResponse)
async def halaman_profil(request: Request):
    return templates.TemplateResponse("customer/profile.html", {"request": request})

@router.get("/cs", response_class=HTMLResponse)
async def halaman_cs(request: Request):
    return templates.TemplateResponse("customer/cs.html", {"request": request})

# ==============================================================================
# JALUR API EXTERNAL (Penyedot Data Realtime)
# ==============================================================================
@router.get("/api/v1/products/live")
async def api_get_live_products():
    """Jalur pipa khusus biar index.html bisa nyedot data stok realtime"""
    if not supabase:
        return JSONResponse(status_code=500, content={"error": "Database tidak terhubung"})
    try:
        # Tarik semua produk yang statusnya aktif
        res = supabase.table("products").select("*").eq("is_active", True).order("id").execute()
        
        # Bersihkan data biar nggak bikin crash frontend HTML lu
        data_bersih = [normalize_product(p) for p in (res.data or [])]
        
        return {"status": "success", "data": data_bersih}
    except Exception as e:
        print(f"❌ [ERROR API PRODUK]: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})