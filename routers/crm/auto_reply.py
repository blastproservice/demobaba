"""
====================================================================================
BABA PARFUME - CRM AUTO REPLY & AI ENGINE (BACKEND) [ULTRA ENTERPRISE V8.0]
====================================================================================
Deskripsi : Arsitektur Backend berskala besar untuk menangani ribuan chat Real-Time.
Fitur Utama:
    1. Circuit Breaker Pattern (Anti-Crash jika Database Supabase Down)
    2. Token Bucket Rate Limiter (Sistem Anti-Spam Enterprise)
    3. Background Task Queue (Menulis log ke DB tanpa memblokir balasan chat)
    4. Advanced TTL In-Memory Cache (Hemat API Call & Resource)
    5. Whitelist Group Integration & Secure Event Hooking
====================================================================================
"""
import os
import time
import random
import logging
import asyncio
from typing import Optional, List, Tuple, Dict, Any
from datetime import datetime

from fastapi import APIRouter, Request, Depends, BackgroundTasks, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from dotenv import load_dotenv

# Telethon for Live Listening (MTProto)
from telethon import TelegramClient, events
from telethon.sessions import StringSession

# Supabase Bridge & Middlewares
from routers.common import supabase, api_success, api_error, render_admin_template
from routers.dependencies import get_current_admin

# Import AI Engine Core
from ai_mtproto import get_mtproto_ai_reply

load_dotenv()

# ==============================================================================
# LOGGING CONFIGURATION
# ==============================================================================
# Matikan log spam dari modul HTTPX bawaan Supabase agar terminal bersih
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

