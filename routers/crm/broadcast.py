"""
====================================================================================
BABA PARFUME - CRM BROADCAST COMMANDER (ENTERPRISE V15.0 ULTIMATE)
====================================================================================
Deskripsi : Engine utama pengiriman pesan massal kelas Enterprise dengan 
            Sistem "Watchdog Polling" Anti-Gagal.
Developer : BABA Enterprise Core Team
Fitur Utama:
            1. [NEW] Native Watchdog Engine: Menggantikan APScheduler untuk eksekusi 
               jadwal yang 100% tahan banting, anti-restart, dan kebal dari hilang memori.
            2. Real-time State Interceptor (PAUSE, RESUME, STOP).
            3. URL Template Parser (Tarik pesan & media langsung dari Link Telegram).
            4. Smart Follow-Up (Auto fetch oldest users & Sort by Last Seen).
            5. Algoritma Humanized Delay & Batch Resting.
            6. Auto-Retry Queue Loop (Max 3x) untuk grup Slowmode / FloodWait.
            7. MTProto Memory Leak Protection (Auto Connect/Disconnect).
            8. Dynamic Variable Injection ([NAMA], [WAKTU], Spintax).
            9. Dual Sender Engine (MTProto & BOT API Fallback).
====================================================================================
"""

import os
import io
import re
import json
import time
import base64
import random
import asyncio
import logging
import traceback
import aiohttp
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional, Union, Tuple

from fastapi import APIRouter, Request, Depends, HTTPException, BackgroundTasks, Body
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field
import pytz

# Telegram Imports
from telethon import TelegramClient, functions, types, utils
from telethon.sessions import StringSession
from telethon.errors import (
    UserIsBlockedError, 
    UserDeactivatedError, 
    ChatWriteForbiddenError, 
    SlowModeWaitError,
    FloodWaitError,
    PeerIdInvalidError,
    RPCError,
    ChatAdminRequiredError
)

# APScheduler (Masih dipertahankan HANYA untuk operasi Daily/Interval jangka panjang)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

# Supabase Bridge & Core Routers
try:
    from database import supabase
except ImportError:
    supabase = None

from routers.common import render_admin_template, api_success, api_error
from routers.dependencies import get_current_admin

# ==============================================================================
# KELAS 1: ENTERPRISE LOGGING SYSTEM (AUDIT & TRACKING)
# ==============================================================================
class BroadcastLogger:
    """Manajer Log Khusus untuk Engine Broadcast V15.0"""
    def __init__(self):
        self.logger = logging.getLogger("baba.crm.broadcast.engine")
        if not self.logger.handlers:
            handler = logging.StreamHandler()
            # Format log rapi ala enterprise
            formatter = logging.Formatter('%(asctime)s | [ENGINE_DEWA] %(levelname)s - %(message)s')
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)
            self.logger.setLevel(logging.INFO)

    def info(self, msg: str): self.logger.info(msg)
    def warning(self, msg: str): self.logger.warning(msg)
    def error(self, msg: str): self.logger.error(msg)
    def critical(self, msg: str): self.logger.critical(msg)
    
    def debug_job(self, campaign_id: str, msg: str):
        """Logger spesifik per kampanye agar mudah ditelusuri di Terminal"""
        self.logger.info(f"[CAMP:{campaign_id[:8]}] {msg}")
        
    def audit(self, admin_id: int, action: str, details: str):
        """Catat aktivitas krusial admin untuk Audit Trail di Database"""
        self.logger.info(f"[AUDIT TRAIL] Admin ID: {admin_id} | Action: {action} | Details: {details}")
        if supabase:
            try: 
                supabase.table("admins").update({"last_activity_desc": f"{action}: {details}"}).eq("id", admin_id).execute()
            except Exception: 
                pass

logger = BroadcastLogger()

# ==============================================================================
# ROUTER & SYSTEM INITIALIZATION
# ==============================================================================
router = APIRouter(prefix="/admin/crm/broadcast", tags=["CRM Broadcast"])

TELEGRAM_API_ID = int(os.getenv("API_ID", "0"))
TELEGRAM_API_HASH = os.getenv("API_HASH", "")

# Inisialisasi Scheduler Global untuk Engine Dewa
jobstores = { 'default': MemoryJobStore() }
scheduler = AsyncIOScheduler(jobstores=jobstores, timezone=pytz.timezone("Asia/Jakarta"))

@router.on_event("startup")
async def start_engine_dewa():
    """Event Listener saat server FastAPI menyala"""
    logger.info("⚙️ Mempersiapkan Engine Dewa V15.0...")
    
    # 1. Nyalakan APScheduler (Untuk Cronjob Daily/Interval)
    if not scheduler.running:
        scheduler.start()
        logger.info("⚙️ [APScheduler] Mesin Waktu Eksternal ON.")
        
    # 2. Nyalakan Watchdog Database Poller (Penyelamat Jadwal ONCE)
    await CampaignWatchdog.start()

# ==============================================================================
# KELAS 2: PYDANTIC SCHEMAS (VALIDASI DATA FRONTEND)
# ==============================================================================
class BroadcastPayload(BaseModel):
    """Payload Super Fleksibel untuk mengakomodasi request dari UI Broadcast"""
    name: str = Field(..., min_length=3, description="Nama Kampanye")
    sender_type: str = "MTPROTO"
    msg_template_id: str

    target_template_id: Optional[str] = None  
    bot_targets: Optional[List[str]] = None
    
    # Mode Target Cerdas (Normal / Followup)
    target_mode: Optional[str] = "normal"
    followup_limit: Optional[int] = 100
    
    # Penjadwalan
    frequency: str = "ONCE"
    schedule_date: Optional[str] = None
    schedule_time: Optional[str] = None
    interval_days: int = 1
    max_cycles: int = 1
    
    # Human Behavior Config
    delay_min: float = 2.0
    delay_max: float = 5.0
    rest_batch: int = 50
    rest_duration_min: int = 5

class TogglePayload(BaseModel):
    status: str

