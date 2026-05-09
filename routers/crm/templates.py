"""
====================================================================================
BABA PARFUME - CRM TEMPLATES ENGINE [ULTRA ENTERPRISE V15.0]
====================================================================================
Deskripsi : Arsitektur Backend Kasta Dewa untuk Manajemen Aset Digital CRM.
            Sistem ini memisahkan secara arsitektural antara Teks Promosi (Content)
            dan Media Lampiran (Source Link) sesuai standar BlastPro Enterprise.
Developer : BABA Enterprise Core Team
Fitur Utama:
            1. Advanced CRUD Template Pesan & Target
            2. Dual-Column Schema (Content & Source_Link)
            3. Dynamic Auto-Fetch Telegram Groups & Topics
            4. Deep Media Extractor Engine (Base64 + Caption Scanner)
            5. Fault-Tolerant API Routes & Strict Pydantic Validation
====================================================================================
"""

import os
import io
import re
import base64
import logging
import asyncio
import traceback
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone

from fastapi import APIRouter, Request, Depends, HTTPException, Body
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field, validator, HttpUrl
from dotenv import load_dotenv

# Telethon Imports untuk Deep Extraction
import telethon
from telethon import TelegramClient, functions, types, utils
from telethon.errors import SessionPasswordNeededError, FloodWaitError
from telethon.sessions import StringSession

from routers.common import supabase, api_success, api_error, render_admin_template
from routers.dependencies import get_current_admin

load_dotenv()

# ==============================================================================
# SECTION 1: ENTERPRISE OBSERVABILITY & LOGGING SYSTEM
# ==============================================================================
class TemplateEngineLogger:
    """Manajer Log Kelas Enterprise untuk melacak setiap aktivitas Template Engine"""
    def __init__(self):
        self.logger = logging.getLogger("baba.crm.templates")
        if not self.logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter('%(asctime)s | [TEMPLATE_ENGINE] %(levelname)s - %(message)s')
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)
            self.logger.setLevel(logging.DEBUG)

    def info(self, msg: str): self.logger.info(msg)
    def warning(self, msg: str): self.logger.warning(msg)
    def error(self, msg: str): self.logger.error(msg)
    def critical(self, msg: str): self.logger.critical(msg)
    def debug(self, msg: str): self.logger.debug(msg)

logger = TemplateEngineLogger()

TELEGRAM_API_ID = int(os.getenv("API_ID", "0"))
TELEGRAM_API_HASH = os.getenv("API_HASH", "")

router = APIRouter(prefix="/admin/crm/templates", tags=["CRM Templates"])

# ==============================================================================
# SECTION 2: STRICT PYDANTIC DATA VALIDATION MODELS
# ==============================================================================
class TemplatePayload(BaseModel):
    """
    Schema Payload Dewa: 
    Memastikan Data yang masuk dari templates.html 100% Valid dan Bersih.
    Sekarang mendukung `source_link` untuk opsi Clone Media!
    """
    template_id: Optional[str] = Field(None, description="ID Template jika mode Edit")
    name: str = Field(..., min_length=3, max_length=150, description="Label / Judul Template")
    type: str = Field(..., description="'MESSAGE' atau 'TARGET_GROUP'")
    content: str = Field(..., min_length=1, description="Isi Teks Pesan atau Kumpulan ID Target")
    source_link: Optional[str] = Field(None, description="URL Telegram Asli untuk ditarik medianya (Opsi A)")

    @validator('type')
    def validate_template_type(cls, v):
        allowed = ['MESSAGE', 'TARGET_GROUP']
        if v not in allowed:
            raise ValueError(f"Tipe template harus salah satu dari {allowed}")
        return v
        
    @validator('source_link')
    def validate_source_link(cls, v):
        if v:
            v = v.strip()
            if not v.startswith("http://t.me/") and not v.startswith("https://t.me/"):
                raise ValueError("Source link harus berupa URL Telegram yang valid (t.me/...)")
        return v

class PreviewUrlPayload(BaseModel):
    """Schema Validasi URL sebelum di-Fetch oleh Engine"""
    url: str = Field(..., description="Link Telegram Mentah")

    @validator('url')
    def validate_url(cls, v):
        v = v.strip()
        if not v.startswith("http://t.me/") and not v.startswith("https://t.me/"):
            raise ValueError("Bukan Link Telegram Asli!")
        return v

