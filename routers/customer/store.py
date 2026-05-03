"""
====================================================================================
BABA PARFUME - CUSTOMER STOREFRONT ROUTER (ENTERPRISE EDITION)
====================================================================================
Deskripsi : Menangani semua lalu lintas data dari pelanggan (Frontend Web App).
            Termasuk rendering HTML, penarikan katalog realtime, sistem checkout 
            otomatis (potong stok & notif bot), dan integrasi AI Mimin.
Arsitektur: FastAPI Router + Pydantic Validation + Supabase ORM
====================================================================================
"""

import uuid
import logging
import asyncio
from datetime import datetime
from typing import Optional, List

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

# Import modul internal BABA
from database import supabase
from ai_agent import get_ai_recommendation

# Setup Logger khusus Store
logger = logging.getLogger("baba.store")
templates = Jinja2Templates(directory="templates")

# Inisiasi Router Utama
router = APIRouter(tags=["Customer Front End"])

# ==============================================================================
# 1. PYDANTIC SCHEMAS (TAMENG KEAMANAN ANTI-INJECTION)
# ==============================================================================
# Skema ini memastikan data yang dikirim dari index.html sesuai format (Gak bisa di-hack)
class CheckoutCustomer(BaseModel):
    id: int
    username: Optional[str] = ""
    first_name: Optional[str] = ""
    full_name: str = Field(..., min_length=1)
    address: str = Field(..., min_length=5)

class CheckoutItem(BaseModel):
    id: int
    name: str
    qty: int = Field(..., gt=0)
    price: float = Field(..., ge=0)

class CheckoutPayload(BaseModel):
    action: str
    customer: CheckoutCustomer
    items: List[CheckoutItem]
    payment_method: str
    total_amount: float = Field(..., ge=0)

class ChatSendPayload(BaseModel):
    tele_id: int
    message: str

class ChatResetPayload(BaseModel):
    tele_id: int

class ChatFeedbackPayload(BaseModel):
    tele_id: int
    rating: int = Field(ge=1, le=5)
    complaint: Optional[str] = ""

# ==============================================================================
# 2. UTILITY & HELPER FUNCTIONS
# ==============================================================================
def api_success(**payload):
    return {"status": "success", **payload}

def api_error(message: str, status_code: int = 400, **payload):
    return JSONResponse(status_code=status_code, content={"status": "error", "message": message, **payload})

def safe_array(value) -> list:
    """Mengamankan format array dari database"""
    if isinstance(value, list): return value
    if isinstance(value, str): 
        return [x.strip() for x in value.split(",") if x.strip()]
    return []

def normalize_product(item: dict) -> dict:
    """Format standar produk untuk dikonsumsi Vue/Alpine.js di Frontend"""
    return {
        "id": item.get("id"),
        "category_id": item.get("category_id"),
        "name": item.get("name") or "Tanpa Nama",
        "tagline": item.get("tagline") or "-",
        "description": item.get("description") or "",
        "image_url": item.get("image_url") or "https://placehold.co/400x500/101010/D4AF37?text=BABA",
        "original_price": float(item.get("original_price") or 0.0),
        "discounted_price": float(item.get("discounted_price") or 0.0),
        "stock_quantity": int(item.get("stock_quantity") or 0),
        "tags": safe_array(item.get("tags")),
        "top_notes": safe_array(item.get("top_notes")),
        "heart_notes": safe_array(item.get("heart_notes")),
        "base_notes": safe_array(item.get("base_notes")),
        "longevity": item.get("longevity") or "8-12 Jam",
        "recommendation": item.get("recommendation") or "All Day",
        "is_active": bool(item.get("is_active", True))
    }

# ==============================================================================
# 3. CORE WEB RENDERING (HTML PAGES)
# ==============================================================================
@router.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    """Pintu Masuk Utama: Landing Page & Toko BABA"""
    settings_data = {
        "store_name": "BABA Parfume", 
        "admin_whatsapp": "", 
        "checkout_message": "Halo BABA Parfume, saya mau pesan..."
    }
    produk_aktif = []

    if supabase:
        try:
            res_set = supabase.table("store_settings").select("*").eq("id", 1).single().execute()
            if res_set.data: settings_data = res_set.data
            
            res_prod = supabase.table("products").select("*").eq("is_active", True).order("id").execute()
            produk_aktif = [normalize_product(p) for p in (res_prod.data or [])]
        except Exception as e:
            logger.error(f"❌ [FRONTEND SSR] Gagal meload data: {e}")

    return templates.TemplateResponse(request=request, name="customer/index.html", context={
        "request": request, "settings": settings_data, "produk": produk_aktif
    })