# ==============================================================================
# KELAS 3: ENTERPRISE UTILITY & DATA ACCESS (DAL)
# ==============================================================================
class DBExecutor:
    """Eksekutor Database Background dengan Retry Khusus untuk Task Berjalan.
       Mencegah crash aplikasi jika API Supabase mengalami timeout sesaat."""
    @staticmethod
    async def run(func, *args, max_retries: int = 3, delay: float = 1.0, **kwargs):
        for attempt in range(max_retries):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                if attempt == max_retries - 1:
                    logger.error(f"DB Error Fatal di Background Task: {e}")
                    raise e
                logger.warning(f"DB Timeout, retrying in {delay}s... (Attempt {attempt+1})")
                await asyncio.sleep(delay)
                delay *= 2

class TelethonErrorHandler:
    """Penanganan Spesifik Error MTProto dari Telegram"""
    @staticmethod
    def parse(e: Exception) -> Tuple[str, bool]:
        """
        Engine penganalisa error Telegram.
        Return: (Pesan Error User Friendly, Apakah Boleh Lanjut/Continue ke Target Berikutnya?)
        """
        err_str = str(e).lower()
        if isinstance(e, FloodWaitError):
            return f"Terkena Limit Telegram. Harus menunggu {e.seconds} detik.", False
        elif isinstance(e, SlowModeWaitError):
            return f"Grup Slowmode. Harus menunggu {e.seconds} detik.", False
        elif isinstance(e, UserIsBlockedError):
            return "User memblokir akun kita.", True
        elif isinstance(e, UserDeactivatedError):
            return "Akun user sudah dihapus/deactivated.", True
        elif isinstance(e, ChatWriteForbiddenError):
            return "Tidak ada akses mengirim pesan ke chat ini.", True
        elif isinstance(e, ChatAdminRequiredError):
            return "Membutuhkan akses admin di grup/channel ini.", True
        elif isinstance(e, PeerIdInvalidError):
            return "ID Target tidak valid atau belum pernah di-cache.", True
        elif isinstance(e, RPCError):
            return f"Telegram API Error: {str(e)}", True
        elif isinstance(e, ValueError) and "cannot find any entity" in err_str:
            return "Entitas tidak ditemukan. Target invalid.", True
        elif "nobody is using this username" in err_str:
            return "Username tidak ditemukan di server Telegram.", True
        return f"Error tidak dikenal: {str(e)}", True

# ==============================================================================
# KELAS 4: MESSAGE RENDERER & MEDIA PARSER
# ==============================================================================
class MessageRenderer:
    """Engine perender pesan dinamis (Variable Injection & Spintax)"""
    
    @staticmethod
    def render(template_text: str, entity_name: str = "") -> str:
        """
        Mengganti variabel seperti [NAMA] dan [WAKTU] menjadi spesifik per target.
        Membuat pesan terasa lebih personal dan natural.
        """
        if not template_text: return ""
        result = template_text
        
        # 1. Inject Waktu (Time-based greeting) - WIB
        current_hour = datetime.now(pytz.timezone("Asia/Jakarta")).hour
        if 5 <= current_hour < 11: waktu = "pagi"
        elif 11 <= current_hour < 15: waktu = "siang"
        elif 15 <= current_hour < 18: waktu = "sore"
        else: waktu = "malam"
        
        # Format lama: {name}, Format baru: [NAMA]
        result = result.replace("[WAKTU]", waktu)
        result = result.replace("{WAKTU}", waktu)
        
        # 2. Inject Nama (Personalization)
        nama_panggilan = "Kak"
        if entity_name and entity_name.strip():
            words = entity_name.split()
            nama_panggilan = words[0] if len(words) > 0 else "Kak"
            
        result = result.replace("[NAMA]", nama_panggilan)
        result = result.replace("{name}", nama_panggilan)
        
        # 3. Spintax Processing {Halo|Hai|Hi}
        spintax_pattern = re.compile(r'\{([^{}]+)\}')
        while True:
            match = spintax_pattern.search(result)
            if not match:
                break
            # Jika mengandung format {name}, abaikan
            if match.group(1).lower() == 'name':
                break
                
            options = match.group(1).split('|')
            chosen = random.choice(options)
            result = result[:match.start()] + chosen + result[match.end():]
            
        return result

    @staticmethod
    def parse_telegram_link(link: str) -> Tuple[Optional[Union[int, str]], Optional[int]]:
        """
        Mesin bedah link Telegram. Support public (username) & private (c/1234).
        Return: (Entity/Chat_ID, Message_ID)
        """
        if not link: return None, None
        link = link.replace('https://t.me/', '').replace('http://t.me/', '').replace('t.me/', '')
        parts = [p for p in link.split('/') if p.strip()]

        if not parts: return None, None

        # Private Group / Channel
        if parts[0] == 'c' and len(parts) >= 3:
            chat_id_str = parts[1]
            msg_id_str = parts[-1]
            try:
                chat_id = int(f"-100{chat_id_str}")
                msg_id = int(msg_id_str)
                return chat_id, msg_id
            except: return None, None

        # Public Username
        elif len(parts) >= 2:
            username = parts[0]
            msg_id_str = parts[-1]
            try:
                msg_id = int(msg_id_str)
                return username, msg_id
            except: return None, None

        return None, None

