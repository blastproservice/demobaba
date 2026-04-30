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
@router.get("/", response_class=HTMLResponse,tags=["Web Customer"])
async def read_root(request: Request):
    """Endpoint Utama: Menampilkan Katalog Belanja ke Customer"""
    settings_data = {
        "store_name": "BABA Parfume", 
        "admin_whatsapp": "", 
        "checkout_message": "Halo BABA Parfume, saya mau pesan..."
    }
    produk_aktif = []

    if supabase:
        try:
            # Mengambil pengaturan toko global
            res_set = supabase.table("store_settings").select("*").eq("id", 1).single().execute()
            if res_set.data: 
                settings_data = res_set.data
            
            # Mengambil produk yang siap jual (is_active = true)
            res_prod = supabase.table("products").select("*").eq("is_active", True).order("id").execute()
            produk_aktif = [normalize_product(p) for p in (res_prod.data or [])]
            
        except Exception as e:
            logger.error(f"❌ [FRONTEND] Gagal meload data awal: {e}")

    return templates.TemplateResponse(request=request, name="customer/index.html", context={
        "request": request, 
        "settings": settings_data, 
        "produk": produk_aktif
    })


@router.get("/profile", response_class=HTMLResponse,tags=["Web Customer"])
async def customer_profile_page(request: Request, tele_id: Optional[int] = None):
    """
    Halaman Profil Customer: Menampilkan statistik koleksi botol & profil aroma.
    Tanpa nominal uang, fokus ke kebanggaan koleksi (Gamifikasi).
    """
    if not supabase:
        raise HTTPException(status_code=503, detail="Database sedang offline bre!")

    # 1. Default Data (Jika user belum terdaftar atau tele_id ga ada)
    cust_data = None
    stats = {
        "total_orders": 0,
        "total_bottles": 0,
        "favorite_tags": []
    }
    history_orders = []

    if tele_id:
        try:
            # 2. Ambil Data Dasar Customer
            res_cust = supabase.table("customers").select("*").eq("telegram_id", tele_id).single().execute()
            
            if res_cust.data:
                cust_data = res_cust.data
                cust_uuid = cust_data.get("id")

                # 3. Tarik Riwayat Pesanan (Urutkan dari yang terbaru)
                # Kita cuma butuh ID, Nomor, Status, dan Tanggal. Duitnya kita cuekin!
                res_orders = supabase.table("orders").select(
                    "id, order_number, status, created_at"
                ).eq("customer_id", cust_uuid).order("created_at", desc=True).execute()
                
                raw_orders = res_orders.data or []
                stats["total_orders"] = len(raw_orders)

                if raw_orders:
                    # Ambil semua order_id buat narik detail item sekaligus (Bulk Select)
                    order_ids = [o["id"] for o in raw_orders]
                    
                    # 4. Tarik Detail Item & Join ke Produk buat ambil Tags (buat AI Profiling)
                    res_items = supabase.table("order_items").select(
                        "order_id, quantity, products(name, image_url, tags)"
                    ).in_("order_id", order_ids).execute()
                    
                    all_items = res_items.data or []
                    
                    # 5. Logic God Mode: Hitung Total Botol & Analisis Aroma Favorit
                    tag_counter = {}
                    
                    for order in raw_orders:
                        order["items"] = []
                        for item in all_items:
                            if item["order_id"] == order["id"]:
                                qty = item["quantity"]
                                prod = item.get("products") or {}
                                
                                # Tambahin rincian barang ke list pesanan
                                order["items"].append({
                                    "name": prod.get("name", "Varian BABA"),
                                    "image_url": prod.get("image_url", ""),
                                    "qty": qty
                                })
                                
                                # Update Statistik Koleksi (Pride Meter)
                                stats["total_bottles"] += qty
                                
                                # Scan Tags buat pembelajaran AI / Profil Selera
                                p_tags = safe_array(prod.get("tags"))
                                for tag in p_tags:
                                    t_up = tag.upper().strip()
                                    tag_counter[t_up] = tag_counter.get(t_up, 0) + qty

                    history_orders = raw_orders
                    
                    # 6. Ambil 3 Aroma Teratas (Signature Style si User)
                    if tag_counter:
                        # Sortir dari yang paling banyak dibeli
                        sorted_tags = sorted(tag_counter.items(), key=lambda x: x[1], reverse=True)
                        stats["favorite_tags"] = [t[0] for t in sorted_tags[:3]]

            logger.info(f"👤 [PROFILE] User ID:{tele_id} mengintip koleksi ({stats['total_bottles']} botol).")

        except Exception as e:
            logger.error(f"❌ [PROFILE FETCH ERROR]: {e}")
            # Kita biarin tetep render pake data default biar gak crash putih layarnya

    return templates.TemplateResponse("customer/profile.html", {
        "request": request,
        "customer": cust_data,
        "stats": stats,
        "orders": history_orders
    })

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