@router.get("/profile", response_class=HTMLResponse)
async def customer_profile_page(request: Request, tele_id: Optional[int] = None):
    """Halaman Profil & Gamifikasi Pelanggan"""
    if not supabase: return HTMLResponse("Database Offline", status_code=503)

    cust_data = None
    stats = {"total_orders": 0, "total_bottles": 0, "favorite_tags": []}
    history_orders = []

    if tele_id:
        try:
            res_cust = supabase.table("customers").select("*").eq("telegram_id", tele_id).single().execute()
            if res_cust.data:
                cust_data = res_cust.data
                cust_uuid = cust_data.get("id")

                res_orders = supabase.table("orders").select("id, order_number, status, created_at").eq("customer_id", cust_uuid).order("created_at", desc=True).execute()
                raw_orders = res_orders.data or []
                stats["total_orders"] = len(raw_orders)

                if raw_orders:
                    order_ids = [o["id"] for o in raw_orders]
                    res_items = supabase.table("order_items").select("order_id, quantity, products(name, image_url, tags)").in_("order_id", order_ids).execute()
                    all_items = res_items.data or []
                    
                    tag_counter = {}
                    for order in raw_orders:
                        order["items"] = []
                        for item in all_items:
                            if item["order_id"] == order["id"]:
                                qty = item["quantity"]
                                prod = item.get("products") or {}
                                order["items"].append({
                                    "name": prod.get("name", "Varian BABA"),
                                    "image_url": prod.get("image_url", ""),
                                    "qty": qty
                                })
                                stats["total_bottles"] += qty
                                for tag in safe_array(prod.get("tags")):
                                    t_up = tag.upper().strip()
                                    tag_counter[t_up] = tag_counter.get(t_up, 0) + qty

                    history_orders = raw_orders
                    if tag_counter:
                        sorted_tags = sorted(tag_counter.items(), key=lambda x: x[1], reverse=True)
                        stats["favorite_tags"] = [t[0] for t in sorted_tags[:3]]

        except Exception as e:
            logger.error(f"❌ [PROFILE FETCH ERROR]: {e}")

    return templates.TemplateResponse("customer/profile.html", {
        "request": request, "customer": cust_data, "stats": stats, "orders": history_orders
    })

@router.get("/cs", response_class=HTMLResponse)
async def chat_ai_page(request: Request):
    """Halaman Ruang Chat AI Mimin"""
    return templates.TemplateResponse(request=request, name="customer/cs.html", context={"request": request})

# ==============================================================================
# 4. EXTERNAL API LOGIC (LIVE CATALOG & THE CHECKOUT ENGINE)
# ==============================================================================
@router.get("/api/v1/products/live")
async def api_get_live_products():
    """Supply data katalog realtime ke Frontend Alpine.js"""
    if not supabase: return api_error("Database offline", 503)
    try:
        res = supabase.table("products").select("*").eq("is_active", True).order("id").execute()
        return api_success(data=[normalize_product(p) for p in (res.data or [])])
    except Exception as e:
        logger.error(f"❌ [LIVE CATALOG ERROR]: {e}")
        return api_error(str(e), 500)

@router.post("/api/v1/checkout")
async def api_process_checkout(payload: CheckoutPayload):
    """
    ENGINE CHECKOUT BABA:
    1. Validasi Payload
    2. Simpan Data Pelanggan
    3. Simpan Pesanan (Orders & Items)
    4. Kurangi Stok Barang
    5. Kirim Notif Telegram (User & Admin)
    """
    try:
        if payload.action != "checkout":
            return api_error("Action tidak valid", 400)
            
        if not supabase:
            return api_error("Sistem Database sedang gangguan", 503)

        tele_id = payload.customer.id
        full_name = payload.customer.full_name
        address = payload.customer.address
        total_amount = payload.total_amount
        payment_method = payload.payment_method

        # 1. Generate Order Number Unik (Ciri khas Enterprise)
        order_number = f"ORD-{datetime.now().strftime('%y%m%d')}-{str(tele_id)[-4:]}-{str(uuid.uuid4())[:4].upper()}"

        # 2. Sinkronisasi Data Customer
        supabase.table("customers").upsert({
            "telegram_id": tele_id,
            "full_name": full_name,
            "default_address": address,
            "username": payload.customer.username
        }, on_conflict="telegram_id").execute()

        cust_db = supabase.table("customers").select("id").eq("telegram_id", tele_id).single().execute()
        cust_uuid = cust_db.data.get("id")

        # 3. Rekam Pesanan Induk
        order_res = supabase.table("orders").insert({
            "order_number": order_number,
            "customer_id": cust_uuid,
            "shipping_address": address,
            "total_amount": total_amount,
            "status": "Menunggu Pembayaran",
            "order_source": "Telegram WebApp",
            "payment_method": payment_method
        }).execute()
        
        order_uuid = order_res.data[0].get("id")

        # 4. Rekam Detail Item & Potong Stok Fisik
        for item in payload.items:
            # Insert item pesanan
            supabase.table("order_items").insert({
                "order_id": order_uuid,
                "product_id": item.id,
                "quantity": item.qty,
                "price_at_time": item.price
            }).execute()

            # Potong Stok Realtime
            prod_data = supabase.table("products").select("stock_quantity").eq("id", item.id).single().execute()
            if prod_data.data:
                current_stock = prod_data.data.get("stock_quantity", 0)
                new_stock = max(0, current_stock - item.qty) # Gak boleh minus
                supabase.table("products").update({"stock_quantity": new_stock}).eq("id", item.id).execute()

        # 5. Notifikasi Bot Asynchronous (Biar loading web gak lama nungguin Telegram)
        try:
            from bot import bot as bot_instance
            import os
            
            # Notif ke Customer
            struk_cust = (
                f"✅ <b>YAY! PESANAN BERHASIL DIBUAT!</b>\n\n"
                f"Terima kasih kak <b>{full_name}</b>!\n"
                f"No. Pesanan: <code>{order_number}</code>\n"
                f"Total Tagihan: <b>${total_amount:,.2f}</b>\n"
                f"Pembayaran: <b>{payment_method}</b>\n\n"
                f"<i>Silakan tunggu sebentar ya, Admin BABA akan segera ngehubungin kakak buat konfirmasi.</i> 🚀"
            )
            asyncio.create_task(bot_instance.send_message(chat_id=tele_id, text=struk_cust, parse_mode="HTML"))
            
            # Notif ke Admin Dika
            admin_id = os.getenv("ADMIN_ID")
            if admin_id:
                alert_admin = (
                    f"🚨 <b>BOS ADA ORDERAN MASUK VIA WEB!</b> 🚨\n\n"
                    f"Customer: {full_name}\n"
                    f"Nilai: <b>${total_amount:,.2f}</b> ({payment_method})\n"
                    f"Order ID: <code>{order_number}</code>\n\n"
                    f"👉 Cek Dashboard Admin sekarang!"
                )
                asyncio.create_task(bot_instance.send_message(chat_id=admin_id, text=alert_admin, parse_mode="HTML"))
        except Exception as bot_err:
            logger.warning(f"⚠️ [NOTIF BOT] Gagal mengirim pesan otomatis: {bot_err}")

        logger.info(f"✅ [CHECKOUT SUCCESS] Order {order_number} dibuat oleh {full_name} (ID:{tele_id})")
        return api_success(order_number=order_number, message="Pesanan sedang diproses!")

    except Exception as e:
        logger.error(f"❌ [CHECKOUT FATAL ERROR]: {e}")
        return api_error(f"Gagal memproses checkout: {str(e)}", 500)