# ==============================================================================
# KELAS 5: TARGET RESOLVER ENGINE
# ==============================================================================
class TargetResolver:
    """Engine pemecah ID Target Cerdas (Commander Bulk ID & Group Scraping)"""
    
    @staticmethod
    async def resolve(client: TelegramClient, target_content: str, campaign_id: str, admin_id: int) -> List[Dict[str, Any]]:
        """
        Return List of Dict: [{'id': 123, 'name': 'Budi', 'retry': 0}, ...]
        """
        targets_queue = []
        raw_content = target_content.strip()
        
        if not raw_content:
            return targets_queue

        # ---------------------------------------------------------
        # KASUS A: SMART FOLLOW-UP (Dynamic Scrape from Client)
        # ---------------------------------------------------------
        if raw_content.startswith("DYNAMIC_FOLLOWUP"):
            parts = raw_content.split(":")
            # Ambil limit sesuai yang diset Admin (Bukan default 100 lagi)
            limit = int(parts[1]) if len(parts) > 1 else 100
            logger.info(f"🔍 [RESOLVER] Memicu DYNAMIC_FOLLOWUP. Menyisir {limit} user terlama...")
            
            try:
                dialogs = await client.get_dialogs()
                # Ambil User Pribadi (Bukan Bot, Bukan Grup)
                users = [d for d in dialogs if d.is_user and not d.entity.bot]
                # Sort dari Date paling lama (Ascending)
                users.sort(key=lambda x: x.date)
                
                for u in users[:limit]:
                    user_name = getattr(u.entity, 'first_name', 'Kakak') or 'Kakak'
                    # FIX PERKODEAN: Jangan pakai str(u.id), biarkan INTEGER!
                    targets_queue.append({'id': u.id, 'name': user_name, 'retry': 0})
                
                # Update cache total target di DB biar UI update
                await DBExecutor.run(lambda: supabase.table("crm_campaigns").update({"total_target_cache": len(targets_queue)}).eq("id", campaign_id).execute())
                return targets_queue
            except Exception as e:
                logger.error(f"Gagal Dynamic Followup: {e}")
                return targets_queue

        # ---------------------------------------------------------
        # KASUS B: COMMANDER BULK LIST ID (Pisah Koma/Enter)
        # ---------------------------------------------------------
        if ',' in raw_content or '\n' in raw_content:
            parts = re.split(r'[\n,]+', raw_content)
            for p in parts:
                p = p.strip()
                if not p: continue
                # Deteksi format Forum/Topic -> CHAT_ID:TOPIC_ID
                if ':' in p:
                    targets_queue.append({'id': p, 'name': 'Kak', 'retry': 0})
                else:
                    try: targets_queue.append({'id': int(p), 'name': 'Kak', 'retry': 0})
                    except: targets_queue.append({'id': p, 'name': 'Kak', 'retry': 0})
            
            logger.info(f"🎯 [RESOLVER] Bulk ID terdeteksi. Ditemukan {len(targets_queue)} target.")
            return targets_queue

        # ---------------------------------------------------------
        # KASUS C: SINGLE TARGET / GROUP SCRAPE
        # ---------------------------------------------------------
        try:
            entity = await client.get_entity(raw_content)
            if hasattr(entity, 'broadcast') and entity.broadcast:
                # Target Channel
                targets_queue.append({'id': raw_content, 'name': 'Channel', 'retry': 0})
            elif hasattr(entity, 'megagroup') or getattr(entity, 'is_group', False):
                # Target Group -> Scrape Member Aktif
                logger.info(f"🎯 [RESOLVER] Ekstrak audiens Grup {raw_content}...")
                count = 0
                async for user in client.iter_participants(entity):
                    if not user.bot and not user.deleted:
                        fname = getattr(user, 'first_name', 'Kak') or 'Kak'
                        targets_queue.append({'id': user.id, 'name': fname, 'retry': 0})
                        count += 1
                        if count > 5000: break # Safety limit hard-cap
                logger.info(f"🎯 [RESOLVER] Berhasil ekstrak {len(targets_queue)} member.")
            else:
                # Personal User
                fname = getattr(entity, 'first_name', 'Kak') or 'Kak'
                targets_queue.append({'id': raw_content, 'name': fname, 'retry': 0})
        except Exception as e:
            logger.warning(f"⚠️ [RESOLVER] Entitas '{raw_content}' unresolved: {e}. Fallback ke raw input.")
            try: targets_queue.append({'id': int(raw_content), 'name': 'Kak', 'retry': 0})
            except: targets_queue.append({'id': raw_content, 'name': 'Kak', 'retry': 0})

        return targets_queue

# ==============================================================================
# KELAS 6: WATCHDOG POLLING ENGINE (NATIVE CRONJOB FIX)
# ==============================================================================
class CampaignWatchdog:
    """
    Inilah PENYELAMAT NYA! 
    Sistem Cronjob native berbasis Polling Database yang kebal dari restart.
    Tugasnya hanya 1: Cek DB setiap 20 detik, kalau ada jadwal waktunya tiba -> Tembak!
    """
    _is_running = False
    _lock = asyncio.Lock()

    @classmethod
    async def start(cls):
        if cls._is_running: return
        cls._is_running = True
        logger.info("👁️ [WATCHDOG] Mesin Pengecek Jadwal (Database Poller) Dihidupkan!")
        asyncio.create_task(cls._loop())

    @classmethod
    async def _loop(cls):
        while cls._is_running:
            try:
                if supabase:
                    # Ambil waktu sekarang di zona WIB
                    wib_tz = pytz.timezone("Asia/Jakarta")
                    now_wib = datetime.now(wib_tz)
                    now_iso = now_wib.isoformat()

                    # Query: Cari Kampanye yang PENDING dan jadwalnya <= waktu sekarang
                    res = await DBExecutor.run(
                        lambda: supabase.table("crm_campaigns").select("id", "scheduled_at")\
                            .eq("status", "PENDING")\
                            .lte("scheduled_at", now_iso)\
                            .execute()
                    )

                    pending_campaigns = res.data or []
                    
                    for camp in pending_campaigns:
                        camp_id = camp['id']
                        
                        # 1. Flag jadi PROCESSING agar Watchdog berikutnya tidak double hit
                        await DBExecutor.run(
                            lambda: supabase.table("crm_campaigns").update({"status": "PROCESSING"}).eq("id", camp_id).execute()
                        )
                        
                        logger.info(f"⏰ [WATCHDOG] Waktu Tiba! Memicu Kampanye ID: {camp_id[:8]}...")
                        
                        # 2. Eksekusi tugas (Lepas ke thread background)
                        asyncio.create_task(execute_broadcast_task(camp_id))
                        
                        # Jeda 1 detik antar trigger kampanye jika barengan
                        await asyncio.sleep(1)
            
            except Exception as e:
                logger.error(f"❌ [WATCHDOG ERROR] {e}")
            
            # Watchdog beristirahat 20 detik sebelum patroli lagi
            await asyncio.sleep(20)

