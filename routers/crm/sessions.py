"""
====================================================================================
BABA PARFUME - MTPROTO SESSION MANAGER (CRM) [ENTERPRISE GRADE]
====================================================================================
Deskripsi : Menangani proses Autentikasi Telegram (MTProto) menggunakan Telethon.
            - Kirim Kode OTP
            - Verifikasi Kode OTP
            - Handling 2FA (Two-Step Verification Password)
            - Logout Session
====================================================================================
"""
import os
import logging
import json
from typing import Dict, Any

from fastapi import APIRouter, Depends, HTTPException, Body
from pydantic import BaseModel
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import (
    SessionPasswordNeededError, 
    PhoneCodeInvalidError, 
    PhoneCodeExpiredError,
    PasswordHashInvalidError
)
from dotenv import load_dotenv

from routers.common import api_success, api_error
from routers.dependencies import get_current_admin

# Load env variables
load_dotenv()

try:
    from database import supabase
except ImportError:
    supabase = None

logger = logging.getLogger("baba.crm.sessions")

# ==============================================================================
# CONFIG & CACHE 
# ==============================================================================
TELEGRAM_API_ID = int(os.getenv("API_ID", "0"))
TELEGRAM_API_HASH = os.getenv("API_HASH", "")

if not TELEGRAM_API_ID or not TELEGRAM_API_HASH:
    logger.critical("❌ [FATAL ERROR] API_ID dan API_HASH tidak ditemukan di .env!")

# Cache memory untuk nyimpen state login (Client Object & Hash)
# Penting: Client tidak boleh diputus (disconnect) jika nyangkut di 2FA
LOGIN_CACHE: Dict[str, dict] = {}

router = APIRouter(prefix="/admin/api/crm/mtproto", tags=["CRM MTProto"])

# ==============================================================================
# SCHEMAS
# ==============================================================================
class PhonePayload(BaseModel):
    phone: str

class VerifyPayload(BaseModel):
    phone: str
    code: str

class PasswordPayload(BaseModel):
    phone: str
    password: str

# ==============================================================================
# 1. SEND OTP CODE
# ==============================================================================
@router.post("/send_code")
async def send_telegram_code(payload: PhonePayload, admin=Depends(get_current_admin)):
    """Mengirim kode OTP Telegram ke nomor HP Admin"""
    phone = payload.phone.strip()
    
    # Bikin client Telethon baru dengan StringSession kosong (belum login)
    client = TelegramClient(StringSession(), TELEGRAM_API_ID, TELEGRAM_API_HASH)
    
    try:
        await client.connect()
        if not await client.is_user_authorized():
            # Minta kirim kode OTP ke Telegram Server
            send_code_result = await client.send_code_request(phone)
            
            # Simpan client dan hash ke cache untuk step verifikasi nanti
            LOGIN_CACHE[phone] = {
                "client": client,
                "phone_code_hash": send_code_result.phone_code_hash
            }
            
            logger.info(f"📲 [MTPROTO] Berhasil mengirim OTP ke {phone}")
            return api_success(message=f"Kode OTP berhasil dikirim ke aplikasi Telegram {phone}")
        else:
            await client.disconnect()
            return api_error("Nomor ini sudah terotorisasi sebelumnya. Silakan periksa dashboard.")
            
    except Exception as e:
        logger.error(f"❌ [MTPROTO SEND CODE ERROR]: {str(e)}")
        if client: await client.disconnect()
        return api_error(f"Gagal mengirim kode: {str(e)}", 500)


# ==============================================================================
# 2. VERIFY OTP CODE (WITH 2FA CATCHER)
# ==============================================================================
@router.post("/verify")
async def verify_telegram_code(payload: VerifyPayload, admin=Depends(get_current_admin)):
    """Verifikasi OTP. Akan melempar status khusus jika butuh 2FA Password."""
    phone = payload.phone.strip()
    code = payload.code.strip()
    
    if phone not in LOGIN_CACHE:
        return api_error("Sesi login tidak ditemukan atau sudah kadaluarsa. Silakan refresh halaman dan request OTP ulang.")
        
    cache_data = LOGIN_CACHE[phone]
    client: TelegramClient = cache_data["client"]
    phone_code_hash = cache_data["phone_code_hash"]
    
    try:
        # Eksekusi Sign In Tahap 1 (Nomor + OTP)
        await client.sign_in(phone=phone, code=code, phone_code_hash=phone_code_hash)
        
        # JIKA LOLOS TANPA 2FA -> Langsung sukses
        session_string = client.session.save()
        await _save_session_to_db(admin.get("admin_id"), phone, session_string)
        
        await client.disconnect()
        del LOGIN_CACHE[phone]
        
        logger.info(f"✅ [MTPROTO] Login sukses (Tanpa 2FA) untuk {phone}")
        return api_success(message="Koneksi MTProto berhasil diamankan!")
        
    except SessionPasswordNeededError:
        # JIKA KENA 2FA -> Jangan disconnect client! Biarkan di cache.
        logger.warning(f"🔐 [MTPROTO] Akun {phone} membutuhkan Password 2FA.")
        return {"status": "password_needed", "message": "Akun dilindungi 2FA. Masukkan password."}
        
    except PhoneCodeInvalidError:
        return api_error("Kode OTP yang Anda masukkan salah!")
    except PhoneCodeExpiredError:
        return api_error("Kode OTP sudah kadaluarsa. Silakan request ulang.")
    except Exception as e:
        logger.error(f"❌ [MTPROTO VERIFY ERROR]: {str(e)}")
        return api_error(f"Verifikasi gagal: {str(e)}", 400)


