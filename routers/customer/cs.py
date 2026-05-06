"""
====================================================================================
BABA PARFUME - CS & AI ROUTER (COMMUNICATION ENGINE)
====================================================================================
Deskripsi : Menangani obrolan AI (Mimin) dan Bridge intersep untuk Bot Telegram.
====================================================================================
"""
import logging
import asyncio
from typing import Optional
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from datetime import datetime, timezone

from database import supabase
from ai_agent import get_ai_recommendation

logger = logging.getLogger("baba.cs")
templates = Jinja2Templates(directory="templates")

router = APIRouter(tags=["Customer Service"])

# ==============================================================================
# SCHEMAS (Sudah Disesuaikan dengan Payload dari cs_management.html)
# ==============================================================================
class ChatSendPayload(BaseModel):
    tele_id: int
    message: str

class ChatFeedbackPayload(BaseModel):
    tele_id: int
    rating: int = Field(ge=1, le=5)
    complaint: Optional[str] = ""

class ResolveSessionPayload(BaseModel):
    session_id: int   # FIX: Diubah dari ticket_id menjadi session_id
    tele_id: int
    admin_notes: Optional[str] = ""

def api_success(**payload): return {"status": "success", **payload}
def api_error(msg: str, code: int = 400): return JSONResponse(status_code=code, content={"status": "error", "message": msg})

# ==============================================================================
# HTML & AI CHAT ENDPOINTS
# ==============================================================================
@router.get("/cs", response_class=HTMLResponse)
async def chat_ai_page(request: Request):
    return templates.TemplateResponse("customer/cs.html", {"request": request})

@router.post("/api/v1/chat/send")
async def chat_ai_send(payload: ChatSendPayload):
    if not payload.message.strip(): return api_error("Pesan kosong", 400)
    try:
        # =================================================================
        # 🔄 AUTO-REOPEN TICKET ENGINE (Tanpa ribet gembok)
        # =================================================================
        if supabase:
            try:
                # Cari tiket terakhir si customer
                res_sess = supabase.table("ai_chat_sessions").select("id, is_active").eq("telegram_id", payload.tele_id).order("created_at", desc=True).limit(1).execute()
                
                # Kalau ada tiket dan statusnya False (Selesai), kita hidupkan lagi!
                if res_sess.data and not res_sess.data[0].get('is_active'):
                    supabase.table("ai_chat_sessions").update({
                        "is_active": True
                    }).eq("id", res_sess.data[0]['id']).execute()
                    logger.info(f"🔄 [AUTO-REOPEN] Tiket {res_sess.data[0]['id']} diaktifkan kembali.")
            except Exception as db_err:
                logger.warning(f"⚠️ Gagal auto-reopen sesi: {db_err}")

        # Eksekusi AI (Sekarang AI pasti mau jawab karena tiket udah aktif)
        ai_reply = await get_ai_recommendation(payload.tele_id, payload.message)
        
        # Pengaman UI biar bubble gak putih kosong kalau API Gemini lagi limit
        if not ai_reply:
            ai_reply = "Maaf kak, Mimin lagi sinkronisasi data nih. Coba ketik pesannya lagi ya! 🔄"

        return api_success(reply=ai_reply)

    except Exception as e:
        logger.error(f"❌ [AI ERROR]: {e}")
        return api_error("Mimin lagi pusing, server kepenuhan!", 500)

@router.post("/api/v1/chat/reset")
async def chat_reset(payload: dict): 
    """Menghapus secara permanen seluruh riwayat user (Hard Delete)"""
    try:
        tele_id = payload.get("tele_id")
        if supabase:
            # 1. Tarik semua ID sesi user ini
            res_sess = supabase.table("ai_chat_sessions").select("id").eq("telegram_id", tele_id).execute()
            if res_sess.data:
                # 2. Hancurkan pesannya satu per satu biar Supabase nggak nolak
                for s in res_sess.data:
                    supabase.table("ai_chat_messages").delete().eq("session_id", s["id"]).execute()
                
                # 3. Hancurkan sesinya
                supabase.table("ai_chat_sessions").delete().eq("telegram_id", tele_id).execute()
                
        logger.info(f"🧹 [HARD RESET] Database chat ID:{tele_id} dibersihkan total.")
        return api_success(message="Database bersih, sesi direstart!")
    except Exception as e:
        logger.error(f"❌ [RESET ERROR]: {e}")
        return api_error("Gagal membersihkan database", 500)