# ==============================================================================
# KELAS 7: THE MAIN SENDER CORE (BROADCAST WORKER)
# ==============================================================================
class BroadcastEngine:
    """Orkestrator Utama yang bertugas mengeksekusi kampanye broadcast di background"""
    
    @staticmethod
    async def is_campaign_active(campaign_id: str) -> str:
        """Interceptor: Memeriksa state realtime di Database jika admin mem-PAUSE kampanye"""
        try:
            res = await DBExecutor.run(lambda: supabase.table("crm_campaigns").select("status").eq("id", campaign_id).execute())
            if res.data:
                return res.data[0]["status"]
            return "DELETED"
        except:
            return "UNKNOWN"

    @staticmethod
    async def execute_task(campaign_id: str):
        """
        FUNGSI DEWA: Mengurus penarikan data, pengiriman, human-delay, pause, stop, dan reporting.
        """
        logger.debug_job(campaign_id, "🔥 ENGINE DEWA START: Mempersiapkan aset kampanye...")
        if not supabase:
            logger.critical("Database Offline. Aborting task...")
            return

        client = None
        try:
            # 1. PULL DATA KAMPANYE DARI DB
            camp_res = await DBExecutor.run(lambda: supabase.table("crm_campaigns").select("*").eq("id", campaign_id).execute())
            if not camp_res.data:
                logger.debug_job(campaign_id, "Data kampanye tidak ditemukan / sudah dihapus. Aborting.")
                return
            campaign = camp_res.data[0]
            admin_id = campaign.get("created_by")

            # 2. PULL ASET TEMPLATE (TARGET & PESAN)
            target_tpl_res = await DBExecutor.run(lambda: supabase.table("crm_templates").select("content").eq("id", campaign["target_template_id"]).execute())
            
            # 🔥 FIX 1: Tarik kolom 'content' DAN 'source_link' sekalian!
            msg_tpl_res = await DBExecutor.run(lambda: supabase.table("crm_templates").select("content, source_link").eq("id", campaign["message_template_id"]).execute())
            
            if not target_tpl_res.data or not msg_tpl_res.data:
                raise Exception("Template Pesan atau Target Audiens tidak ditemukan di DB.")
                
            raw_target_content = target_tpl_res.data[0]["content"]
            raw_msg_content = msg_tpl_res.data[0]["content"]
            source_link_val = msg_tpl_res.data[0].get("source_link") # Ambil URL medianya

            # 3. AKTIVASI MESIN MTPROTO
            session_id = campaign.get("session_id")
            if not session_id:
                raise Exception("Tidak ada akun MTProto yang di-assign untuk kampanye ini.")
                
            sess_res = await DBExecutor.run(lambda: supabase.table("crm_telegram_sessions").select("*").eq("id", session_id).execute())
            if not sess_res.data or sess_res.data[0]["status"] != "active":
                raise Exception("Sesi MTProto tidak aktif / putus.")
                
            session_string = sess_res.data[0]["session_string"]
            
            # [MEMORY LEAK PROTECTION] Gunakan sequential_updates
            client = TelegramClient(StringSession(session_string), TELEGRAM_API_ID, TELEGRAM_API_HASH, sequential_updates=True)
            await client.connect()
            
            if not await client.is_user_authorized():
                raise Exception("Kredensial Telegram kadaluarsa. Sistem ditolak.")

            # 4. RESOLVE TARGET AUDIENS DENGAN TARGET RESOLVER
            targets_queue = await TargetResolver.resolve(client, raw_target_content, campaign_id, admin_id)
            if not targets_queue:
                raise Exception("Array target kosong. Tidak ada entitas untuk dikirimi pesan.")

            # 5. PERSIAPAN ENGINE PESAN (Cek Lampiran Media)
            is_url_mode = bool(source_link_val and str(source_link_val).startswith("http"))
            source_chat_id = None
            source_msg_id = None
            cloud_msg_obj = None
            
            if is_url_mode:
                logger.debug_job(campaign_id, "🔗 Lampiran Media Terdeteksi! Ekstrak source dari Telegram...")
                source_chat_id, source_msg_id = MessageRenderer.parse_telegram_link(str(source_link_val))
                
                if source_chat_id and source_msg_id:
                    try:
                        # Wajib fetch pesan aslinya buat ditarik Media/Gambarnya
                        src_entity = await client.get_input_entity(source_chat_id)
                        extracted_msg = await client.get_messages(src_entity, ids=source_msg_id)
                        if extracted_msg:
                            cloud_msg_obj = extracted_msg
                            logger.debug_job(campaign_id, "✅ Media asli berhasil di-load dari server Telegram.")
                        else:
                            raise Exception("Pesan URL kosong / dihapus di server.")
                    except Exception as e:
                        logger.warning(f"Gagal Load Cloud Message Media: {e}")

            # 6. MUAT KONFIGURASI HUMAN BEHAVIOR
            h_config = campaign.get("humanized_config", {})
            delay_min = float(h_config.get("delay_min", campaign.get("delay_min", 2.0)))
            delay_max = float(h_config.get("delay_max", campaign.get("delay_max", 5.0)))
            batch_size = int(h_config.get("rest_batch", campaign.get("batch_size", 50)))
            rest_duration = int(h_config.get("rest_duration_min", campaign.get("rest_duration", 300)))
            
            # Jika rest_duration masih dalam bentuk menit, ubah ke detik
            if rest_duration < 60: rest_duration = rest_duration * 60 

            success_count = 0
            failed_count = 0
            batch_counter = 0

            # 7. FILTER ANTI-DOUBLE SEND (Lanjutkan dari siklus yg berjalan)
            cycle = int(campaign.get("current_cycle", 1))
            sent_res = await DBExecutor.run(
                lambda: supabase.table("crm_blast_logs")\
                                .select("target_id")\
                                .eq("campaign_id", campaign_id)\
                                .eq("status", "SUCCESS")\
                                .eq("cycle_number", cycle)\
                                .execute()
            )
            already_sent_ids = [s["target_id"] for s in (sent_res.data or [])]
            
            # Buang target yang sudah dikirim di siklus ini
            pending_targets = [t for t in targets_queue if str(t['id']) not in already_sent_ids]

            logger.debug_job(campaign_id, f"Aset Siap. Sisa antrean: {len(pending_targets)} target.")

            # ====================================================================
            # 8. PERULANGAN EKSEKUSI PENGIRIMAN (THE BATTLEFIELD LOOP DUAL ENGINE)
            # ====================================================================
            bot_token = os.getenv("BOT_TOKEN")
            
            async with aiohttp.ClientSession() as http_session:
                while pending_targets:
                    # A. INTERCEPTOR (Cek Status UI)
                    current_state = await BroadcastEngine.is_campaign_active(campaign_id)
                    if current_state == "PAUSED":
                        logger.debug_job(campaign_id, "⏸️ INTERCEPTOR: Kampanye di-PAUSE. Menghentikan tugas...")
                        return 
                    if current_state == "STOPPED" or current_state == "DELETED":
                        logger.debug_job(campaign_id, "🛑 INTERCEPTOR: Kampanye di-STOP. Menggugurkan tugas...")
                        return

                    # B. BATCH RESTING (Pencegah Banned Telegram)
                    if batch_counter > 0 and batch_counter % batch_size == 0:
                        logger.debug_job(campaign_id, f"😴 LIMIT BATCH ({batch_size}). Beristirahat {rest_duration} detik...")
                        await DBExecutor.run(lambda: supabase.table("crm_campaigns").update({"status": "RESTING"}).eq("id", campaign_id).execute())
                        
                        for _ in range(rest_duration):
                            state_check = await BroadcastEngine.is_campaign_active(campaign_id)
                            if state_check in ["PAUSED", "STOPPED", "DELETED"]: return
                            await asyncio.sleep(1)
                            
                        await DBExecutor.run(lambda: supabase.table("crm_campaigns").update({"status": "PROCESSING"}).eq("id", campaign_id).execute())

                    # C. POP ANTRIAN TERATAS & PERKODEAN TARGET
                    current_target = pending_targets.pop(0)
                    t_id = current_target['id']
                    t_name = current_target['name']
                    t_retry = current_target['retry']

                    # Kembalikan tipe data ke Integer agar Telethon tidak ngira ini Username
                    peer_id = t_id
                    reply_to = None
                    if isinstance(t_id, str):
                        if ':' in t_id:
                            parts = t_id.split(':')
                            peer_id = int(parts[0]) if parts[0].lstrip('-').isdigit() else parts[0]
                            reply_to = int(parts[1])
                        elif t_id.lstrip('-').isdigit():
                            peer_id = int(t_id)

                    error_msg = None
                    is_success = False

                    # D. EKSEKUSI TELEGRAM (3-LAYER SMART FALLBACK + BOT API + TABRAK LARI)
                    try:
                        pid = peer_id
                        final_text = MessageRenderer.render(raw_msg_content, t_name)
                        
                        # -------------------------------------------------------------
                        # FUNGSI INTERNAL: PENGIRIMAN VIA BOT API
                        # -------------------------------------------------------------
                        async def send_via_bot():
                            if not bot_token: raise Exception("BOT_TOKEN tidak disetting di .env")
                            url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
                            payload = {"chat_id": pid, "text": final_text, "parse_mode": "Markdown"}
                            if reply_to: payload["reply_to_message_id"] = reply_to
                            
                            async with http_session.post(url, json=payload) as resp:
                                res_data = await resp.json()
                                if not res_data.get("ok"):
                                    raise Exception(f"Bot Error: {res_data.get('description')}")

                        # -------------------------------------------------------------
                        # JALUR 1: JIKA SENDER TYPE MEMANG DI-SET BOT
                        # -------------------------------------------------------------
                        if campaign.get('sender_type') == 'BOT':
                            await send_via_bot()
                            is_success = True
                            success_count += 1
                            logger.info(f"✅ [CAMP:{campaign_id[:8]}] Terkirim via BOT -> ID: {pid}")
                            
                        # -------------------------------------------------------------
                        # JALUR 2: JIKA SENDER MTPROTO (DENGAN 3-LAYER HASH & AUTO-FALLBACK BOT)
                        # -------------------------------------------------------------
                        else:
                            try:
                                # LAYER 0: Tarik amunisi (Hash & Username) dari database customers
                                db_hash = None
                                db_username = None
                                try:
                                    user_data = await DBExecutor.run(lambda: supabase.table("customers").select("access_hash, username").eq("telegram_id", pid).execute())
                                    if user_data.data:
                                        hash_val = user_data.data[0].get("access_hash")
                                        db_hash = int(hash_val) if hash_val else None
                                        db_username = user_data.data[0].get("username")
                                except: pass

                                peer_entity = None
                                
                                # LAYER 1: BYPASS CACHE PAKAI ACCESS HASH DARI DB
                                from telethon.tl.types import InputPeerUser
                                if db_hash:
                                    try:
                                        peer_entity = InputPeerUser(user_id=pid, access_hash=db_hash)
                                        logger.info(f"🔑 [CAMP:{campaign_id[:8]}] Layer 1: Menggunakan Access Hash DB untuk ID {pid}")
                                    except Exception: pass

                                # LAYER 2: FALLBACK PAKAI USERNAME JIKA HASH KOSONG
                                if not peer_entity and db_username:
                                    try:
                                        peer_entity = await client.get_input_entity(db_username)
                                        logger.info(f"🔍 [CAMP:{campaign_id[:8]}] Layer 2: Fallback ke Username (@{db_username}) untuk ID {pid}")
                                    except Exception: pass
                                    
                                # LAYER 3: RAW ID (Mengandalkan Telethon Cache)
                                if not peer_entity:
                                    try: peer_entity = await client.get_input_entity(pid)
                                    except: peer_entity = pid # Ultimate raw fallback
                                
                                # Simulasi Ngetik
                                try:
                                    async with client.action(peer_entity, 'typing'):
                                        await asyncio.sleep(random.uniform(1.0, 2.5))
                                except: pass

                                # Tembak MTProto
                                if cloud_msg_obj:
                                    await client.send_message(peer_entity, cloud_msg_obj, reply_to=reply_to)
                                elif is_url_mode and source_chat_id and source_msg_id:
                                    source_entity = await client.get_entity(source_chat_id)
                                    await client.forward_messages(peer_entity, source_msg_id, source_entity)
                                else:
                                    await client.send_message(peer_entity, final_text, reply_to=reply_to)
                                    
                                is_success = True
                                success_count += 1
                                logger.info(f"✅ [CAMP:{campaign_id[:8]}] Terkirim via MTPROTO -> ID: {pid}")

                            except Exception as ve:
                                # CATCH ALL UNTUK ENTITY ERROR AGAR BISA FALLBACK KE BOT
                                err_str = str(ve).lower()
                                if "find the input entity" in err_str or "cannot find" in err_str or "hash" in err_str or "peer" in err_str:
                                    logger.warning(f"⚠️ MTProto tidak kenal ID {pid} (Hash/Username invalid). Auto-Fallback ke BOT API...")
                                    try:
                                        await send_via_bot()
                                        is_success = True
                                        success_count += 1
                                        logger.info(f"✅ [CAMP:{campaign_id[:8]}] Terkirim via BOT FALLBACK -> ID: {pid}")
                                    except Exception as bot_err:
                                        raise Exception(f"MTProto & Bot sama-sama gagal: {str(bot_err)}")
                                else:
                                    raise ve 

                    except SlowModeWaitError:
                        if t_retry < 2: 
                            logger.warning(f"🐌 SlowMode terdeteksi di {t_id}. Masuk antrean ulang (Retry {t_retry+1}).")
                            current_target['retry'] += 1
                            pending_targets.append(current_target) # Lempar ke paling belakang
                            error_msg = None 
                        else:
                            error_msg = "Gagal Limit Slowmode (Max Retry)"
                            
                    except FloodWaitError as e:
                        logger.warning(f"🌊 FLOOD WAIT: Telegram limit. Tidur paksa {e.seconds} detik...")
                        await DBExecutor.run(lambda: supabase.table("crm_campaigns").update({"status": "RESTING"}).eq("id", campaign_id).execute())
                        await asyncio.sleep(e.seconds + 2)
                        await DBExecutor.run(lambda: supabase.table("crm_campaigns").update({"status": "PROCESSING"}).eq("id", campaign_id).execute())
                        
                        pending_targets.insert(0, current_target) # Kembalikan ke pucuk
                        error_msg = None
                        
                    except Exception as ex:
                        err_str = str(ex).lower()
                        
                        # LOGIKA TABRAK LARI (SKIP & MOVE ON)
                        if "too many requests" in err_str:
                            logger.warning(f"🌊 RATE LIMIT: Telegram nolak ngirim ke {t_id}. Tidur 45 detik, lalu SKIP target ini.")
                            await DBExecutor.run(lambda: supabase.table("crm_campaigns").update({"status": "RESTING"}).eq("id", campaign_id).execute())
                            await asyncio.sleep(45) 
                            await DBExecutor.run(lambda: supabase.table("crm_campaigns").update({"status": "PROCESSING"}).eq("id", campaign_id).execute())
                            
                            # JANGAN dimasukin ke antrean lagi! Langsung catat gagal!
                            error_msg = "Gagal Limit: Too Many Requests (Di-Skip)"
                            failed_count += 1
                            logger.error(f"❌ [CAMP:{campaign_id[:8]}] Gagal -> ID: {t_id} | Alasan: {error_msg}")
                            
                        else:
                            # Kalau error lain (diblokir, deactived, dll)
                            parsed_err, can_continue = TelethonErrorHandler.parse(ex)
                            error_msg = parsed_err
                            failed_count += 1
                            logger.error(f"❌ [CAMP:{campaign_id[:8]}] Gagal -> ID: {t_id} | Alasan: {error_msg}")
                            
                            if not can_continue:
                                logger.critical("🛑 FATAL: Menghentikan kampanye darurat akibat pelanggaran batas Telegram!")
                                await DBExecutor.run(lambda: supabase.table("crm_campaigns").update({"status": "FAILED", "error_message": error_msg}).eq("id", campaign_id).execute())
                                return

                    # E. CATAT LOG DATABASE
                    if error_msg is not None or is_success:
                        log_data = {
                            "campaign_id": campaign_id,
                            "target_id": str(t_id),
                            "status": "SUCCESS" if is_success else "FAILED",
                            "error_message": error_msg,
                            "sent_at": datetime.now(timezone.utc).isoformat(),
                            "cycle_number": cycle
                        }
                        try: await DBExecutor.run(lambda: supabase.table("crm_blast_logs").insert(log_data).execute())
                        except: pass

                    # F. JITTER HUMANIZED DELAY ANTAR PESAN
                    batch_counter += 1
                    if batch_counter < len(targets_queue):
                        delay = random.uniform(delay_min, delay_max)
                        await asyncio.sleep(delay)

            # ====================================================================
            # 9. POST-EXECUTION (Siklus Kelar 100%)
            # ====================================================================
            logger.debug_job(campaign_id, f"🎉 EKSEKUSI SELESAI. Sukses: {success_count}, Gagal: {failed_count}.")
            
            freq = campaign.get("frequency", "ONCE")
            max_cycles = int(campaign.get("max_cycles", 1))
            
            if freq != "ONCE" and cycle < max_cycles:
                # Persiapan Siklus Berikutnya
                next_cycle = cycle + 1
                
                # Hitung waktu jadwal berikutnya
                wib_tz = pytz.timezone("Asia/Jakarta")
                now_wib = datetime.now(wib_tz)
                next_schedule = now_wib + timedelta(days=int(campaign.get("interval_days", 1)))
                
                # Update Jadwal Baru ke Database (Ini kunci agar Watchdog nangkap siklus berikutnya)
                await DBExecutor.run(lambda: supabase.table("crm_campaigns").update({
                    "status": "PENDING", 
                    "current_cycle": next_cycle,
                    "scheduled_at": next_schedule.isoformat()
                }).eq("id", campaign_id).execute())
                
                logger.debug_job(campaign_id, f"Siklus {cycle} selesai. Menunggu jadwal Siklus {next_cycle} pada {next_schedule.strftime('%d-%m-%Y %H:%M:%S')}...")
            else:
                # Selesai Total (ONCE atau sudah mencapai batas cycle)
                await DBExecutor.run(lambda: supabase.table("crm_campaigns").update({"status": "COMPLETED"}).eq("id", campaign_id).execute())
                logger.debug_job(campaign_id, "Seluruh jadwal Kampanye COMPLETED 100%.")

        except Exception as fatal_e:
            logger.critical(f"FATAL CRASH di Engine Dewa Kampanye {campaign_id}: {str(fatal_e)}")
            traceback.print_exc()
            if supabase:
                try: await DBExecutor.run(lambda: supabase.table("crm_campaigns").update({"status": "FAILED", "error_message": str(fatal_e)}).eq("id", campaign_id).execute())
                except: pass
                
        finally:
            if client:
                await client.disconnect()
                logger.info(f"🔌 [CLEANUP] Sesi MTProto Kampanye {campaign_id[:8]} diputus dengan aman.")