# ==============================================================================
# SECTION 3: CORE UTILITIES & EXTRACTOR ENGINES
# ==============================================================================
class TelegramURLParser:
    """Mesin Pemecah URL Telegram Menjadi ID Numerik (Chat ID & Message ID)"""
    
    @staticmethod
    def parse(url: str) -> tuple[int, int]:
        """
        Mengurai URL https://t.me/... menjadi (chat_id, message_id)
        Mendukung format Private Channel (c) maupun Username Publik.
        """
        try:
            link = url.rstrip('/')
            if "t.me/" not in link:
                raise ValueError("URL tidak mengandung t.me/")
                
            parts = link.split('t.me/')[1].split('/')
            
            if parts[0] == 'c':
                # Format Private Channel: t.me/c/123456789/100
                chat_id = int("-100" + parts[1])
                msg_id = int(parts[-1])
            else:
                # Format Public Channel/Group: t.me/username/100
                chat_id = parts[0]
                msg_id = int(parts[-1])
                
            logger.debug(f"URL Parsed -> Chat: {chat_id}, MsgID: {msg_id}")
            return chat_id, msg_id
            
        except Exception as e:
            logger.error(f"Gagal Parsing URL '{url}': {e}")
            raise ValueError("Struktur URL Telegram tidak dapat diurai. Pastikan copy link langsung dari pesan.")

class MediaExtractorEngine:
    """Mesin Kasta Dewa untuk Mengubah Media Telegram menjadi Base64 & Mencari Caption Tersembunyi"""
    
    @staticmethod
    async def extract_caption(client: TelegramClient, chat_entity, message, msg_id: int) -> str:
        """Logika radar brutal untuk mencari caption di dalam Album/Grouped Message"""
        extracted_text = getattr(message, 'text', '') or getattr(message, 'message', '') or ""

        # 1. Jika sudah ada teks, langsung kembalikan
        if extracted_text:
            return extracted_text

        # 2. Logic pencarian Album/Forum (Scan manual ID sekitar)
        if not extracted_text and getattr(message, 'grouped_id', None):
            logger.info(f"📸 Album terdeteksi (Group ID: {message.grouped_id}). Mencari caption di pesan saudara...")
            for offset in range(-5, 6):
                if offset == 0: continue
                try:
                    sibling = await client.get_messages(chat_entity, ids=msg_id + offset)
                    if sibling and getattr(sibling, 'grouped_id', None) == message.grouped_id:
                        teks_sibling = getattr(sibling, 'text', '') or getattr(sibling, 'message', '') or ""
                        if teks_sibling:
                            logger.info(f"✅ Caption album ketemu di ID: {sibling.id}")
                            return teks_sibling
                except Exception: pass

        # 3. Fallback Ekstrem kalau tetep kosong (Beda 1 ID Atas Bawah)
        logger.warning("⚠️ Teks masih kosong. Mengaktifkan radar fallback ke pesan terdekat...")
        for offset in [-1, 1, -2, 2]:
            try:
                tetangga = await client.get_messages(chat_entity, ids=msg_id + offset)
                if tetangga:
                    teks_tetangga = getattr(tetangga, 'text', '') or getattr(tetangga, 'message', '') or ""
                    if teks_tetangga:
                        logger.info(f"✅ Teks fallback ketemu di ID: {tetangga.id}")
                        return teks_tetangga
            except Exception: pass
            
        return ""

    @staticmethod
    async def extract_media_base64(client: TelegramClient, message) -> Optional[str]:
        """Download media ke RAM (BytesIO) dan konversi ke Base64 agar bisa dirender di HTML"""
        if not message.media:
            return None
            
        if not (hasattr(message.media, 'photo') or hasattr(message.media, 'document')):
            return None
            
        try:
            logger.debug("Mendownload media ke memory buffer...")
            buffer = io.BytesIO()
            await client.download_media(message.media, file=buffer)
            img_encoded = base64.b64encode(buffer.getvalue()).decode('utf-8')
            logger.info("✅ Konversi media ke Base64 sukses!")
            return f"data:image/jpeg;base64,{img_encoded}"
        except Exception as e:
            logger.error(f"Gagal ekstrak media base64: {e}")
            return None

# ==============================================================================
# SECTION 4: API ROUTE HANDLERS (WEB & DATA)
# ==============================================================================

