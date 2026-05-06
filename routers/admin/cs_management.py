from typing import Optional
from datetime import datetime
import uuid, base64, asyncio
from pydantic import BaseModel
from fastapi import APIRouter, Request, Depends, HTTPException, status, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from routers.common import supabase, api_success, api_error, logger, require_admin_roles, render_admin_template, BOT_AVAILABLE
from routers.schemas import AdminManualChatPayload
from routers.dependencies import get_current_admin

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
router = APIRouter(
    tags=["Panel CS"],
    dependencies=[require_admin_roles("super_admin", "marketing", "cs")] 
)
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
    
class ResolveSessionPayload(BaseModel):
    session_id: int
    tele_id: int
    admin_notes: Optional[str] = ""

# ==============================================================================
# JALUR RENDER HALAMAN HTML
# ==============================================================================
@router.get("/admin/cs", response_class=HTMLResponse)
async def admin_cs_dashboard(
    request: Request,
    # CUKUP PANGGIL FUNGSINYA LANGSUNG KARENA UDAH BAWAAN DEPENDS DARI COMMON.PY
    admin=Depends(get_current_admin)
):
    # Menyambungkan backend ini ke template HTML cs_management.html
    return render_admin_template(
        request, 
        "admin/cs_management.html", 
        admin_data=admin,
        pending_count=get_pending_count()
    )

# ==============================================================================
# JALUR API JSON (Penyedot Data untuk Alpine.js)
# ==============================================================================
@router.get("/api/v1/admin/cs/sessions", tags=["API Admin CRM"], dependencies=[require_admin_roles("super_admin", "marketing", "cs")])
async def api_admin_get_sessions():
    """Mengambil daftar list obrolan yang sedang aktif/riwayat"""
    try:
        if not supabase: return api_success(sessions=[], admin_takes=0)
        
        # 1. Tarik data sesi
        res_sess = supabase.table("ai_chat_sessions").select("*").order("created_at", desc=True).execute()
        sessions = res_sess.data or []
        
        if sessions:
            # --- UPDATE: Narik content DAN created_at pesan terakhir ---
            session_ids = [s["id"] for s in sessions]
            res_msgs = supabase.table("ai_chat_messages").select("session_id, content, created_at").in_("session_id", session_ids).order("created_at", desc=False).execute()
            
            msg_map = {}
            time_map = {}
            for m in (res_msgs.data or []):
                msg_map[m["session_id"]] = m["content"]
                time_map[m["session_id"]] = m["created_at"] # Ambil waktu pesan paling akhir

            # 2. Tarik data customer
            tele_ids = list(set([s["telegram_id"] for s in sessions]))
            res_cust = supabase.table("customers").select("telegram_id, full_name, username").in_("telegram_id", tele_ids).execute()
            
            cust_map = {c["telegram_id"]: {"full_name": c.get("full_name"), "username": c.get("username")} for c in (res_cust.data or [])}
            
            # Tempelin nama, pesan terakhir, dan UPDATE WAKTU SESI ke masing-masing chat
            for s in sessions:
                s["customers"] = cust_map.get(s["telegram_id"], {"full_name": "Pelanggan Baru", "username": "Anonymous"})
                s["last_message"] = msg_map.get(s["id"], "Tidak ada pesan")
                # Timpa updated_at dengan waktu pesan terakhir biar sorting jalan
                s["updated_at"] = time_map.get(s["id"], s.get("updated_at") or s.get("created_at"))
        
        # 3. Hitung berapa sesi yang diambil alih admin
        admin_takes = 0
        try:
            res_admin = supabase.table("ai_chat_messages").select("session_id").eq("role", "admin").execute()
            if res_admin.data:
                admin_takes = len(set([m["session_id"] for m in res_admin.data]))
        except:
            admin_takes = 0
                
        return api_success(sessions=sessions, admin_takes=admin_takes)
        
    except Exception as e:
        return api_error(str(e), status_code=500)

# ==============================================================================
# JALUR EKSEKUSI (Kirim Pesan Manual & Intercept AI)
# ==============================================================================