# ==============================================================================
# WRAPPER BACKGROUND TASK
# ==============================================================================
async def execute_broadcast_task(campaign_id: str):
    """Bridge Asynchronous Murni untuk Watchdog/Background Tasks"""
    try:
        await BroadcastEngine.execute_task(campaign_id)
    except Exception as e:
        logger.error(f"❌ [CRONJOB FATAL] Gagal mengeksekusi trigger: {e}")

# ==============================================================================
# FASTAPI ROUTE HANDLERS (WEB & API CONTROLLERS)
# ==============================================================================
@router.get("", response_class=HTMLResponse)
async def broadcast_page(request: Request, admin=Depends(get_current_admin)):
    """Menampilkan Dashboard UI Broadcast"""
    return render_admin_template(request, "crm/broadcast.html", admin_data=admin)

# ------------------------------------------------------------------------------
# 1. API: INIT DATA DASHBOARD (Realtime Progress)
# ------------------------------------------------------------------------------
@router.get("/api/init")
async def init_broadcast_data(admin=Depends(get_current_admin)):
    """Menyediakan data Real-Time untuk Dashboard Commander HTML"""
    if not supabase: return api_error("Database offline", 503)
    admin_id = admin.get("admin_id")
    try:
        # Panggil DB secara native untuk render HTML UI yang ngebut
        camp_res = supabase.table("crm_campaigns").select("*").eq("created_by", admin_id).order("created_at", desc=True).execute()
        tpl_res = supabase.table("crm_templates").select("id, name, type, content").eq("created_by", admin_id).execute()
        
        messages = [t for t in (tpl_res.data or []) if t['type'] == 'MESSAGE']
        targets = [t for t in (tpl_res.data or []) if t['type'] == 'TARGET_GROUP']

        bot_cust_res = await DBExecutor.run(
            lambda: supabase.table("customers").select("*").eq("source", "bot").execute()
        )
        bot_customers = bot_cust_res.data or []

        # Hitung Metrics Stats Atas
        total_sent = supabase.table("crm_blast_logs").select("id", count="exact").eq("status", "SUCCESS").execute().count or 0
        total_failed = supabase.table("crm_blast_logs").select("id", count="exact").eq("status", "FAILED").execute().count or 0
        in_queue = supabase.table("crm_campaigns").select("id", count="exact").in_("status", ["PENDING", "PROCESSING", "RESTING", "SCHEDULED"]).execute().count or 0

        # Assembly Final Data
        final_campaigns = []
        for c in (camp_res.data or []):
            msg_name = next((t['name'] for t in messages if t['id'] == c.get('message_template_id')), "Deleted Template")
            
            # Logika Target Deskripsi
            if "DYNAMIC_FOLLOWUP" in c.get('target_template_id', ''):
                tgt_name = "Smart Follow-Up (Dynamic)"
                total_target = c.get('total_target_cache', 100) 
            else:
                tgt_name = next((t['name'] for t in targets if t['id'] == c.get('target_template_id')), "Deleted Target")
                tgt_content = next((t['content'] for t in targets if t['id'] == c.get('target_template_id')), "")
                total_target = len([i for i in tgt_content.split(',') if i.strip()])
            
            # Progress bar hitungan akurat
            logs_count = supabase.table("crm_blast_logs").select("id", count="exact").eq("campaign_id", c['id']).eq("status", "SUCCESS").execute().count or 0
            
            progress = min(round((logs_count / total_target * 100), 1), 100) if total_target > 0 else 0
            if c.get('status') == 'COMPLETED': progress = 100

            final_campaigns.append({
                **c,
                "msg_template_name": msg_name,
                "target_desc": tgt_name,
                "progress": progress,
                "sent_count": logs_count,
                "total_target": total_target
            })

        return api_success(data={
            "campaigns": final_campaigns,
            "messages": messages,
            "targets": targets,
            "bot_customers": bot_customers,
            "metrics": {"total_sent": total_sent, "total_failed": total_failed, "in_queue": in_queue}
        })
    except Exception as e:
        logger.error(f"❌ [INIT ERROR]: {e}")
        return api_error(f"Gagal muat data: {e}", 500)