# ==============================================================================
# 5. AI CHATBOT API (INTEGRASI MIMIN)
# ==============================================================================
@router.get("/api/v1/chat/history")
async def get_chat_history(tele_id: int):
    """Menarik ingatan percakapan sebelumnya"""
    try:
        if not supabase: return api_success(history=[])
        res_sess = supabase.table("ai_chat_sessions").select("id").eq("telegram_id", tele_id).eq("is_active", True).execute()
        if not res_sess.data: return api_success(history=[])
            
        sid = res_sess.data[0]['id']
        res_msg = supabase.table("ai_chat_messages").select("role, content").eq("session_id", sid).order("created_at", desc=False).execute()
        return api_success(history=res_msg.data or [])
    except Exception as e:
        logger.warning(f"⚠️ Error memuat history AI: {e}")
        return api_success(history=[])

@router.post("/api/v1/chat/send")
async def chat_ai_send(payload: ChatSendPayload):
    """Otak Utama: Lempar pesan ke Gemini dan kembalikan ke Frontend"""
    if not payload.message.strip():
        return api_error("Pesan kosong tidak bisa diproses", 400)
    try:
        ai_reply = await get_ai_recommendation(payload.tele_id, payload.message)
        return api_success(reply=ai_reply)
    except Exception as e:
        logger.error(f"❌ [AI GENERATION ERROR]: {e}")
        return api_error("Mimin lagi pusing, server kepenuhan kak!", 500)

@router.post("/api/v1/chat/reset")
async def chat_reset(payload: ChatResetPayload):
    """Tombol Hapus Memori Mimin"""
    try:
        if supabase:
            supabase.table("ai_chat_sessions").update({"is_active": False}).eq("telegram_id", payload.tele_id).execute()
        logger.info(f"🧹 Sesi chat ID:{payload.tele_id} berhasil dibersihkan.")
        return api_success(message="Sesi berhasil direstart")
    except Exception as e:
        logger.error(f"❌ [AI RESET ERROR]: {e}")
        return api_error("Gagal mereset sesi", 500)

@router.post("/api/v1/chat/feedback")
async def submit_ai_feedback(payload: ChatFeedbackPayload):
    """Tampung rating user buat evaluasi mesin LLM"""
    try:
        if supabase:
            supabase.table("ai_feedbacks").insert({
                "telegram_id": payload.tele_id,
                "rating": payload.rating,
                "complaint": payload.complaint
            }).execute()
            logger.info(f"🌟 [AI FEEDBACK] ID:{payload.tele_id} memberi Bintang {payload.rating}")
        return api_success(message="Makasih ya kak feedback-nya!")
    except Exception as e:
        logger.error(f"❌ [AI FEEDBACK ERROR]: {e}")
        return api_error(str(e), 500)
