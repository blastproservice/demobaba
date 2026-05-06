"""
====================================================================================
BABA PARFUME - INVENTORY & PROCUREMENT ENGINE (ULTIMATE ENTERPRISE EDITION)
====================================================================================
Deskripsi : Jantung dari sistem gudang BABA Parfume. Menangani:
            1. Master Data Produk (CRUD & Etalase)
            2. Pengadaan Barang / Purchase Order (Restock terintegrasi Finance)
            3. Penyesuaian Manual / Stock Opname (Koreksi dengan Audit Trail ketat)
            4. Reservation System (Sistem Pending Stok untuk Orderan masuk)
            5. Stock Analytics & Log History dengan Period Filter
Arsitektur: FastAPI + Supabase + Pydantic Strict Validation + Modular Pattern
====================================================================================
"""
import uuid
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, Request, Form, HTTPException, status, Depends
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from pydantic import BaseModel, Field

# Setup logger khusus modul stok agar error mudah dilacak
logger = logging.getLogger("baba.stock.engine")

# Import Modul Internal
from routers.common import templates, render_admin_template, require_admin_roles, api_success, api_error, format_currency
from routers.dependencies import get_current_admin

try:
    from database import supabase
except ImportError:
    logger.critical("❌ [SYSTEM FATAL] File database.py tidak ditemukan! Sistem akan crash.")
    supabase = None

# ==============================================================================
# INISIASI ROUTER
# ==============================================================================
router = APIRouter(prefix="/admin", tags=["Stock Management Engine"])


# ==============================================================================
# 1. ENTERPRISE SCHEMAS (Tameng Validasi & Anti-Error 500)
# ==============================================================================
class PurchaseItem(BaseModel):
    product_id: int = Field(..., gt=0)
    item_name: str = Field(..., min_length=1)
    quantity: int = Field(..., gt=0)
    capital_price_per_unit: float = Field(..., ge=0)

class PurchaseOrderPayload(BaseModel):
    account_id: int = Field(..., gt=0, description="ID Rekening sumber dana")
    shipping_cost: float = Field(default=0.0, ge=0)
    notes: str = Field(default="")
    items: List[PurchaseItem] = Field(..., min_items=1)

class StockAdjustmentPayload(BaseModel):
    product_id: int = Field(..., gt=0)
    action: str = Field(..., description="'IN' untuk penambahan, 'OUT' untuk pengurangan")
    adjustment_amount: int = Field(..., gt=0, description="Kuantitas harus lebih dari 0")
    reason: str = Field(..., min_length=5, description="Alasan wajib untuk audit")

class OrderReservePayload(BaseModel):
    order_id: str = Field(..., description="UUID dari order yang masuk")
    items: List[dict] = Field(..., description="List of dict: product_id dan quantity")

class OrderResolvePayload(BaseModel):
    order_id: str = Field(..., description="UUID dari order yang diproses")
    status: str = Field(..., description="'COMPLETED' jika lunas, 'CANCELLED' jika batal")


# ==============================================================================
# 2. UTILITY & HELPER FUNCTIONS
# ==============================================================================
def to_list(text: str) -> list:
    """Konversi string dipisahkan koma menjadi list bersih"""
    if not text or text.strip() == "": return []
    return [x.strip() for x in str(text).split(",") if x.strip()]

def safe_array(value) -> list:
    if isinstance(value, list): return value
    if isinstance(value, str): return to_list(value)
    return []

def normalize_product(item: dict) -> dict:
    """Format produk agar aman, konsisten, dan siap di-render ke Jinja2"""
    return {
        "id": item.get("id"),
        "name": item.get("name") or "Unnamed Product",
        "tagline": item.get("tagline") or "-",
        "description": item.get("description") or "",
        "image_url": item.get("image_url") or "https://placehold.co/150x150/111827/FBBF24?text=BABA",
        "original_price": float(item.get("original_price") or 0.0),
        "discounted_price": float(item.get("discounted_price") or 0.0),
        "stock_quantity": int(item.get("stock_quantity") or 0),
        "tags": safe_array(item.get("tags")),
        "top_notes": safe_array(item.get("top_notes")),
        "heart_notes": safe_array(item.get("heart_notes")),
        "base_notes": safe_array(item.get("base_notes")),
        "longevity": item.get("longevity") or "-",
        "recommendation": item.get("recommendation") or "-",
        "is_active": bool(item.get("is_active", True)),
        "categories": item.get("categories") # <--- TAMBAHAN INI BRE BIAR FILTER FRONTEND JALAN
    }