@router.get("", response_class=HTMLResponse)
async def crm_templates_page(request: Request, admin=Depends(get_current_admin)):
    """
    Menampilkan halaman antarmuka utama Manajemen Template & Target.
    Mengirimkan data admin yang login ke template engine.
    """
    logger.info(f"Admin {admin.get('admin_id')} mengakses dashboard Templates CRM.")
    return render_admin_template(
        request, 
        "crm/templates.html",
        admin_data=admin
    )

@router.get("/list")
async def get_all_templates(admin=Depends(get_current_admin)):
    """
    Endpoint untuk menyuplai data ke Alpine.js (Table List).
    Sekarang akan menyertakan kolom `source_link` berkat Opsi A.
    """
    if not supabase: return api_error("Sistem Database Induk sedang offline", 503)

    try:
        res = supabase.table("crm_templates")\
                      .select("id, name, type, content, source_link, created_at")\
                      .eq("created_by", admin.get("admin_id"))\
                      .order("created_at", desc=True)\
                      .execute()
                      
        logger.debug(f"Mengirim {len(res.data or [])} data aset template ke antarmuka.")
        return api_success(data=res.data or [])
    except Exception as e:
        logger.error(f"❌ [FETCH TEMPLATES ERROR]: {str(e)}")
        return api_error(f"Kegagalan sistem saat memuat data: {str(e)}", 500)


@router.post("/api/preview_url")
async def preview_telegram_url(payload: PreviewUrlPayload, admin=Depends(get_current_admin)):
    """
    ENGINE UTAMA EKSTRAKSI URL: 
    Merespon permintaan dari UI untuk menarik Teks dan Media dari link Telegram.
    Sistem akan otomatis membersihkan koneksi untuk mencegah Memory Leak.
    """
    if not supabase: return api_error("Database offline", 503)
    url = payload.url.strip()

    try:
        # 1. VERIFIKASI SESI MTPROTO ADMIN
        res = supabase.table("crm_telegram_sessions")\
                      .select("session_string")\
                      .eq("admin_id", admin.get("admin_id"))\
                      .eq("status", "active")\
                      .execute()
                      
        if not res.data:
            return api_error("Sesi MTProto belum diaktifkan di Pengaturan.", 401)
            
        session_string = res.data[0]["session_string"]
        
        # Inisiasi Telethon Client
        client = TelegramClient(StringSession(session_string), TELEGRAM_API_ID, TELEGRAM_API_HASH)
        
        await client.connect()
        if not await client.is_user_authorized():
            await client.disconnect()
            return api_error("Sesi Telethon kadaluarsa atau dicabut dari HP Anda.", 401)

        logger.info(f"🔍 [EXTRACTOR] Memulai Ekstraksi Deep-Link: {url}")
        
        # 2. PARSING URL
        try:
            chat_id, msg_id = TelegramURLParser.parse(url)
        except ValueError as ve:
            await client.disconnect()
            return api_error(str(ve))

        # 3. FETCHING DATA DARI SERVER TELEGRAM
        try:
            # Resolving Entity (Bisa channel private, group, atau public)
            chat_entity = await client.get_entity(chat_id)
            message = await client.get_messages(chat_entity, ids=msg_id)
            
            if not message:
                raise Exception("Pesan terhapus atau Anda tidak memiliki akses ke grup tersebut.")

            # Ekstrak Teks menggunakan Mesin Radar
            extracted_text = await MediaExtractorEngine.extract_caption(client, chat_entity, message, msg_id)

            # Ekstrak Media menjadi Gambar Base64
            image_base64 = await MediaExtractorEngine.extract_media_base64(client, message)

        except Exception as fetch_error:
            logger.error(f"❌ [API FETCH ERROR]: {fetch_error}")
            await client.disconnect()
            return api_error(f"Telegram menolak akses ke pesan ini: {str(fetch_error)}")

        # 4. CLEANUP KONEKSI & RETURN PAYLOAD
        await client.disconnect()
        logger.info("✅ Proses Ekstraksi Selesai dengan Sempurna.")
        
        return api_success(message="Teks dan Media berhasil di-fetch!", data={
            "text": extracted_text,
            "image_url": image_base64
        })

    except Exception as e:
        logger.critical(f"❌ [EXTRACTOR FATAL CRASH]: {str(e)}\n{traceback.format_exc()}")
        try: await client.disconnect() 
        except: pass
        return api_error("Terjadi kegagalan server internal saat ekstraksi URL.", 500)