logger = logging.getLogger("baba.crm.autoreply.ultra")
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter('%(asctime)s | [CRM_ENGINE] %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

router = APIRouter(prefix="/admin/crm/auto-reply", tags=["CRM Auto Reply"])

# ==============================================================================
# GLOBAL ENVIRONMENT & STATE
# ==============================================================================
TELEGRAM_API_ID = int(os.getenv("API_ID", "0"))
TELEGRAM_API_HASH = os.getenv("API_HASH", "")

# Parsing Whitelist Groups dari Environment Variables
ENV_GROUPS = os.getenv("WHITELIST_GROUPS", "")
WHITELIST_GROUPS = [int(g.strip()) for g in ENV_GROUPS.split(",") if g.strip().lstrip('-').isdigit()]

# Menyimpan instances dari Telethon client berdasarkan Admin ID
ACTIVE_LISTENERS: Dict[str, TelegramClient] = {}

# ==============================================================================
# ENTERPRISE COMPONENT 1: CIRCUIT BREAKER PATTERN
# Mencegah cascading failures jika Supabase sedang down atau timeout.
# ==============================================================================
class DatabaseCircuitBreaker:
    def __init__(self, failure_threshold: int = 5, recovery_timeout: int = 60):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failures = 0
        self.last_failure_time = 0.0
        self.state = "CLOSED" # CLOSED = Normal, OPEN = Error/Cut off, HALF_OPEN = Testing recovery
        self._lock = asyncio.Lock()

    async def execute(self, func, *args, **kwargs):
        """Mengeksekusi fungsi database dengan perlindungan Circuit Breaker"""
        async with self.lock:
            if self.state == "OPEN":
                if time.time() - self.last_failure_time > self.recovery_timeout:
                    logger.info("Circuit Breaker masuk ke fase HALF-OPEN. Mencoba koneksi kembali...")
                    self.state = "HALF_OPEN"
                else:
                    raise Exception("Circuit Breaker OPEN: Database Supabase sedang tidak dapat diakses.")

        try:
            # Panggil fungsi aslinya (Supabase call)
            result = func(*args, **kwargs)
            
            async with self.lock:
                if self.state == "HALF_OPEN":
                    logger.info("Circuit Breaker CLOSED: Koneksi database kembali normal.")
                    self.state = "CLOSED"
                    self.failures = 0
            return result
            
        except Exception as e:
            async with self.lock:
                self.failures += 1
                self.last_failure_time = time.time()
                if self.failures >= self.failure_threshold:
                    self.state = "OPEN"
                    logger.error(f"Circuit Breaker OPEN: Mencapai batas kegagalan ({self.failures}). Melindungi sistem.")
            raise e

    @property
    def lock(self):
        return self._lock

db_circuit = DatabaseCircuitBreaker()

# ==============================================================================
# ENTERPRISE COMPONENT 2: ASYNC BACKGROUND TASK QUEUE
# Menyimpan log chat ke DB tanpa memperlambat respon bot ke pelanggan.
# ==============================================================================
class AsyncDatabaseLogger:
    def __init__(self):
        self.queue = asyncio.Queue()
        self.is_running = False
        self.worker_task = None

    async def start(self):
        if not self.is_running:
            self.is_running = True
            self.worker_task = asyncio.create_task(self._worker())
            logger.info("Background Database Logger berjalan...")

    async def stop(self):
        self.is_running = False
        if self.worker_task:
            self.worker_task.cancel()
            
    async def log_message(self, session_id: int, role: str, content: str):
        """Menambahkan pesan ke dalam antrean untuk disimpan"""
        await self.queue.put({
            "session_id": session_id,
            "role": role,
            "content": content
        })

    async def _worker(self):
        """Pekerja di background yang mengambil data dari antrean dan menyimpan ke DB"""
        while self.is_running:
            try:
                task = await self.queue.get()
                if supabase:
                    # Bungkus dengan Circuit Breaker
                    await db_circuit.execute(
                        supabase.table("ai_chat_messages").insert,
                        task
                    ).execute()
                self.queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Gagal menulis log di background: {e}")
                await asyncio.sleep(2) # Backoff sebelum mencoba task berikutnya

bg_db_logger = AsyncDatabaseLogger()

# ==============================================================================
# ENTERPRISE COMPONENT 3: TOKEN BUCKET RATE LIMITER
# Mencegah spam brutal dari pelanggan menggunakan algoritma standar industri.
# ==============================================================================
class TokenBucketRateLimiter:
    def __init__(self, capacity: int = 5, refill_rate_per_sec: float = 0.2):
        self.capacity = capacity
        self.refill_rate = refill_rate_per_sec
        self.buckets: Dict[int, Dict[str, float]] = {}
        self._lock = asyncio.Lock()

    async def acquire(self, user_id: int) -> bool:
        """Mengambil 1 token. Mengembalikan True jika diizinkan, False jika terkena limit."""
        async with self._lock:
            now = time.time()
            if user_id not in self.buckets:
                self.buckets[user_id] = {"tokens": self.capacity, "last_refill": now}
            
            bucket = self.buckets[user_id]
            time_passed = now - bucket["last_refill"]
            
            # Refill tokens berdasarkan waktu yang berlalu
            refill_amount = time_passed * self.refill_rate
            bucket["tokens"] = min(self.capacity, bucket["tokens"] + refill_amount)
            bucket["last_refill"] = now

            if bucket["tokens"] >= 1.0:
                bucket["tokens"] -= 1.0
                return True
            return False

rate_limiter = TokenBucketRateLimiter(capacity=7, refill_rate_per_sec=0.15)

# ==============================================================================
# ENTERPRISE COMPONENT 4: ADVANCED TTL CACHE MANAGER
# Caching untuk aturan auto-reply agar tidak membebani Supabase.
# ==============================================================================
class CacheManager:
    def __init__(self, ttl_seconds: int = 15):
        self.ttl = ttl_seconds
        self.cache: Dict[str, Any] = {}
        self.timestamps: Dict[str, float] = {}

    def get(self, key: str) -> Optional[Any]:
        if key in self.cache:
            if time.time() - self.timestamps[key] < self.ttl:
                return self.cache[key]
            else:
                self.delete(key)
        return None

    def set(self, key: str, value: Any):
        self.cache[key] = value
        self.timestamps[key] = time.time()

    def delete(self, key: str):
        self.cache.pop(key, None)
        self.timestamps.pop(key, None)

app_cache = CacheManager(ttl_seconds=10)

# ==============================================================================
# HTTP SCHEMAS
# ==============================================================================
class KeywordPayload(BaseModel):
    id: Optional[int] = None
    keyword: str
    reply_text: str
    match_type: str = "exact"

class AiTogglePayload(BaseModel):
    active: bool

# ==============================================================================
# FASTAPI ROUTES: UI RENDERING
# ==============================================================================
@router.get("", response_class=HTMLResponse)
async def auto_reply_page(request: Request, admin=Depends(get_current_admin)):
    """Entry point untuk halaman Dashboard CRM Auto Reply."""
    return render_admin_template(request, "crm/auto_reply.html", admin_data=admin)

# ==============================================================================
# FASTAPI ROUTES: DATA SYNCHRONIZATION
# ==============================================================================
@router.get("/api/data")
async def get_auto_reply_data(admin=Depends(get_current_admin)):
    """Mengambil dan memformat data untuk Front-End Alpine.js"""
    if not supabase: 
        return api_error("Sistem Database Offline", 503)
        
    admin_id = admin.get("admin_id")
    
    try:
        # Fetching Keywords
        key_res = supabase.table("crm_auto_replies").select("*").eq("created_by", admin_id).order("created_at", desc=True).execute()
        
        # Fetching Session Status
        session_res = supabase.table("crm_telegram_sessions").select("status, ai_reply_active").eq("admin_id", admin_id).eq("status", "active").execute()
        
        ai_active = session_res.data[0].get("ai_reply_active", False) if session_res.data else False
        mt_status = "connected" if session_res.data else "disconnected"

        # Fetching Live Logs (Limit 8 for Dashboard Performance)
        logs_res = supabase.table("ai_chat_messages")\
            .select("id, role, content, created_at, ai_chat_sessions(telegram_id)")\
            .eq("role", "assistant")\
            .order("created_at", desc=True)\
            .limit(8)\
            .execute()
        
        recent_logs = []
        for log_entry in logs_res.data or []:
            tele_id = str(log_entry.get("ai_chat_sessions", {}).get("telegram_id", "Unknown"))
            content = log_entry.get("content", "")
            
            # Identifikasi sumber balasan
            source_engine = "KEYWORD" if "[KEYWORD_REPLY]" in content else "AI AGENT"
            content = content.replace("[KEYWORD_REPLY]", "").strip()
            
            # Sanitize content for UI
            clean_content = content.replace("*", "").replace("_", "")
            preview = clean_content[:45] + ("..." if len(clean_content) > 45 else "")

            recent_logs.append({
                "id": log_entry.get("id"),
                "user_name": f"Client ID: {tele_id}",
                "user_initial": tele_id[-2:] if tele_id != "Unknown" else "??",
                "source": source_engine,
                "trigger": preview,
                "time": log_entry.get("created_at")
            })

        return api_success(data={
            "keywords": key_res.data or [],
            "ai_active": ai_active,
            "mtproto_status": mt_status,
            "recent_logs": recent_logs,
            "total_hits": len(recent_logs)
        })
        
    except Exception as e:
        logger.error(f"Kesalahan sinkronisasi data: {e}")
        return api_error("Internal Server Error saat memuat data")

# ==============================================================================
# FASTAPI ROUTES: TOGGLE AI & DAEMON CONTROLLER
# ==============================================================================
@router.post("/api/toggle-ai")
async def toggle_ai_agent(payload: AiTogglePayload, bg_tasks: BackgroundTasks, admin=Depends(get_current_admin)):
    """Mengendalikan nyawa dari Telethon Listener secara dinamis"""
    if not supabase: 
        return api_error("Database offline", 503)
        
    admin_id = admin.get("admin_id")

    try:
        session_res = supabase.table("crm_telegram_sessions").select("id, session_string").eq("admin_id", admin_id).eq("status", "active").execute()
        if not session_res.data: 
            return api_error("Sesi MTProto tidak ditemukan. Harap hubungkan nomor Telegram terlebih dahulu.")
            
        session_id = session_res.data[0]['id']
        session_string = session_res.data[0]['session_string']

        # Update status di database
        supabase.table("crm_telegram_sessions").update({"ai_reply_active": payload.active}).eq("id", session_id).execute()

        global ACTIVE_LISTENERS
        listener_key = f"admin_{admin_id}"

        # Mengatur Background Listener berdasarkan state
        if payload.active:
            if listener_key not in ACTIVE_LISTENERS:
                logger.info(f"Menginisialisasi Daemon Listener untuk Admin ID: {admin_id}...")
                await bg_db_logger.start() # Start the logging queue
                bg_tasks.add_task(start_telegram_listener, admin_id, session_string, session_id)
        else:
            if listener_key in ACTIVE_LISTENERS:
                client = ACTIVE_LISTENERS[listener_key]
                await client.disconnect()
                del ACTIVE_LISTENERS[listener_key]
                logger.info(f"Daemon Listener untuk Admin ID: {admin_id} telah dihentikan.")

        # Hapus cache agar sinkronisasi di listener mengambil state terbaru
        app_cache.delete(f"config_{admin_id}")

        return api_success(data={"current_state": payload.active})
    except Exception as e:
        logger.error(f"Gagal memutar state AI: {e}")
        return api_error("Gagal mengkonfigurasi agen AI.")

# ==============================================================================
# FASTAPI ROUTES: KEYWORD CRUD
# ==============================================================================
@router.post("/api/save")
async def save_keyword(payload: KeywordPayload, admin=Depends(get_current_admin)):
    """Menyimpan atau mengupdate aturan Auto Reply statis"""
    if not supabase: return api_error("Database offline")
    admin_id = admin.get("admin_id")
    
    try:
        data = {
            "keyword": payload.keyword.strip(),
            "reply_text": payload.reply_text.strip(),
            "match_type": payload.match_type,
            "created_by": admin_id
        }
        
        if payload.id: 
            supabase.table("crm_auto_replies").update(data).eq("id", payload.id).execute()
        else: 
            supabase.table("crm_auto_replies").insert(data).execute()
            
        # Invalidate Cache
        app_cache.delete(f"config_{admin_id}")
        return api_success(message="Aturan Keyword berhasil divalidasi dan disimpan.")
    except Exception as e: 
        return api_error("Gagal memproses penyimpanan aturan.")

@router.delete("/api/delete/{id}")
async def delete_keyword(id: int, admin=Depends(get_current_admin)):
    """Menghapus aturan Keyword"""
    if not supabase: return api_error("Database offline")
    admin_id = admin.get("admin_id")
    
    try:
        supabase.table("crm_auto_replies").delete().eq("id", id).eq("created_by", admin_id).execute()
        app_cache.delete(f"config_{admin_id}")
        return api_success(message="Aturan berhasil dilenyapkan dari database.")
    except Exception as e: 
        return api_error("Operasi penghapusan gagal.")

# ==============================================================================
# CORE ENGINE: TELEGRAM EVENT LOOP (MTPROTO)
# ==============================================================================
async def start_telegram_listener(admin_id: int, session_string: str, db_session_id: int):
    """
    Fungsi Abadi (Long-Running Task) yang menempel ke Telethon Event Loop.
    Arsitektur:
    1. Hook Incoming Message -> 2. Rate Limiting -> 3. Group Whitelisting
    4. Exact/Contains Keyword Matching -> 5. Deep Gemini AI Contextual Gen -> 6. Async Sending
    """
    global ACTIVE_LISTENERS
    listener_key = f"admin_{admin_id}"
    
    # Inisialisasi Telethon Client (Hanya gunakan memory session)
    client = TelegramClient(StringSession(session_string), TELEGRAM_API_ID, TELEGRAM_API_HASH)
    
    try:
        await client.connect()
        if not await client.is_user_authorized(): 
            logger.error("Akses MTProto ditolak. Harap rekoneksi QR/Nomor Telegram Anda.")
            return
            
        ACTIVE_LISTENERS[listener_key] = client
        logger.info(f"🛡️ [SHIELD ACTIVE] Enterprise Listener untuk Admin {admin_id} siap menerima lalu lintas chat.")

        # ======================================================================
        # EVENT HANDLER MAIN LOGIC
        # ======================================================================
        @client.on(events.NewMessage(incoming=True))
        async def incoming_message_handler(event):
            sender = await event.get_sender()
            
            # SAFE SENDER CHECK: Mencegah crash jika pengirim adalah Channel/System
            if not sender or getattr(sender, 'bot', False) or getattr(sender, 'is_self', False): 
                return

            incoming_text = getattr(event.message, 'text', '')
            if not incoming_text: 
                return
            
            sender_id = event.sender_id
            chat_id = event.chat_id
            is_private = event.is_private

            # --- 1. FILTER GRUP (WHITELIST SYSTEM) ---
            # Mengabaikan pesan dari grup yang tidak terdaftar di environment variables
            if not is_private:
                if chat_id not in WHITELIST_GROUPS:
                    return

            # --- 2. CONFIGURATION SYNC (VIA CACHE) ---
            cache_key = f"config_{admin_id}"
            config = app_cache.get(cache_key)
            
            if not config:
                if not supabase: return
                # Fetching data dari DB jika cache kosong/expired
                sess = supabase.table("crm_telegram_sessions").select("ai_reply_active").eq("id", db_session_id).single().execute()
                kw_res = supabase.table("crm_auto_replies").select("*").eq("created_by", admin_id).execute()
                
                config = {
                    "ai_active": sess.data.get("ai_reply_active", False) if sess.data else False,
                    "keywords": kw_res.data or []
                }
                app_cache.set(cache_key, config)

            # Jika toggle AI Agent dimatikan dari Front-End, abaikan pesan
            if not config.get("ai_active", False): 
                return 

            # --- 3. RATE LIMITING (ANTI SPAM) ---
            if is_private:
                is_allowed = await rate_limiter.acquire(sender_id)
                if not is_allowed:
                    logger.warning(f"Rate limit terlampaui untuk user {sender_id}. Pesan diabaikan untuk mencegah spam.")
                    # Memberitahu pengguna bahwa mereka dibatasi (hanya sesekali agar tidak backfire spam)
                    if random.random() > 0.7: 
                        await client.send_message(sender_id, "Sabar kak, ngetiknya cepet banget 🏃‍♂️ Tunggu bentar ya biar Mimin bisa baca.")
                    return

            # --- 4. STATIC KEYWORD MATCHING ENGINE ---
            reply_text = None
            is_keyword_match = False
            incoming_lower = incoming_text.lower()
            
            for kw in config.get("keywords", []):
                triggers = [k.strip().lower() for k in kw['keyword'].split(',')]
                for trigger in triggers:
                    if kw['match_type'] == 'exact' and incoming_lower == trigger:
                        reply_text = kw['reply_text']
                        is_keyword_match = True
                        break
                    elif kw['match_type'] == 'contains' and trigger in incoming_lower:
                        reply_text = kw['reply_text']
                        is_keyword_match = True
                        break
                if is_keyword_match: break

            # --- 5. DEEP AI INTEGRATION (VIA GEMINI & ai_mtproto.py) ---
            # AI hanya akan aktif membalas jalur Japri jika tidak ada keyword yang cocok
            chat_session_id = None
            
            if not is_keyword_match and is_private:
                try:
                    # Resolve Chat Session dari Supabase
                    if supabase:
                        chat_session = supabase.table("ai_chat_sessions").select("id").eq("telegram_id", sender_id).execute()
                        if not chat_session.data:
                            res_cs = supabase.table("ai_chat_sessions").insert({"telegram_id": sender_id}).execute()
                            chat_session_id = res_cs.data[0]['id']
                        else:
                            chat_session_id = chat_session.data[0]['id']
                        
                        # Logging pesan pengguna via Background Task (Asynchronous)
                        await bg_db_logger.log_message(chat_session_id, "user", incoming_text)

                    # MELEMPAR PROSES KE OTAK AI (ai_mtproto.py)
                    reply_text = await get_mtproto_ai_reply(chat_session_id, incoming_text)
                    
                except Exception as ai_err:
                    logger.error(f"Kegagalan kritis pada pemanggilan Eksekutor AI: {ai_err}")
                    reply_text = "Maaf kak, sinyal Mimin lagi kurang bagus nih. Minta waktunya bentar ya 🙏"

            # --- 6. ASYNCHRONOUS DISPATCH & LOGGING ---
            if reply_text:
                try:
                    # Meniru waktu mengetik manusia secara natural (Jitter)
                    base_delay = 0.5 if is_keyword_match else 1.5
                    jitter = random.uniform(0.5, 2.0)
                    
                    async with client.action(chat_id, 'typing'):
                        await asyncio.sleep(base_delay + jitter)
                        
                        # Eksekusi pengiriman
                        if not is_private:
                            # Balas reply spesifik jika di Grup
                            await client.send_message(chat_id, reply_text, reply_to=event.message.id)
                        else:
                            await client.send_message(chat_id, reply_text)
                    
                    # Log respon Mimin ke Database via Antrean Background (Hanya Japri)
                    if is_private and chat_session_id:
                        log_content = f"[KEYWORD_REPLY] {reply_text}" if is_keyword_match else reply_text
                        await bg_db_logger.log_message(chat_session_id, "assistant", log_content)
                        
                    logger.info(f"✅ Balasan sukses di-dispatch ke {'Japri' if is_private else 'Grup'} (ID: {chat_id})")
                    
                except Exception as send_err:
                    logger.error(f"❌ Kegagalan pada Network Layer saat mengirim pesan Telegram: {send_err}")

        # Tahan event loop agar client tetap mendengarkan secara abadi
        await client.run_until_disconnected()

    except Exception as e:
        logger.error(f"❌ [CRITICAL HALT] Telethon Listener Crash: {str(e)}")
    finally:
        if listener_key in ACTIVE_LISTENERS:
            del ACTIVE_LISTENERS[listener_key]
        logger.warning(f"📉 Listener MTProto telah dicabut dari memori untuk Admin ID: {admin_id}.")