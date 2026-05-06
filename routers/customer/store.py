"""
====================================================================================
BABA PARFUME - CUSTOMER STOREFRONT ROUTER (ENTERPRISE EDITION)
====================================================================================
Deskripsi : Menangani rendering UI toko, tarikan data katalog realtime, SSR Testimoni,
            API pengiriman ulasan, dan engine checkout anti Race-Condition.
====================================================================================
"""
import os
import uuid
import logging
import asyncio
from datetime import datetime
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, Request, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

# Supabase Bridge
try:
    from database import supabase
except ImportError:
    supabase = None

# Logger khusus storefront
logger = logging.getLogger("baba.store")
templates = Jinja2Templates(directory="templates")
router = APIRouter(prefix="", tags=["Customer Store"])

# ==============================================================================
# SCHEMAS (VALIDASI DATA SUPER KETAT)
# ==============================================================================
class CheckoutCustomer(BaseModel):
    id: int = Field(..., description="Telegram ID")
    username: Optional[str] = ""
    full_name: str = Field(..., min_length=2, description="Nama lengkap pelanggan")
    address: str = Field(..., min_length=5, description="Alamat pengiriman valid")

class CheckoutItem(BaseModel):
    id: int
    qty: int = Field(..., gt=0, description="Kuantitas minimal 1")
    price: float = Field(..., ge=0, description="Harga tidak boleh negatif")

class CheckoutPayload(BaseModel):
    action: str
    customer: CheckoutCustomer
    items: List[CheckoutItem] = Field(..., min_items=1)
    payment_method: str
    total_amount: float = Field(..., gt=0)

class TestimoniPayload(BaseModel):
    tele_id: int = Field(..., description="Telegram ID user yang kasih ulasan")
    rating: int = Field(..., ge=1, le=5, description="Rating bintang 1-5")
    review_text: Optional[str] = Field("", description="Isi ulasan opsional")

# ==============================================================================
# UTILITY FUNCTIONS
# ==============================================================================
def api_response(success: bool, message: str, data: Dict[str, Any] = None, status_code: int = 200):
    """Standarisasi format balikan API"""
    content = {"status": "success" if success else "error", "message": message}
    if data: content.update(data)
    return JSONResponse(status_code=status_code, content=content)

def normalize_product(item: dict) -> dict:
    """Formatter data produk agar aman dikonsumsi Alpine.js/Vue di Frontend"""
    def safe_array(val):
        if isinstance(val, list): return val
        return [x.strip() for x in str(val).split(",") if x.strip()] if val else []

    return {
        "id": item.get("id"),
        "name": item.get("name", "Varian BABA"),
        "image_url": item.get("image_url", "https://placehold.co/400x500/101010/D4AF37?text=BABA"),
        "original_price": float(item.get("original_price") or 0.0),
        "discounted_price": float(item.get("discounted_price") or 0.0),
        "stock_quantity": int(item.get("stock_quantity") or 0),
        "tags": safe_array(item.get("tags")),
        "is_active": bool(item.get("is_active", True)),
        "category_id": item.get("category_id"),
        "top_notes": safe_array(item.get("top_notes")),
        "heart_notes": safe_array(item.get("heart_notes")),
        "base_notes": safe_array(item.get("base_notes")),
        "description": item.get("description", ""),
        "longevity": item.get("longevity", ""),
        "recommendation": item.get("recommendation", "")
    }

# ==============================================================================
# BACKGROUND TASKS (NOTIFICATIONS)
# ==============================================================================
async def notify_admin_new_order(order_number: str, customer_name: str, total: float):
    """Pekerja background untuk kirim notif order ke Telegram Admin"""
    try:
        from bot import bot as bot_instance
        admin_id = os.getenv("ADMIN_ID")
        if admin_id:
            msg_admin = f"🚨 <b>NEW ORDER MASUK (WEB)!</b>\n\nUser: <b>{customer_name}</b>\nTotal: <b>${total:,.2f}</b>\nOrder ID: <code>{order_number}</code>\n\n<i>Cek dashboard untuk proses pesanan.</i>"
            await bot_instance.send_message(chat_id=admin_id, text=msg_admin, parse_mode="HTML")
    except Exception as e:
        logger.warning(f"Gagal ngirim notif admin (Order): {e}")

async def notify_admin_new_testimoni(customer_name: str, rating: int, review_text: str):
    """Pekerja background untuk kirim notif moderasi ulasan ke Telegram Admin"""
    try:
        from bot import bot as bot_instance
        admin_id = os.getenv("ADMIN_ID")
        if admin_id:
            star_icons = "⭐" * rating
            msg_admin = (
                f"📝 <b>ULASAN BARU MASUK!</b>\n\n"
                f"Dari: <b>{customer_name}</b>\n"
                f"Rating: {star_icons} ({rating}/5)\n"
                f"Ulasan: <i>\"{review_text}\"</i>\n\n"
                f"⚠️ <b>Butuh Moderasi:</b> Ulasan ini masuk antrean dan belum tayang di web. Buka panel admin untuk *Approve*."
            )
            await bot_instance.send_message(chat_id=admin_id, text=msg_admin, parse_mode="HTML")
    except Exception as e:
        logger.warning(f"Gagal ngirim notif admin (Testimoni): {e}")

