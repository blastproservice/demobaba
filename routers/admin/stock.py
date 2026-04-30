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

@router.get("/api/v1/stock/belanja/process", tags=["API Inventory"], dependencies=[require_admin_roles("super_admin", "oprasional")])
async def api_process_purchase_order(payload: PurchaseOrderPayload):
    """CORE ENGINE: Memproses PO, potong uang bank, dan nambah stok fisik otomatis"""
    if not supabase: return api_error("Database offline", 503)

    try:
        # 1. Validasi Saldo Bank Dulu
        res_acc = supabase.table("finance_accounts").select("current_balance").eq("id", payload.account_id).single().execute()
        if not res_acc.data: return api_error("Rekening tidak ditemukan")
        
        current_balance = float(res_acc.data.get("current_balance", 0))
        total_items_cost = sum(i.quantity * i.capital_price_per_unit for i in payload.items)
        grand_total = total_items_cost + payload.shipping_cost

        if current_balance < grand_total:
            return api_error(f"Saldo rekening tidak mencukupi! Butuh: {format_currency(grand_total)}")

        # 2. Generate PO Number
        po_number = f"PO-{datetime.now().strftime('%y%m')}-{str(uuid.uuid4())[:5].upper()}"

        # 3. Insert Tabel `stock_purchases`
        po_res = supabase.table("stock_purchases").insert({
            "purchase_number": po_number,
            "account_id": payload.account_id,
            "total_items_cost": total_items_cost,
            "shipping_cost": payload.shipping_cost,
            "grand_total": grand_total,
            "notes": payload.notes
        }).execute()
        po_id = po_res.data[0].get("id")

        # 4. Insert Items & Tambah Stok Fisik
        for item in payload.items:
            subtotal = item.quantity * item.capital_price_per_unit
            supabase.table("stock_purchase_items").insert({
                "purchase_id": po_id,
                "product_id": item.product_id,
                "item_name": item.item_name,
                "quantity": item.quantity,
                "capital_price_per_unit": item.capital_price_per_unit,
                "subtotal": subtotal
            }).execute()

            # Jika barang terkait dengan produk di etalase, tambah stoknya!
            if item.product_id:
                res_prod = supabase.table("products").select("stock_quantity").eq("id", item.product_id).single().execute()
                if res_prod.data:
                    new_stock = int(res_prod.data.get("stock_quantity", 0)) + item.quantity
                    supabase.table("products").update({"stock_quantity": new_stock}).eq("id", item.product_id).execute()
                    
                    # Log penambahan stok
                    supabase.table("stock_logs").insert({
                        "product_id": item.product_id,
                        "action": "BELANJA_INBOUND",
                        "adjustment_amount": item.quantity,
                        "final_stock": new_stock,
                        "reason": f"Masuk dari PO: {po_number}"
                    }).execute()

        # 5. Potong Saldo Bank
        new_balance = current_balance - grand_total
        supabase.table("finance_accounts").update({"current_balance": new_balance}).eq("id", payload.account_id).execute()

        # 6. Catat Ledger Pengeluaran (Mutasi)
        # Cari Kategori 'Belanja Stok'
        cat_res = supabase.table("finance_categories").select("id").ilike("category_name", "%belanja%").limit(1).execute()
        cat_id = cat_res.data[0].get("id") if cat_res.data else 1 # Fallback ID 1 jika tidak nemu

        supabase.table("finance_mutations").insert({
            "account_id": payload.account_id,
            "category_id": cat_id,
            "transaction_type": "OUT",
            "amount": grand_total,
            "balance_after": new_balance,
            "description": f"Pembayaran {po_number}. {payload.notes}",
            "reference_purchase_id": po_id
        }).execute()

        logger.info(f"🚚 [PROCUREMENT] Purchase Order {po_number} senilai {grand_total} berhasil di-deploy!")
        return api_success(message="PO Berhasil diproses", po_number=po_number)

    except Exception as e:
        logger.error(f"❌ [API PO ERROR]: {e}")
        # Idealnya ada mekanisme manual rollback Supabase di sini jika gagal di tengah jalan
        return api_error(f"Gagal memproses PO: {str(e)}", 500)