def get_pending_count() -> int:
    """Mengambil jumlah pesanan yang belum dibayar untuk notifikasi global"""
    if not supabase: return 0
    try:
        res = supabase.table("orders").select("id", count="exact").eq("status", "Menunggu Pembayaran").execute()
        return res.count or 0
    except:
        return 0


# ==============================================================================
# 3. VIEWS (RENDER HALAMAN HTML & DASHBOARD UI)
# ==============================================================================

@router.get("/stock")
async def stock_page(request: Request, admin=Depends(get_current_admin)):
    """Render Halaman Dashboard Gudang Utama (Katalog & Nilai Aset)"""
    data_parfum = []
    stats = {"total_items": 0, "total_asset_value": 0, "low_stock_items": 0}
    
    if supabase:
        try:
            # FIX 1: Tambah "categories(name, slug)" buat ambil data relasi kategori
            # FIX 2: Ubah desc=False jadi desc=True biar stok terbanyak di atas
            response = supabase.table("products").select("*, categories(name, slug)").eq("is_active", True).order("stock_quantity", desc=True).execute()
            
            for item in response.data or []:
                prod = normalize_product(item)
                data_parfum.append(prod)
                
                # Kalkulasi Analitik Gudang
                stats["total_items"] += prod["stock_quantity"]
                stats["total_asset_value"] += (prod["stock_quantity"] * prod["original_price"])
                if prod["stock_quantity"] <= 5:
                    stats["low_stock_items"] += 1
        except Exception as e:
            logger.error(f"❌ [ERROR LOAD STOK MASTER]: {e}")

    return render_admin_template(
        request,
        "admin/stock.html",
        admin_data=admin,
        produk=data_parfum,
        stats=stats,
        pending_count=get_pending_count()
    )


@router.get("/stock/belanja")
async def belanja_po_page(request: Request, admin=Depends(get_current_admin)):
    """Render Halaman Pengadaan / Purchase Order (Restock)"""
    accounts, products, purchases = [], [], []
    
    if supabase:
        try:
            # Tarik Rekening Aktif
            res_acc = supabase.table("finance_accounts").select("id, bank_name, currency, current_balance").eq("is_active", True).execute()
            accounts = res_acc.data or []
            
            # Tarik Produk
            res_prod = supabase.table("products").select("id, name, original_price, stock_quantity").eq("is_active", True).order("name").execute()
            products = res_prod.data or []
            
            # Tarik History PO
            res_po = supabase.table("stock_purchases").select(
                "*, finance_accounts(bank_name), stock_purchase_items(item_name)"
            ).order("created_at", desc=True).limit(200).execute()
            purchases = res_po.data or []
        except Exception as e:
            logger.error(f"❌ [ERROR LOAD BELANJA PO]: {e}")

    return render_admin_template(
        request, 
        "admin/stock_belanja.html", 
        admin_data=admin,
        accounts=accounts,
        products=products,
        purchases=purchases,
        pending_count=get_pending_count()
    )

@router.get("/stock/mutation")
async def stock_mutation_page(request: Request, admin=Depends(get_current_admin)):
    """Render Halaman Mutasi Stok & Audit Trail V2.1 (Full Log Integration)"""
    products, logs = [], []
    
    if supabase:
        try:
            # Dropdown Manual Adjustment
            res_prod = supabase.table("products").select("id, name, stock_quantity").eq("is_active", True).order("name").execute()
            products = res_prod.data or []
            
            # Tarik log mutasi (Limit dinaikkan agar filter periode di frontend bekerja maksimal)
            # Pastikan database sudah punya kolom reference_type, reference_id, dan status
            res_logs = supabase.table("stock_logs").select(
                "id, product_id, action, adjustment_amount, final_stock, reason, created_at, reference_type, reference_id, status, products(name)"
            ).order("created_at", desc=True).limit(1000).execute()
            logs = res_logs.data or []
        except Exception as e:
            logger.error(f"❌ [ERROR LOAD MUTASI LOGS]: {e}")

    return render_admin_template(
        request, 
        "admin/stock_mutation.html", 
        admin_data=admin,
        products=products,
        logs=logs,
        pending_count=get_pending_count()
    )


