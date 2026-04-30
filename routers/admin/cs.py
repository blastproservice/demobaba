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
@router.get("/api/v1/admin/cs/sessions")
async def api_get_sessions():
    """Narik daftar antrean chat / sesi yang masuk"""
    if not supabase: return JSONResponse({"status": "error", "message": "Database Offline"})
    try:
        # Asumsi tabel lu namanya 'chat_sessions', kita join sama nama customer
        res = supabase.table("chat_sessions").select("*, customers(full_name, username)").order("updated_at", desc=True).execute()
        
        # Hitung statistik sederhana
        sessions = res.data or []
        admin_takes = sum(1 for s in sessions if not s.get("is_active"))
        
        return {
            "status": "success", 
            "sessions": sessions,
            "admin_takes": admin_takes
        }
    except Exception as e:
        print(f"❌ [ERROR GET SESSIONS]: {e}")
        return JSONResponse({"status": "error", "message": str(e)})

@router.get("/api/v1/admin/cs/messages")
async def api_get_messages(session_id: int):
    """Narik isi riwayat chat pas admin ngeklik salah satu pelanggan"""
    if not supabase: return JSONResponse({"status": "error"})
    try:
        res = supabase.table("chat_messages").select("*").eq("session_id", session_id).order("created_at", desc=False).execute()
        return {"status": "success", "messages": res.data or []}
    except Exception as e:
        print(f"❌ [ERROR GET MESSAGES]: {e}")
        return JSONResponse({"status": "error", "message": str(e)})

# ==============================================================================
# JALUR EKSEKUSI (Kirim Pesan Manual & Intercept AI)
# ==============================================================================
@router.post("/api/v1/admin/cs/send-manual")
async def api_send_manual(payload: ManualMessagePayload):
    """Jalur sakti: Simpan chat ke Supabase, lalu tembak ke Telegram!"""
    if not supabase: return JSONResponse({"status": "error"})
    
    try:
        # 1. Simpan riwayat chat lu ke database sebagai role 'admin'
        msg_data = {
            "session_id": payload.session_id,
            "role": "admin",
            "content": payload.message
        }
        supabase.table("chat_messages").insert(msg_data).execute()

        # 2. Update status sesi menjadi 'Intercepted' (is_active = false)
        # Biar bot AI lu tau kalau Amel/Radit udah ngambil alih chat ini
        supabase.table("chat_sessions").update({"is_active": False}).eq("id", payload.session_id).execute()

        # 3. TEMBAK LANGSUNG KE TELEGRAM CUSTOMER!
        if bot:
            await bot.send_message(chat_id=payload.tele_id, text=payload.message)
            print(f"✅ [CS INTERCEPT] Pesan manual berhasil dikirim ke {payload.tele_id}")

        return {"status": "success"}
        
    except Exception as e:
        print(f"❌ [ERROR SEND MANUAL]: {e}")
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})