# ------------------------------------------------------------------------------
# 2. API: LAUNCH CAMPAIGN (DENGAN WATCHDOG)
# ------------------------------------------------------------------------------
@router.post("/api/launch")
async def launch_campaign(payload: BroadcastPayload, bg_tasks: BackgroundTasks, admin=Depends(get_current_admin)):
    """API Pembuatan Broadcast Manual dari Halaman Broadcast UI"""
    if not supabase: return api_error("Database offline", 503)
    
    admin_id = admin.get("admin_id")
    wib_tz = pytz.timezone("Asia/Jakarta")
    logger.audit(admin_id, "INIT_LAUNCH", f"Mempersiapkan kampanye: {payload.name}")

    try:
        # A. Setup Target Template
        target_id = payload.target_template_id
        
        if payload.target_mode == 'followup':
            # 1. Logic Auto Follow-up (Udah bener)
            limit_followup = payload.followup_limit if payload.followup_limit else 100
            logger.info(f"🤖 Smart Follow-Up terdeteksi! Mengunci limit ke: {limit_followup} users...")
            
            res_tpl = await DBExecutor.run(
                lambda: supabase.table("crm_templates").insert({
                    "name": f"Smart Follow-Up ({limit_followup} Users)",
                    "type": "TARGET_GROUP",
                    "content": f"DYNAMIC_FOLLOWUP:{limit_followup}",
                    "created_by": admin_id
                }).execute()
            )
            target_id = res_tpl.data[0]['id']
            logger.info(f"✅ Template Follow-Up {limit_followup} target berhasil dibuat (ID: {target_id}).")
            
        elif payload.sender_type == 'BOT' and payload.bot_targets:
            # 2. 🔥 FIX: Logic Target Centangan BOT API
            # Ubah list ID centangan jadi satu string panjang pisah koma
            logger.info(f"🤖 Target Bot terdeteksi! Menyimpan {len(payload.bot_targets)} user ke template...")
            target_list_string = ",".join(payload.bot_targets)
            
            # Bikin template dadakan ke database persis kayak follow-up
            res_tpl = await DBExecutor.run(
                lambda: supabase.table("crm_templates").insert({
                    "name": f"Bot Custom Targets ({len(payload.bot_targets)} Users)",
                    "type": "TARGET_GROUP",
                    "content": target_list_string,
                    "created_by": admin_id
                }).execute()
            )
            target_id = res_tpl.data[0]['id']
            logger.info(f"✅ Template Bot Custom berhasil dibuat (ID: {target_id}).")

        # Keamanan terakhir biar nggak lolos kalau kosong
        if not target_id:
            return api_error("Target audiens kosong! Harap pilih target terlebih dahulu.", 400)

        # B. Setup Database Status (TIMEZONE KETAT WIB)
        sess_res = supabase.table("crm_telegram_sessions").select("id").eq("admin_id", admin_id).eq("status", "active").execute()
        if not sess_res.data:
            return api_error("Akun Telegram (MTProto) belum dihubungkan. Cek menu Profile.")
        
        session_id = sess_res.data[0]["id"] # Sekarang variabel ini sudah ada isinya!

        # 2. Setup Waktu (WIB)
        schedule_datetime_str = None
        now_wib = datetime.now(wib_tz)
        run_date = now_wib
        is_scheduled = False

        if payload.frequency != 'ONCE' or (payload.schedule_date and payload.schedule_time):
            schedule_datetime_str = f"{payload.schedule_date}T{payload.schedule_time}:00"
            naive_date = datetime.strptime(schedule_datetime_str, "%Y-%m-%dT%H:%M:%S")
            target_date = wib_tz.localize(naive_date)

            if payload.frequency != 'ONCE' or target_date > now_wib + timedelta(minutes=1):
                run_date = target_date
                is_scheduled = True
            else:
                is_scheduled = False

        new_camp = {
            "campaign_name": payload.name,
            "sender_type": payload.sender_type,
            "session_id": session_id,
            "message_template_id": payload.msg_template_id,
            "target_template_id": target_id,
            # Jika is_scheduled=True, Watchdog yang akan menangkapnya!
            "status": "PENDING" if is_scheduled else "PROCESSING", 
            "created_by": admin_id,
            # Simpan jadwal aslinya (Format ISO WIB agar aman)
            "scheduled_at": run_date.isoformat(),
            "frequency": payload.frequency,
            "interval_days": payload.interval_days,
            "max_cycles": payload.max_cycles,
            "current_cycle": 1,
            "delay_min": payload.delay_min,
            "delay_max": payload.delay_max,
            "batch_size": payload.rest_batch,
            "rest_duration": payload.rest_duration_min * 60,
            "humanized_config": {
                "delay_min": payload.delay_min,
                "delay_max": payload.delay_max,
                "rest_batch": payload.rest_batch,
                "rest_duration_min": payload.rest_duration_min
            }
        }
        
        res = supabase.table("crm_campaigns").insert(new_camp).execute()
        campaign_id = res.data[0]['id']

        # C. EKSEKUSI / INJEKSI
        if not is_scheduled:
            # 1. Langsung Gaspol Sekarang!
            logger.info(f"🚀 Job {campaign_id[:8]} dieksekusi INSTAN.")
            bg_tasks.add_task(execute_broadcast_task, campaign_id)
        else:
            # 2. Dijadwalkan (Watchdog siap menerkam)
            logger.info(f"⏳ Job {campaign_id[:8]} berhasil DISIMPAN. Watchdog akan memantau: {run_date.strftime('%d-%m-%Y %H:%M:%S')} WIB")
            
            # [PASTIKAN WATCHDOG NYALA]
            await CampaignWatchdog.start()

        return api_success(message="✅ Kampanye berhasil diinjeksi ke Engine!")

    except Exception as e:
        logger.error(f"❌ [LAUNCH ERROR]: {str(e)}")
        traceback.print_exc()
        return api_error(f"Gagal meluncurkan kampanye: {str(e)}", 500)