# ==============================================================================
# 4. MASTER DATA MODIFICATION ENDPOINTS
# ==============================================================================

@router.post("/add-product")
async def add_product(
    name: str = Form(...), category_id: int = Form(1),
    original_price: float = Form(0.0), discounted_price: float = Form(0.0),
    stock_quantity: int = Form(0), tags: str = Form(""),
    tagline: str = Form(""), description: str = Form(""),
    top_notes: str = Form(""), heart_notes: str = Form(""),
    base_notes: str = Form(""), longevity: str = Form(""),
    recommendation: str = Form(""), image_url: str = Form(""),
    admin=Depends(get_current_admin)
):
    """Create New Product & Initialize Stock Log"""
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
        res = supabase.table("products").insert(data_input).execute()
        
        # Log Inisialisasi
        if stock_quantity > 0 and res.data:
            new_id = res.data[0]['id']
            admin_name = admin.get("admin_name", "System")
            supabase.table("stock_logs").insert({
                "product_id": new_id, 
                "action": "IN",
                "adjustment_amount": stock_quantity, 
                "final_stock": stock_quantity,
                "reason": f"[{admin_name}] Inisialisasi produk baru di database",
                "reference_type": "ADJUSTMENT",
                "status": "COMPLETED"
            }).execute()

        return RedirectResponse(url="/admin/stock", status_code=status.HTTP_303_SEE_OTHER)
    except Exception as e:
        logger.error(f"❌ [GAGAL SIMPAN PRODUK]: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/stock/edit/{pid}")
async def edit_product(pid: int, name: str = Form(...), stock_quantity: int = Form(...), discounted_price: float = Form(...)):
    """Fast Edit Product dari Dashboard. Peringatan: Tidak disarankan merubah qty dari sini untuk audit!"""
    try:
        supabase.table("products").update({
            "name": name, "stock_quantity": stock_quantity, "discounted_price": discounted_price
        }).eq("id", pid).execute()
        return RedirectResponse(url="/admin/stock", status_code=status.HTTP_303_SEE_OTHER)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stock/delete/{pid}")
async def delete_product(pid: int, admin=Depends(get_current_admin)):
    """Soft Delete Produk untuk menjaga integritas transaksi lama"""
    try:
        supabase.table("products").update({"is_active": False, "stock_quantity": 0}).eq("id", pid).execute() 
        
        admin_name = admin.get("admin_name", "System")
        supabase.table("stock_logs").insert({
            "product_id": pid, 
            "action": "OUT",
            "adjustment_amount": 0, 
            "final_stock": 0,
            "reason": f"[{admin_name}] Produk diarsipkan dari etalase",
            "reference_type": "ADJUSTMENT",
            "status": "COMPLETED"
        }).execute()
        
        return RedirectResponse(url="/admin/stock", status_code=status.HTTP_303_SEE_OTHER)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==============================================================================
# 5. CORE ENGINES (API TRANSAKSI GUDANG ENTERPRISE)
# ==============================================================================

