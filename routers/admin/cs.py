from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

# 1. Import Brankas Supabase
try:
    from database import supabase
except ImportError:
    print("❌ [SYSTEM] File database.py tidak ditemukan!")
    supabase = None

# 2. Import Mesin Bot Telegram (PENTING: Buat tembak pesan manual)
try:
    from bot import bot
except ImportError:
    bot = None

# Inisiasi Router khusus CS AI
router = APIRouter(tags=["Admin CS AI"])
templates = Jinja2Templates(directory="templates")

# ==============================================================================
# DATA MODELS (Pengaman Tipe Data dari Frontend)
# ==============================================================================
class ManualMessagePayload(BaseModel):
    session_id: int
    tele_id: int
    message: str

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
@router.get("/admin/cs", response_class=HTMLResponse)
async def admin_cs_dashboard(request: Request):
    return templates.TemplateResponse("admin/cs_management.html", {
        "request": request,
        "pending_count": get_pending_count()
    })

# ==============================================================================
# JALUR API JSON (Penyedot Data untuk Alpine.js)
# ==============================================================================
@router.get("/api/v1/admin/cs/sessions", tags=["API Admin CRM"], dependencies=[require_admin_roles("super_admin", "marketing", "cs")])
async def api_admin_get_sessions():
    """Mengambil daftar list obrolan yang sedang aktif/riwayat"""
    try:
        if not supabase: return api_success(sessions=[])
        
        # 1. Tarik data sesi (TANPA JOIN LANGSUNG KARENA GA ADA FK DI DB)
        res_sess = supabase.table("ai_chat_sessions").select("*").order("created_at", desc=True).execute()
        sessions = res_sess.data or []
        
        # 2. Kalau ada sesi, tarik data customer manual trus gabungin
        if sessions:
            tele_ids = list(set([s["telegram_id"] for s in sessions]))
            # Tarik nama pelanggan berdasarkan telegram_id yang lagi nge-chat
            res_cust = supabase.table("customers").select("telegram_id, full_name, username").in_("telegram_id", tele_ids).execute()
            
            # Bikin kamus (map) buat nyocokin data
            cust_map = {c["telegram_id"]: {"full_name": c.get("full_name"), "username": c.get("username")} for c in (res_cust.data or [])}
            
            # Tempelin nama customer ke masing-masing sesi chat
            for s in sessions:
                s["customers"] = cust_map.get(s["telegram_id"], {"full_name": "Pelanggan Baru", "username": "Anonymous"})
                
        return api_success(sessions=sessions)
        
    except Exception as e:
        logger.error(f"❌ [CS SESSIONS ERROR]: {e}")
        return api_error(str(e), status_code=500)

# ==============================================================================
# JALUR EKSEKUSI (Kirim Pesan Manual & Intercept AI)
# ==============================================================================
@router.post("/api/v1/admin/cs/send-manual", tags=["API Admin CRM"], dependencies=[require_admin_roles("super_admin", "marketing", "cs")])
async def api_admin_send_manual(payload: AdminManualChatPayload):
    """Fungsi pengambilalihan kendali: Lu (Admin) balas chat user secara paksa"""
    try:
        if not supabase:
            return api_error("Database chat belum terhubung", status_code=503)

        # 1. Simpan sbg log admin
        supabase.table("ai_chat_messages").insert({
            "session_id": payload.session_id, 
            "role": "admin", 
            "content": payload.message
        }).execute()

        # 2. Tembak ke Bot
        if BOT_AVAILABLE:
            from bot import bot as bot_instance
            await bot_instance.send_message(chat_id=payload.tele_id, text=f"👨‍💻 <b>Admin BABA:</b>\n{payload.message}", parse_mode="HTML")
        
        logger.info(f"🗣️ [MANUAL CHAT] Admin membalas ID:{payload.tele_id}")
        return api_success(message="Pesan terkirim!")
    except Exception as e:
        logger.error(f"❌ [MANUAL CHAT ERROR]: {e}")
        return api_error("Gagal mengirim pesan manual", status_code=500)

@router.post("/api/v1/admin/cs/messages", tags=["API Admin CRM"], dependencies=[require_admin_roles("super_admin", "marketing", "cs")])
async def api_admin_get_messages(session_id: int):
    """Intip isi percakapan satu sesi tertentu"""
    try:
        if not supabase: return api_success(messages=[])
        res = supabase.table("ai_chat_messages").select("*").eq("session_id", session_id).order("created_at", desc=False).execute()
        return api_success(messages=res.data or [])
    except Exception as e:
        return api_error(str(e), status_code=500)