# ==============================================================================
# ROUTER 2: CUSTOMER AI AGENT (CS ENGINE)
# ==============================================================================
@router.get("/cs", response_class=HTMLResponse, tags=["Web Customer"])
async def chat_ai_page(request: Request):
    """Menampilkan antarmuka obrolan Mimin AI"""
    return templates.TemplateResponse(request=request, name="customer/cs.html", context={"request": request})

@router.get("/api/v1/chat/history", tags=["API AI"])
async def get_chat_history(tele_id: int):
    """Memanggil kembali memori percakapan user dari database"""
    try:
        if not supabase: return api_success(history=[])
        res_sess = supabase.table("ai_chat_sessions").select("id").eq("telegram_id", tele_id).eq("is_active", True).execute()
        if not res_sess.data:
            return api_success(history=[])
            
        sid = res_sess.data[0]['id']
        res_msg = supabase.table("ai_chat_messages").select("role, content").eq("session_id", sid).order("created_at", desc=False).execute()
        return api_success(history=res_msg.data or [])
    except Exception as e:
        logger.warning(f"Error memuat history AI: {e}")
        return api_success(history=[])

@router.post("/api/v1/chat/send", tags=["API AI"])
async def chat_ai_send(payload: ChatSendPayload):
    """Menerima pesan dari user, memproses via Google GenAI, dan mengembalikan jawaban"""
    if not payload.message.strip():
        return api_error("Pesan kosong tidak bisa diproses", 400)

    try:
        # get_ai_recommendation dipanggil dari ai_agent.py lu
        ai_reply = await get_ai_recommendation(payload.tele_id, payload.message)
        return api_success(reply=ai_reply)
    except Exception as e:
        logger.error(f"❌ [AI GENERATION ERROR]: {e}")
        return api_error("Sistem AI sedang kelebihan beban", 500)

@router.post("/api/v1/chat/reset", tags=["API AI"])
async def chat_reset(payload: ChatResetPayload):
    """Menonaktifkan memori sesi AI (ketika user klik Mulai Baru)"""
    try:
        if supabase:
            supabase.table("ai_chat_sessions").update({"is_active": False}).eq("telegram_id", payload.tele_id).execute()
        logger.info(f"Sesi chat ID:{payload.tele_id} telah direset.")
        return api_success(message="Sesi berhasil direstart")
    except Exception as e:
        logger.error(f"❌ [AI RESET ERROR]: {e}")
        return api_error("Gagal mereset sesi", status_code=500)

@router.post("/api/v1/chat/feedback", tags=["API AI"])
async def submit_ai_feedback(payload: ChatFeedbackPayload):
    """Menyimpan Rating Bintang dan Keluhan untuk melatih ulang AI"""
    try:
        if supabase:
            supabase.table("ai_feedbacks").insert({
                "telegram_id": payload.tele_id,
                "rating": payload.rating,
                "complaint": payload.complaint
            }).execute()
            logger.info(f"🌟 [AI FEEDBACK] ID:{payload.tele_id} memberi Bintang {payload.rating}")
        return api_success(message="Feedback disimpan!")
    except Exception as e:
        logger.error(f"❌ [AI FEEDBACK ERROR]: {e}")
        return api_error(str(e), status_code=500)