@router.post("/api/v1/stock/belanja/process", tags=["API Inventory"])
async def api_process_purchase_order(payload: PurchaseOrderPayload, admin=Depends(get_current_admin)):
    """CORE ENGINE 1: PROCUREMENT (PO) -> Auto potong bank, nambah stok, & Audit Log"""
    
    if admin.get("admin_role") not in ["super_admin", "oprasional"]:
        return api_error("Akses ditolak. Hubungi Super Admin.", 403)
        
    if not supabase: return api_error("Database offline", 503)

    try:
        # Cek Saldo
        res_acc = supabase.table("finance_accounts").select("current_balance").eq("id", payload.account_id).single().execute()
        if not res_acc.data: return api_error("Rekening bank tidak valid.")
        
        current_balance = float(res_acc.data.get("current_balance", 0))
        total_items_cost = sum(i.quantity * i.capital_price_per_unit for i in payload.items)
        grand_total = total_items_cost + payload.shipping_cost

        if current_balance < grand_total:
            return api_error(f"Saldo rekening tidak cukup! Butuh: {format_currency(grand_total)}")

        po_number = f"PO-{datetime.now().strftime('%y%m%d')}-{str(uuid.uuid4())[:4].upper()}"

        # Buat PO
        po_res = supabase.table("stock_purchases").insert({
            "purchase_number": po_number, "account_id": payload.account_id,
            "total_items_cost": total_items_cost, "shipping_cost": payload.shipping_cost,
            "grand_total": grand_total, "notes": payload.notes,
            "created_by": admin.get("admin_id")
        }).execute()
        po_id = po_res.data[0].get("id")

        # Proses Item & Inbound
        for item in payload.items:
            subtotal = item.quantity * item.capital_price_per_unit
            supabase.table("stock_purchase_items").insert({
                "purchase_id": po_id, "product_id": item.product_id,
                "item_name": item.item_name, "quantity": item.quantity,
                "capital_price_per_unit": item.capital_price_per_unit, "subtotal": subtotal
            }).execute()

            if item.product_id:
                res_prod = supabase.table("products").select("stock_quantity").eq("id", item.product_id).single().execute()
                if res_prod.data:
                    new_stock = int(res_prod.data.get("stock_quantity", 0)) + item.quantity
                    supabase.table("products").update({"stock_quantity": new_stock}).eq("id", item.product_id).execute()
                    
                    # LOG AUDIT: PURCHASE
                    supabase.table("stock_logs").insert({
                        "product_id": item.product_id,
                        "action": "IN",
                        "adjustment_amount": item.quantity,
                        "final_stock": new_stock,
                        "reason": f"Penerimaan barang dari dokumen {po_number}",
                        "reference_type": "PURCHASE",
                        "reference_id": po_id,
                        "status": "COMPLETED"
                    }).execute()

        # Potong Saldo & Mutasi Finance
        new_balance = current_balance - grand_total
        supabase.table("finance_accounts").update({"current_balance": new_balance}).eq("id", payload.account_id).execute()

        cat_res = supabase.table("finance_categories").select("id").ilike("category_name", "%belanja%").limit(1).execute()
        cat_id = cat_res.data[0].get("id") if cat_res.data else 1 

        supabase.table("finance_mutations").insert({
            "account_id": payload.account_id, "category_id": cat_id,
            "transaction_type": "OUT", "amount": grand_total,
            "balance_after": new_balance,
            "description": f"Pembayaran {po_number}. {payload.notes}",
            "reference_purchase_id": po_id, "created_by": admin.get("admin_id")
        }).execute()

        logger.info(f"🚚 [PROCUREMENT SUCCESS] PO {po_number} berhasil.")
        return api_success(message="Pengadaan berhasil diproses!", po_number=po_number)

    except Exception as e:
        logger.error(f"❌ [API PO ERROR]: {e}")
        return api_error(f"Sistem gagal memproses PO: {str(e)}", 500)


@router.post("/api/v1/stock/adjustment", tags=["API Inventory"])
async def api_process_stock_adjustment(payload: StockAdjustmentPayload, admin=Depends(get_current_admin)):
    """CORE ENGINE 2: MANUAL ADJUSTMENT -> Opname / Barang Rusak"""
    
    if admin.get("admin_role") not in ["super_admin", "oprasional"]:
        return api_error("Akses ditolak.", 403)
        
    if not supabase: return api_error("Database offline", 503)

    try:
        res_prod = supabase.table("products").select("stock_quantity, name").eq("id", payload.product_id).single().execute()
        if not res_prod.data: return api_error("Barang tidak valid.")
        
        current_stock = int(res_prod.data.get("stock_quantity", 0))
        product_name = res_prod.data.get("name")
        
        if payload.action == "OUT":
            if current_stock < payload.adjustment_amount:
                return api_error(f"Ditolak! Stok akhir tidak boleh minus. Sisa: {current_stock}")
            new_stock = current_stock - payload.adjustment_amount
        else:
            new_stock = current_stock + payload.adjustment_amount

        # Update Master
        supabase.table("products").update({"stock_quantity": new_stock}).eq("id", payload.product_id).execute()

        # LOG AUDIT: ADJUSTMENT
        admin_name = admin.get("admin_name", "Admin")
        supabase.table("stock_logs").insert({
            "product_id": payload.product_id,
            "action": payload.action,
            "adjustment_amount": payload.adjustment_amount,
            "final_stock": new_stock,
            "reason": f"[{admin_name}] {payload.reason}",
            "reference_type": "ADJUSTMENT",
            "status": "COMPLETED"
        }).execute()

        logger.info(f"📦 [ADJUSTMENT] {product_name}: {payload.action} {payload.adjustment_amount} unit.")
        return api_success(message=f"Penyesuaian stok {product_name} berhasil!")

    except Exception as e:
        logger.error(f"❌ [API ADJUSTMENT ERROR]: {e}")
        return api_error(str(e), 500)