# ------------------------------------------------------------------------------
# 3. API: INTERCEPTOR UI (PAUSE, RESUME, STOP)
# ------------------------------------------------------------------------------
@router.post("/api/action/{action}/{id}")
async def handle_campaign_action(action: str, id: str, bg_tasks: BackgroundTasks, admin=Depends(get_current_admin)):
    """API Interceptor untuk mengontrol tombol-tombol Live Dashboard"""
    if not supabase: return api_error("Database offline", 503)
    
    valid_actions = {"pause": "PAUSED", "resume": "PROCESSING", "stop": "STOPPED"}
    if action not in valid_actions:
        return api_error("Perintah aksi tidak dikenali sistem.", 400)
        
    try:
        new_status = valid_actions[action]
        supabase.table("crm_campaigns").update({"status": new_status}).eq("id", id).eq("created_by", admin.get("admin_id")).execute()
        
        if action == "resume":
            # Resume = Paksa eksekusi saat ini juga
            bg_tasks.add_task(execute_broadcast_task, id)
            
        logger.audit(admin.get("admin_id"), f"ACTION_{action.upper()}", f"Mengubah state kampanye {id} menjadi {new_status}")
        return api_success(message=f"Status kampanye diperbarui menjadi: {new_status}")
    except Exception as e:
        logger.error(f"Error Action Button UI: {e}")
        return api_error(str(e), 500)

# ------------------------------------------------------------------------------
# 4. API: DELETE CAMPAIGN
# ------------------------------------------------------------------------------
@router.delete("/api/delete/{id}")
async def delete_campaign(id: str, admin=Depends(get_current_admin)):
    """Menghapus secara permanen kampanye beserta log-nya"""
    if not supabase: return api_error("Database offline", 503)
    try:
        # Bersihkan log terlebih dahulu (Bypass Foreign Key)
        try: supabase.table("crm_blast_logs").delete().eq("campaign_id", id).execute()
        except: pass

        supabase.table("crm_campaigns").delete().eq("id", id).eq("created_by", admin.get("admin_id")).execute()
        
        logger.audit(admin.get("admin_id"), "DELETE_BROADCAST", f"Kampanye {id} dimusnahkan.")
        return api_success(message="Kampanye dan Riwayat Log berhasil dihapus permanen.")
    except Exception as e:
        logger.error(f"Error Delete Campaign UI: {e}")
        return api_error(f"Gagal menghapus data kampanye. {str(e)}", 500)