@router.post("/api/v1/admin/cs/send-manual", tags=["API Admin CRM"])
async def api_admin_send_manual(payload: AdminManualChatPayload):
    try:
        # 1. Simpan sbg log admin
        supabase.table("ai_chat_messages").insert({
            "session_id": payload.session_id, 
            "role": "admin", 
            "content": payload.message
        }).execute()

        # Update Supabase pakai Try-Except biar kalo error gagal update kolom, chatnya tetep kekirim
        try:
            supabase.table("ai_chat_sessions").update({
                "is_human_handled": True
            }).eq("id", payload.session_id).execute()
        except Exception as db_e:
            logger.warning(f"Gagal update is_human_handled (abaikan kalau kolom blm dibuat): {db_e}")

        # 2. Tembak ke Bot Telegram
        try:
            from bot import bot as bot_instance
            await bot_instance.send_message(
                chat_id=payload.tele_id, 
                text=f"👨‍💻 <b>Admin BABA:</b>\n{payload.message}", 
                parse_mode="HTML"
            )
        except Exception as tg_e:
            logger.error(f"Gagal kirim via bot Telegram: {tg_e}")
            return api_error("Database tercatat, tapi gagal kirim ke HP Customer (Bot Error)", 500)
        
        return api_success(message="Pesan terkirim!")
    except Exception as e:
        logger.error(f"❌ [MANUAL CHAT ERROR]: {e}")
        return api_error("Gagal memproses pesan", 500)
    
# Pastikan schema ini ada di atas
class ResolveSessionPayload(BaseModel):
    session_id: int
    tele_id: int
    admin_notes: Optional[str] = ""

# ==============================================================================
# ENDPOINT RESOLVE TICKET (BULLETPROOF)
# ==============================================================================
@router.post("/api/v1/admin/cs/resolve", tags=["API Admin CRM"]) 
async def api_admin_resolve_session(payload: ResolveSessionPayload):
    try:
        # 1. UPDATE DATABASE (Aman dari crash kolom)
        if supabase:
            try:
                # Kita cuma update is_active aja biar pasti sukses di struktur tabel bawaan
                supabase.table("ai_chat_sessions").update({
                    "is_active": False
                }).eq("id", payload.session_id).execute()
            except Exception as db_err:
                logger.warning(f"⚠️ Peringatan DB saat tutup tiket (Bisa diabaikan): {db_err}")

        # 2. TEMBAK NOTIFIKASI KE TELEGRAM CUSTOMER
        try:
            from bot import bot as bot_instance
            pesan_tutup = f"✅ <b>Sesi CS Selesai</b>\n\nKonsultasi Anda telah diselesaikan oleh Admin BABA."
            
            if payload.admin_notes:
                pesan_tutup += f"\n\n<b>Catatan:</b> <i>{payload.admin_notes}</i>"
            
            await bot_instance.send_message(chat_id=payload.tele_id, text=pesan_tutup, parse_mode="HTML")
        except ImportError:
            logger.error("❌ Modul bot gagal di-import.")
        except Exception as tg_err:
            logger.error(f"⚠️ Gagal kirim notif penutup ke Telegram: {tg_err}")

        # 3. CLEAR STATE BOT (Membersihkan antrean FSM)
        try:
            from bot import dp, bot as bot_instance
            from aiogram.fsm.storage.base import StorageKey
            
            # Mendapatkan ID bot untuk kunci Storage
            bot_id = bot_instance.id
            key = StorageKey(bot_id=bot_id, user_id=payload.tele_id, chat_id=payload.tele_id)
            
            # Hapus state agar customer bisa pakai menu bot normal lagi
            await dp.storage.set_state(key, None)
        except Exception as fsm_err:
            logger.warning(f"⚠️ Gagal reset FSM (Aman diabaikan jika tidak pakai strict state storage): {fsm_err}")

        logger.info(f"✅ [TICKET RESOLVED] Sesi {payload.session_id} berhasil ditutup.")
        return api_success(message="Tiket diselesaikan dan notifikasi terkirim.")
        
    except Exception as e:
        logger.error(f"❌ [RESOLVE FATAL ERROR]: {e}")
        # Kembalikan error aslinya ke frontend biar gampang ditracing kalau error lagi
        return api_error(f"Sistem Gagal: {str(e)}", status_code=500)  

@router.get("/api/v1/admin/cs/messages", tags=["API Admin CRM"], dependencies=[require_admin_roles("super_admin", "marketing", "cs")])
async def api_admin_get_messages(session_id: int):
    """Intip isi percakapan satu sesi tertentu"""
    try:
        if not supabase: return api_success(messages=[])
        res = supabase.table("ai_chat_messages").select("*").eq("session_id", session_id).order("created_at", desc=False).execute()
        return api_success(messages=res.data or [])
    except Exception as e:
        return api_error(str(e), status_code=500)