from fastapi import APIRouter, Request, Form, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

# Import koneksi Supabase murni dari root
try:
    from database import supabase
except ImportError:
    print("❌ [SYSTEM] File database.py tidak ditemukan!")
    supabase = None

# Inisiasi Router khusus Admin Inventory
router = APIRouter(prefix="/admin", tags=["Admin Inventory"])
templates = Jinja2Templates(directory="templates")

# ==============================================================================
# HELPER FUNCTIONS (Supaya File Ini Mandiri & Nggak Error)
# ==============================================================================
def to_list(text: str) -> list:
    if not text or text.strip() == "": return []
    return [x.strip() for x in text.split(",") if x.strip()]

def safe_array(value) -> list:
    if isinstance(value, list): return value
    if isinstance(value, str): return to_list(value)
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
@router.get("/stock", response_class=HTMLResponse)
async def admin_stock(request: Request):
    data_parfum = []
    if supabase:
        try:
            response = supabase.table("products").select("*").order("id").execute()
            data_parfum = [normalize_product(item) for item in (response.data or [])]
        except Exception as e:
            print(f"❌ [ERROR STOK]: {e}")

    return templates.TemplateResponse("admin/stock.html", {
        "request": request, 
        "produk": data_parfum,
        "pending_count": get_pending_count()
    })

# ==============================================================================
# JALUR API / LOGIKA BISNIS (CRUD)
# ==============================================================================
@router.post("/add-product")
async def add_product(
    name: str = Form(...),
    category_id: int = Form(1),
    original_price: float = Form(0.0),
    discounted_price: float = Form(0.0),
    stock_quantity: int = Form(0),
    tags: str = Form(""),
    tagline: str = Form(""),
    description: str = Form(""),
    top_notes: str = Form(""),
    heart_notes: str = Form(""),
    base_notes: str = Form(""),
    longevity: str = Form(""),
    recommendation: str = Form(""),
    image_url: str = Form("")
):
    try:
        data_input = {
            "name": name, "category_id": category_id,
            "original_price": original_price, "discounted_price": discounted_price,
            "stock_quantity": stock_quantity, "tagline": tagline,
            "description": description, "image_url": image_url,
            "longevity": longevity, "recommendation": recommendation,
            "is_active": True,
            "tags": to_list(tags), "top_notes": to_list(top_notes),
            "heart_notes": to_list(heart_notes), "base_notes": to_list(base_notes)
        }
        supabase.table("products").insert(data_input).execute()
        return RedirectResponse(url="/admin/stock", status_code=status.HTTP_303_SEE_OTHER)
    except Exception as e:
        print(f"❌ [GAGAL SIMPAN PRODUK]: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Fitur yang dipotong sama Codex, kita kembalikan!
@router.post("/stock/edit/{pid}")
async def edit_product(pid: int, name: str = Form(...), stock_quantity: int = Form(...), discounted_price: float = Form(...)):
    try:
        supabase.table("products").update({
            "name": name, "stock_quantity": stock_quantity, "discounted_price": discounted_price
        }).eq("id", pid).execute()
        return RedirectResponse(url="/admin/stock", status_code=status.HTTP_303_SEE_OTHER)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Fitur Hapus yang juga dipotong sama Codex
@router.get("/stock/delete/{pid}")
async def delete_product(pid: int):
    try:
        supabase.table("products").delete().eq("id", pid).execute()
        return RedirectResponse(url="/admin/stock", status_code=status.HTTP_303_SEE_OTHER)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))