# ==============================================================================
# 6. INTEGRATION ENGINES (UNTUK MODUL ORDER)
# ==============================================================================

@router.post("/api/v1/stock/order/reserve", tags=["API Inventory Integration"])
async def api_reserve_order_stock(payload: OrderReservePayload):
    """
    INTEGRASI: Dipanggil oleh sistem Order saat customer checkout.
    Fungsi: Memotong stok fisik agar tidak berebut, dan mencatat log PENDING.
    """
    if not supabase: return api_error("DB Offline", 503)

    try:
        for item in payload.items:
            prod_id = item.get("product_id")
            qty = item.get("quantity", 0)
            
            # Cek ketersediaan
            res = supabase.table("products").select("stock_quantity").eq("id", prod_id).single().execute()
            if not res.data or res.data["stock_quantity"] < qty:
                return api_error(f"Gagal reserve. Stok ID {prod_id} tidak mencukupi.")

            new_stock = res.data["stock_quantity"] - qty
            
            # Potong fisik langsung
            supabase.table("products").update({"stock_quantity": new_stock}).eq("id", prod_id).execute()
            
            # Log sebagai PENDING ORDER
            supabase.table("stock_logs").insert({
                "product_id": prod_id,
                "action": "OUT",
                "adjustment_amount": qty,
                "final_stock": new_stock,
                "reason": f"Sistem booking stok untuk Order ID: {payload.order_id}",
                "reference_type": "ORDER",
                "reference_id": payload.order_id,
                "status": "PENDING"
            }).execute()

        return api_success("Stok berhasil direservasi.")
    except Exception as e:
        logger.error(f"❌ [API RESERVE ERROR]: {e}")
        return api_error("Gagal melakukan reservasi stok.", 500)


@router.post("/api/v1/stock/order/resolve", tags=["API Inventory Integration"])
async def api_resolve_order_stock(payload: OrderResolvePayload):
    """
    INTEGRASI: Dipanggil saat order Selesai (Lunas) atau Dibatalkan.
    Jika CANCELLED -> Stok dikembalikan, log diubah ke CANCELLED.
    Jika COMPLETED -> Log PENDING berubah jadi COMPLETED.
    """
    if not supabase: return api_error("DB Offline", 503)

    try:
        # Cari log pending untuk order ini
        res_logs = supabase.table("stock_logs").select("*").eq("reference_id", payload.order_id).eq("status", "PENDING").execute()
        
        if not res_logs.data:
            return api_success("Tidak ada stok pending yang perlu di-resolve untuk order ini.")

        for log in res_logs.data:
            if payload.status == "CANCELLED":
                # Kembalikan stok fisik
                prod = supabase.table("products").select("stock_quantity").eq("id", log["product_id"]).single().execute()
                if prod.data:
                    restored_stock = prod.data["stock_quantity"] + log["adjustment_amount"]
                    supabase.table("products").update({"stock_quantity": restored_stock}).eq("id", log["product_id"]).execute()
                    
                    # Tandai log dibatalkan dan update final stock (meski history)
                    supabase.table("stock_logs").update({
                        "status": "CANCELLED",
                        "reason": f"[ORDER CANCELLED] Stok dikembalikan. {log['reason']}"
                    }).eq("id", log["id"]).execute()

            elif payload.status == "COMPLETED":
                # Selesaikan transaksi
                supabase.table("stock_logs").update({
                    "status": "COMPLETED",
                    "reason": f"[ORDER SUCCESS] {log['reason']}"
                }).eq("id", log["id"]).execute()

        return api_success(f"Status stok untuk order {payload.order_id} berhasil di-resolve menjadi {payload.status}.")
    except Exception as e:
        logger.error(f"❌ [API RESOLVE ERROR]: {e}")
        return api_error("Gagal resolve stok order.", 500)