@router.post("/api/v1/chat/feedback")
async def submit_ai_feedback(payload: ChatFeedbackPayload):
    try:
        if supabase:
            supabase.table("ai_feedbacks").insert({
                "telegram_id": payload.tele_id, "rating": payload.rating, "complaint": payload.complaint
            }).execute()
        return api_success(message="Makasih ya kak feedback-nya!")
    except Exception as e:
        return api_error(str(e), 500)

@router.get("/api/v1/chat/history")
async def get_chat_history(tele_id: int):
    """Menarik history dan menghitung Cooldown Sapaan (2 Jam)"""
    try:
        if not supabase: return api_success(history=[], needs_greeting=True)
        
        # 1. Ambil SEMUA ID sesi milik customer ini
        res_sess = supabase.table("ai_chat_sessions").select("id").eq("telegram_id", tele_id).execute()
        if not res_sess.data: return api_success(history=[], needs_greeting=True)
        
        session_ids = [s["id"] for s in res_sess.data]
        
        # 2. Tarik semua pesan lintas sesi (maksimal 100 biar HP customer ga ngehang)
        res_msg = supabase.table("ai_chat_messages").select("role, content, created_at").in_("session_id", session_ids).order("created_at", desc=False).limit(100).execute()
        history = res_msg.data or []
        
        # 3. LOGIC SMART GREETING (COOLDOWN 2 JAM)
        needs_greeting = False
        if not history:
            needs_greeting = True
        else:
            try:
                # Ambil waktu pesan paling terakhir (Format Supabase = UTC)
                last_msg_time_str = history[-1]["created_at"]
                last_msg_time = datetime.fromisoformat(last_msg_time_str.replace('Z', '+00:00'))
                now_time = datetime.now(timezone.utc)
                
                # Hitung selisih jam
                delta_hours = (now_time - last_msg_time).total_seconds() / 3600
                
                # Jika obrolan terakhir sudah lewat 2 jam, sapa lagi!
                if delta_hours > 2.0:
                    needs_greeting = True
            except Exception as time_err:
                logger.warning(f"Time parse error: {time_err}")
                needs_greeting = False

        return api_success(history=history, needs_greeting=needs_greeting)
    except Exception as e:
        logger.warning(f"⚠️ Error memuat history AI: {e}")
        return api_success(history=[], needs_greeting=True)

# ==============================================================================
# BRIDGE: ADMIN PANEL -> TELEGRAM BOT
# ==============================================================================
@router.post("/api/v1/admin/cs/resolve") # FIX: Endpoint disamakan dengan JS Frontend
async def resolve_cs_ticket(payload: ResolveSessionPayload):
    """
    Dipanggil secara internal oleh Admin Dashboard saat merubah status tiket.
    """
    try:
        # 1. Update Database
        if supabase:
            # Gunakan try-except khusus DB agar error detail terlihat
            try:
                supabase.table("ai_chat_sessions").update({
                    "is_active": False,
                    # Hapus baris 'is_human_handled' di bawah ini jika lu belum buat kolomnya di Supabase
                    "is_human_handled": False 
                }).eq("id", payload.session_id).execute()
            except Exception as db_err:
                logger.error(f"DB Error saat update status sesi: {db_err}")

        # 2. Kirim pesan notifikasi ke Telegram user & Clear FSM
        try:
            from bot import bot as bot_instance
            from bot import dp
            from aiogram.fsm.storage.base import StorageKey

            notif_text = (
                f"✅ <b>Tiket Bantuan Selesai</b>\n\n"
                f"ID Tiket: <code>#{payload.session_id}</code>\n"
                f"Konsultasi Anda telah diselesaikan oleh Admin BABA.\n"
            )
            if payload.admin_notes:
                notif_text += f"\nCatatan: <i>{payload.admin_notes}</i>"

            # Tembak Pesan Telegram
            await bot_instance.send_message(chat_id=payload.tele_id, text=notif_text, parse_mode="HTML")

            # Hapus State CS di Telegram agar bot berfungsi normal
            key = StorageKey(bot_id=bot_instance.id, user_id=payload.tele_id, chat_id=payload.tele_id)
            await dp.storage.set_state(key, None)
            
        except ImportError:
            logger.warning("⚠️ Module bot tidak ditemukan, notifikasi Telegram dilewati.")
        except Exception as tg_err:
            logger.warning(f"⚠️ Telegram API error (mungkin user blokir bot): {tg_err}")

        logger.info(f"✅ [CS RESOLVED] Tiket {payload.session_id} selesai.")
        return api_success(message="Tiket diselesaikan dan notifikasi terkirim.")
        
    except Exception as e:
        logger.error(f"❌ [CS RESOLVE FATAL ERROR]: {e}")
        return api_error(f"Sistem gagal meresolve tiket", 500)