@router.get("/fetch_groups")
async def fetch_telegram_groups(admin=Depends(get_current_admin)):
    """
    ENGINE SINKRONISASI GRUP:
    Mengumpulkan seluruh Grup, Channel, dan Forum Topic yang diikuti Admin.
    Kode ini dilengkapi dengan Fallback API jika fitur Forum belum ter-update.
    """
    if not supabase: return api_error("Database offline", 503)

    try:
        # Cek Session MTProto
        res = supabase.table("crm_telegram_sessions")\
                      .select("session_string")\
                      .eq("admin_id", admin.get("admin_id"))\
                      .eq("status", "active")\
                      .execute()
                      
        if not res.data:
            return api_error("Akses Ditolak. Sesi MTProto tidak ditemukan.", 401)
            
        session_string = res.data[0]["session_string"]
        client = TelegramClient(StringSession(session_string), TELEGRAM_API_ID, TELEGRAM_API_HASH)
        
        # MAGIC FIX: Dynamic Forum API Resolver
        GetForumTopicsReq = getattr(functions.channels, 'GetForumTopicsRequest',
                            getattr(functions.messages, 'GetForumTopicsRequest',
                            getattr(functions.channels, 'GetForumTopics', None)))

        HAS_RAW_API = GetForumTopicsReq is not None
        if not HAS_RAW_API:
            logger.warning("⚠️ Peringatan: API Forum Topik tidak tersedia di versi library ini.")

        groups_data = []
        stats = {'groups': 0, 'forums': 0, 'topics_found': 0}
        
        await client.connect()
        if not await client.is_user_authorized():
            await client.disconnect()
            return api_error("Sesi dicabut. Mohon login MTProto ulang.", 401)
            
        logger.info("🚀 Meluncurkan satelit untuk memindai Grup & Forum MTProto...")
        
        # Looping Dialogs
        async for dialog in client.iter_dialogs(limit=500):
            if dialog.is_group or dialog.is_channel:
                entity = dialog.entity
                
                # Fokus ke Megagroup
                if getattr(entity, 'megagroup', False) or dialog.is_group:
                    is_forum = getattr(entity, 'forum', False)
                    group_id = str(dialog.id)
                    
                    group_info = {
                        "id": group_id,
                        "title": dialog.name,
                        "is_forum": is_forum,
                        "topics": []
                    }
                    
                    if is_forum:
                        stats['forums'] += 1
                        if HAS_RAW_API:
                            try:
                                input_channel = await client.get_input_entity(dialog.id)
                                offset_id, offset_date, offset_topic = 0, 0, 0
                                
                                # Scan up to 5 Pages untuk kedalaman Topik
                                for page in range(5):
                                    req = GetForumTopicsReq(
                                        input_channel,
                                        q='',
                                        offset_date=offset_date,
                                        offset_id=offset_id,
                                        offset_topic=offset_topic,
                                        limit=100
                                    )
                                    topic_res = await client(req)
                                    if not topic_res.topics: break
                                    
                                    for t in topic_res.topics:
                                        t_id = getattr(t, 'id', None)
                                        if t_id:
                                            t_title = getattr(t, 'title', '')
                                            if isinstance(t, types.ForumTopicDeleted):
                                                t_title = f"(Terhapus) #{t_id}"
                                            elif not t_title:
                                                t_title = f"Topik #{t_id}"
                                                
                                            if t_id == 1 and ("Topik #1" in t_title or not t_title):
                                                t_title = "General 📌"
                                                
                                            group_info["topics"].append({"id": t_id, "title": t_title})
                                            stats['topics_found'] += 1
                                            
                                    last_topic = topic_res.topics[-1]
                                    offset_id = getattr(last_topic, 'id', 0)
                                    offset_date = getattr(last_topic, 'date', 0)
                                    await asyncio.sleep(0.2) # Jeda Humanis
                                    
                                group_info["topics"].sort(key=lambda x: x['id'])
                                if not any(t['id'] == 1 for t in group_info["topics"]):
                                    group_info["topics"].insert(0, {'id': 1, 'title': 'General (Utama) 📌'})
                                    
                            except FloodWaitError as e:
                                logger.error(f"FloodWait di grup {dialog.name}. Istirahat {e.seconds}s.")
                                await asyncio.sleep(e.seconds)
                            except Exception as forum_e:
                                logger.error(f"Error Scan Forum '{dialog.name}': {forum_e}")
                                group_info["topics"] = [{'id': 1, 'title': 'General (Fallback)'}]
                        else:
                            group_info["topics"] = [{'id': 1, 'title': 'General (API Missing)'}]
                            
                    else:
                        stats['groups'] += 1
                        
                    groups_data.append(group_info)
                    
        await client.disconnect()
        logger.info(f"✅ Scanning Sukses: {stats['groups']} Grup Biasa, {stats['forums']} Forum, {stats['topics_found']} Topik.")
        return api_success(message="Seluruh Grup dan Topik berhasil dipetakan.", data=groups_data)
        
    except Exception as e:
        logger.error(f"❌ [SYNC GROUPS FATAL ERROR]: {str(e)}\n{traceback.format_exc()}")
        try: await client.disconnect() 
        except: pass
        return api_error("Gagal menyinkronkan data Telegram. Sistem kewalahan.", 500)