# ==============================================================================
# 3. VERIFY 2FA PASSWORD
# ==============================================================================
@router.post("/verify_password")
async def verify_telegram_password(payload: PasswordPayload, admin=Depends(get_current_admin)):
    """Menyelesaikan login untuk akun yang terkunci 2FA Password"""
    phone = payload.phone.strip()
    password = payload.password.strip()
    
    if phone not in LOGIN_CACHE:
        return api_error("Sesi login hilang. Silakan ulangi proses dari awal (Minta OTP).")
        
    cache_data = LOGIN_CACHE[phone]
    client: TelegramClient = cache_data["client"]
    
    try:
        # Eksekusi Sign In Tahap 2 (Hanya butuh password karena OTP sudah lolos di tahap 1)
        await client.sign_in(password=password)
        
        # Sukses login! Ekstrak String Session-nya
        session_string = client.session.save()
        await _save_session_to_db(admin.get("admin_id"), phone, session_string)
        
        # Tutup client dan bersihkan cache
        await client.disconnect()
        del LOGIN_CACHE[phone]
        
        logger.info(f"✅ [MTPROTO] Login 2FA sukses untuk {phone}")
        return api_success(message="Verifikasi 2-Langkah berhasil! MTProto Aktif.")
        
    except PasswordHashInvalidError:
        return api_error("Password 2FA yang Anda masukkan salah!")
    except Exception as e:
        logger.error(f"❌ [MTPROTO 2FA ERROR]: {str(e)}")
        return api_error(f"Gagal verifikasi sandi: {str(e)}", 400)


# ==============================================================================
# 4. LOGOUT MTPROTO
# ==============================================================================
@router.post("/logout")
async def logout_telegram(admin=Depends(get_current_admin)):
    """Memutuskan koneksi MTProto dari server Telegram dan mengupdate status DB"""
    if not supabase: return api_error("Database offline", 503)
    
    try:
        # Cari session aktif milik admin
        res = supabase.table("crm_telegram_sessions")\
                      .select("id, session_string")\
                      .eq("admin_id", admin.get("admin_id"))\
                      .eq("status", "active").execute()
                      
        if not res.data:
            return api_error("Tidak ada koneksi aktif yang ditemukan.")
            
        session_id = res.data[0]["id"]
        session_string = res.data[0]["session_string"]
        
        # Hubungkan Telethon untuk log out resmi dari server Telegram
        client = TelegramClient(StringSession(session_string), TELEGRAM_API_ID, TELEGRAM_API_HASH)
        await client.connect()
        if await client.is_user_authorized():
            await client.log_out()
            
        await client.disconnect()
        
        # Matikan status di database
        supabase.table("crm_telegram_sessions").update({
            "status": "disconnected"
        }).eq("id", session_id).execute()
        
        logger.info(f"🔌 [MTPROTO] Koneksi diputuskan untuk sesi ID: {session_id}")
        return api_success(message="Koneksi MTProto berhasil diputus secara aman.")
        
    except Exception as e:
        logger.error(f"❌ [MTPROTO LOGOUT ERROR]: {str(e)}")
        return api_error("Terjadi kesalahan saat memutuskan koneksi.", 500)


# ==============================================================================
# INTERNAL HELPER
# ==============================================================================
async def _save_session_to_db(admin_id: int, phone: str, session_string: str):
    """Helper internal untuk update/insert session string ke Supabase PostgreSQL"""
    if not supabase:
        logger.error("⚠️ Supabase tidak aktif. Session tidak tersimpan ke database!")
        return
        
    # Pastikan tabel 'crm_telegram_sessions' sudah lu buat di DB ya bre
    supabase.table("crm_telegram_sessions").upsert({
        "admin_id": admin_id,
        "phone_number": phone,
        "session_string": session_string,
        "status": "active",
        "ai_reply_active": False
    }).execute()