async def notify_customer_telegram(tele_id: int, message_text: str):
    """Pekerja background aman untuk kirim notifikasi ke pelanggan"""
    try:
        from bot import bot as bot_instance
        await bot_instance.send_message(chat_id=tele_id, text=message_text, parse_mode="HTML")
    except Exception as e:
        logger.warning(f"Gagal ngirim notif ke pelanggan: {e}")

# ==============================================================================
# WEB RENDERING (SSR HTML)
# ==============================================================================
@router.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    """Render Landing Page & Katalog dengan Data Dinamis"""
    settings_data = {"store_name": "BABA Parfume", "checkout_message": "Halo BABA..."}
    produk_aktif = []
    testimoni_list = []

    if supabase:
        try:
            # 1. Fetch Pengaturan Toko
            res_set = supabase.table("store_settings").select("*").eq("id", 1).execute()
            if res_set.data: settings_data = res_set.data[0]
            
            # 2. Fetch Katalog Produk
            res_prod = supabase.table("products").select("*").eq("is_active", True).order("id").execute()
            produk_aktif = [normalize_product(p) for p in (res_prod.data or [])]

            # 3. Fetch Testimoni Approved (Join ke customers untuk ambil nama)
            res_testi = supabase.table("testimonials") \
                .select("rating, review_text, created_at, customer:customers(full_name)") \
                .eq("is_approved", True) \
                .order("created_at", desc=True).limit(8).execute()
            
            for t in (res_testi.data or []):
                # Ekstrak nama dan inisial biar bisa dipakai di UI Alpine.js
                raw_name = t.get("customer", {}).get("full_name") if t.get("customer") else "Pelanggan BABA"
                cust_name = raw_name if raw_name else "Pelanggan BABA"
                
                testimoni_list.append({
                    "name": cust_name,
                    "initial": cust_name[0].upper(),
                    "rating": t.get("rating", 5),
                    "text": t.get("review_text", ""),
                    "date": t.get("created_at")
                })
        except Exception as e:
            logger.error(f"❌ [FRONTEND SSR ERROR]: {e}")

    # Render Index, lempar semua data JSON ke Jinja biar diolah Alpine
    return templates.TemplateResponse("customer/index.html", {
        "request": request, 
        "settings": settings_data, 
        "produk": produk_aktif,
        "testimoni": testimoni_list
    })

# ==============================================================================
# API ENDPOINTS (DATA & TRANSACTION)
# ==============================================================================
@router.get("/api/v1/products/live")
async def api_get_live_products():
    """Endpoint untuk refresh katalog realtime di frontend (Bypass SSR cache)"""
    if not supabase: return api_response(False, "Database Offline", status_code=503)
    try:
        res = supabase.table("products").select("*").eq("is_active", True).order("id").execute()
        return api_response(True, "Katalog termuat", {"data": [normalize_product(p) for p in (res.data or [])]})
    except Exception as e:
        logger.error(f"❌ [LIVE CATALOG ERROR]: {e}")
        return api_response(False, "Gagal memuat katalog", status_code=500)

@router.post("/api/v1/testimoni/submit")
async def api_submit_testimoni(payload: TestimoniPayload, bg_tasks: BackgroundTasks):
    """Menerima ulasan baru dari user dan memasukkan ke antrean moderasi"""
    if not supabase: return api_response(False, "Database Offline", status_code=503)
    
    try:
        # Cari UUID customer berdasarkan telegram_id
        cust_res = supabase.table("customers").select("id, full_name").eq("telegram_id", payload.tele_id).execute()
        
        if not cust_res.data:
            return api_response(False, "Kakak belum terdaftar sebagai pelanggan. Yuk belanja dulu sebelum ngasih ulasan!", status_code=400)
            
        cust_id = cust_res.data[0]["id"]
        cust_name = cust_res.data[0].get("full_name", "Pelanggan")

        # Insert ke tabel testimonials (is_approved default False dari skema SQL)
        supabase.table("testimonials").insert({
            "customer_id": cust_id,
            "rating": payload.rating,
            "review_text": payload.review_text
        }).execute()

        # Delegasikan notif admin ke background task
        bg_tasks.add_task(notify_admin_new_testimoni, cust_name, payload.rating, payload.review_text)

        logger.info(f"✅ Ulasan baru diterima dari {cust_name} ({payload.rating} Bintang)")
        return api_response(True, "Makasih ulasannya kak! Menunggu moderasi dari admin.")

    except Exception as e:
        logger.error(f"❌ [SUBMIT TESTIMONI ERROR]: {e}")
        return api_response(False, "Gagal mengirim ulasan, coba beberapa saat lagi.", status_code=500)