# ==============================================================================
# SECTION 5: CRUD OPERATIONS (SAVE & DELETE)
# ==============================================================================
@router.post("/save")
async def save_crm_template(
    payload: TemplatePayload, 
    admin=Depends(get_current_admin)
):
    """
    API KUNCI (OPSI A): 
    Menyimpan data Teks (Content) dan Media URL (Source_Link) ke Database.
    Memisahkan data ini memungkinkan BlastPro Architecture berjalan di BABA Parfume.
    """
    if not supabase: return api_error("Database Induk Offline", 503)

    try:
        # Pydantic Payload Assembly
        data_to_insert = {
            "name": payload.name.strip(),
            "type": payload.type,
            "content": payload.content.strip(),
            "source_link": payload.source_link.strip() if payload.source_link else None,
            "created_by": admin.get("admin_id")
        }

        # Keputusan: UPDATE vs INSERT
        if payload.template_id:
            # Mode Modifikasi
            res = supabase.table("crm_templates")\
                          .update(data_to_insert)\
                          .eq("id", payload.template_id)\
                          .execute()
            
            logger.info(f"📝 UPDATE: Template '{payload.name}' (ID: {payload.template_id}) diperbarui oleh Admin {admin.get('admin_id')}.")
            msg = "Amunisi berhasil dimodifikasi!"
        else:
            # Mode Pembuatan Baru
            res = supabase.table("crm_templates")\
                          .insert(data_to_insert)\
                          .execute()
                          
            logger.info(f"📝 INSERT: Template baru '{payload.name}' diciptakan oleh Admin {admin.get('admin_id')}.")
            msg = "Aset Amunisi baru berhasil dikunci ke dalam Server!"

        # Return the saved object
        saved_data = res.data[0] if res.data else {}
        return api_success(message=msg, data=saved_data)

    except Exception as e:
        logger.critical(f"❌ [DB SAVE ERROR]: {str(e)}\n{traceback.format_exc()}")
        return api_error(f"Gagal menyuntikkan data ke server: {str(e)}", 500)

@router.delete("/delete/{id}")
async def delete_crm_template(id: str, admin=Depends(get_current_admin)):
    """Menghapus template secara permanen (Hard Delete) dari Database"""
    if not supabase: return api_error("Database offline", 503)

    try:
        # Proteksi RLS Internal: Hanya admin pembuat yang bisa menghapus
        res = supabase.table("crm_templates")\
                .delete()\
                .eq("id", id)\
                .eq("created_by", admin.get("admin_id"))\
                .execute()
        
        if not res.data:
            logger.warning(f"⚠️ Percobaan penghapusan ilegal/gagal pada ID {id} oleh Admin {admin.get('admin_id')}.")
            return api_error("Aset tidak ditemukan atau Anda tidak memiliki izin.")
            
        logger.info(f"🗑️ DELETE: Template ID {id} dibumihanguskan oleh Admin {admin.get('admin_id')}.")
        return api_success(message="Data berhasil dihapus dari muka bumi.")
        
    except Exception as e:
        logger.error(f"❌ [DELETE TEMPLATE ERROR]: {str(e)}")
        return api_error(f"Gagal menghapus aset: {str(e)}", 500)