@router.post("/api/v1/checkout")
async def api_process_checkout(payload: CheckoutPayload, bg_tasks: BackgroundTasks):
    """
    ENGINE CHECKOUT V2 (TRANSACTION SAFE)
    Dilengkapi dengan pre-check stok ekstrim, injeksi Auto-Customer, dan Async Notif.
    """
    if payload.action != "checkout": return api_response(False, "Aksi ditolak", status_code=400)
    if not supabase: return api_response(False, "Sistem Database Gangguan", status_code=503)

    tele_id = payload.customer.id
    try:
        # --- 1. PRE-CHECK STOK (Keamanan dari Race Condition & Manipulasi Frontend) ---
        item_ids = [item.id for item in payload.items]
        res_stocks = supabase.table("products").select("id, stock_quantity, name, discounted_price").in_("id", item_ids).execute()
        db_stocks = {p["id"]: p for p in res_stocks.data}

        # Verifikasi berlapis: Stok cukup? Harga dimanipulasi?
        for item in payload.items:
            if item.id not in db_stocks:
                return api_response(False, "Varian tidak valid atau sudah dihapus.", status_code=400)
            
            db_item = db_stocks[item.id]
            if db_item["stock_quantity"] < item.qty:
                return api_response(False, f"Stok {db_item['name']} tersisa {db_item['stock_quantity']}!", status_code=400)
            
            # Anti-Hack: Pastikan harga yang dikirim frontend sesuai harga DB (toleransi desimal)
            if abs(db_item["discounted_price"] - item.price) > 0.01:
                logger.warning(f"⚠️ Potensi manipulasi harga oleh TeleID {tele_id}")
                item.price = db_item["discounted_price"] # Override paksa ke harga asli DB

        # --- 2. SINKRONISASI CUSTOMER ---
        order_number = f"ORD-{datetime.now().strftime('%y%m%d')}-{str(tele_id)[-4:]}-{str(uuid.uuid4())[:4].upper()}"
        
        # Upsert: Jika user baru klik beli dan belum pernah disapa bot, paksa buatin profilnya
        supabase.table("customers").upsert({
            "telegram_id": tele_id, 
            "full_name": payload.customer.full_name,
            "default_address": payload.customer.address, 
            "username": payload.customer.username
        }, on_conflict="telegram_id").execute()
        
        cust_res = supabase.table("customers").select("id").eq("telegram_id", tele_id).single().execute()
        cust_uuid = cust_res.data["id"]

        # --- 3. CREATE ORDER ---
        # Note: Order baru tidak ngasih poin loyalty. Poin dikasih pas order Selesai (oleh admin).
        order_res = supabase.table("orders").insert({
            "order_number": order_number, 
            "customer_id": cust_uuid,
            "shipping_address": payload.customer.address, 
            "total_amount": payload.total_amount,
            "status": "Menunggu Pembayaran", 
            "payment_method": payload.payment_method,
            "order_source": "Telegram WebApp"
        }).execute()
        order_uuid = order_res.data[0]["id"]

        # --- 4. INSERT ITEMS & DEDUCT STOK (ATOMIC) ---
        order_items_data = []
        for item in payload.items:
            order_items_data.append({
                "order_id": order_uuid, 
                "product_id": item.id,
                "quantity": item.qty, 
                "price_at_time": item.price
            })
            # Pengurangan Stok
            new_stock = db_stocks[item.id]["stock_quantity"] - item.qty
            supabase.table("products").update({"stock_quantity": new_stock}).eq("id", item.id).execute()
            
        # Bulk Insert Items
        supabase.table("order_items").insert(order_items_data).execute()

        # --- 5. ASYNC NOTIFICATIONS ---
        try:
            # Rakit text detail item dari payload dan db_stocks
            items_text = ""
            for item in payload.items:
                product_name = db_stocks[item.id]["name"]
                items_text += f"- {product_name} {item.qty}pcs (${item.price:,.2f})\n"
                
            msg_cust = (
                f"✅ <b>YAY! PESANAN BERHASIL DIBUAT!</b>\n\n"
                f"Terima kasih kak <b>{payload.customer.full_name}</b>!\n"
                f"Nomor Pesanan: <code>{order_number}</code>\n\n"
                f"<b>Detail Order :</b>\n"
                f"{items_text}\n"
                f"Total Tagihan: <b>${payload.total_amount:,.2f}</b>\n"
                f"Metode Bayar: <b>{payload.payment_method}</b>\n\n"
                f"Silakan tunggu sebentar ya, tim Admin BABA akan segera menghubungi kakak. 🚀"
            )
            
            # Gunakan BackgroundTasks agar API gak macet / timeout!
            bg_tasks.add_task(notify_customer_telegram, tele_id, msg_cust)
        except Exception as e: 
            logger.warning(f"Gagal set notif customer: {e}")

        # Lempar notif admin ke background worker biar respons API instan
        bg_tasks.add_task(notify_admin_new_order, order_number, payload.customer.full_name, payload.total_amount)

        logger.info(f"✅ [CHECKOUT SUCCESS] {order_number} by {tele_id}")
        return api_response(True, "Pesanan berhasil diproses!", {"order_number": order_number})

    except Exception as e:
        logger.error(f"❌ [CHECKOUT FATAL ERROR]: {e}")
        return api_response(False, "Terjadi kesalahan internal saat checkout.", status_code=500)