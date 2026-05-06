"""
====================================================================================
BABA PARFUME - CRM TEMPLATES ENGINE [ENTERPRISE]
====================================================================================
Deskripsi : Menangani manajemen aset digital CRM.
            - CRUD Template Pesan (Copywriting + Emoji)
            - CRUD Database Target (Grup IDs / Username)
            - Sinkronisasi dengan Supabase crm_templates
            - [DYNAMIC FIX] Auto-Fetch Telegram Groups & Topics via MTProto
====================================================================================
"""
import os
import logging
import asyncio
from typing import List, Optional
from datetime import datetime

from fastapi import APIRouter, Request, Depends, HTTPException, Body
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from dotenv import load_dotenv

# Telethon Imports
import telethon
from telethon import TelegramClient, functions, types, utils
from telethon.sessions import StringSession

from routers.common import supabase, api_success, api_error, render_admin_template
from routers.dependencies import get_current_admin

load_dotenv()

logger = logging.getLogger("baba.crm.templates")

TELEGRAM_API_ID = int(os.getenv("API_ID", "0"))
TELEGRAM_API_HASH = os.getenv("API_HASH", "")

router = APIRouter(prefix="/admin/crm/templates", tags=["CRM Templates"])

# ==============================================================================
# SCHEMAS
# ==============================================================================
class TemplatePayload(BaseModel):
    template_id: Optional[str] = None  # Tambahin ini biar nangkep ID pas edit
    name: str
    type: str  # 'MESSAGE' atau 'TARGET_GROUP'
    content: str

# ==============================================================================
# 1. RENDER HALAMAN UTAMA (UI)
# ==============================================================================
@router.get("", response_class=HTMLResponse)
async def crm_templates_page(request: Request, admin=Depends(get_current_admin)):
    """Menampilkan halaman utama Master Template & Target"""
    return render_admin_template(
        request, 
        "crm/templates.html",
        admin_data=admin
    )

# ==============================================================================
# 2. API: FETCH ALL TEMPLATES
# ==============================================================================
@router.get("/list")
async def get_all_templates(admin=Depends(get_current_admin)):
    """Mengambil semua data template milik admin ini dari Database"""
    if not supabase: return api_error("Database offline", 503)

    try:
        res = supabase.table("crm_templates")\
                      .select("*")\
                      .eq("created_by", admin.get("admin_id"))\
                      .order("created_at", desc=True)\
                      .execute()
        return api_success(data=res.data or [])
    except Exception as e:
        logger.error(f"❌ [FETCH TEMPLATES ERROR]: {str(e)}")
        return api_error(f"Gagal mengambil data: {str(e)}", 500)

# ==============================================================================
# 3. API: AUTO-FETCH GROUPS & TOPICS (MAGIC FIX DYNAMIC IMPORT)
# ==============================================================================
@router.get("/fetch_groups")
async def fetch_telegram_groups(admin=Depends(get_current_admin)):
    """Mengambil list grup dan topik menggunakan Dynamic API Resolution"""
    if not supabase: return api_error("Database offline", 503)

    try:
        # Cek Session MTProto
        res = supabase.table("crm_telegram_sessions")\
                      .select("session_string")\
                      .eq("admin_id", admin.get("admin_id"))\
                      .eq("status", "active")\
                      .execute()
                      
        if not res.data:
            return api_error("MTProto belum terkoneksi. Silakan login Telegram terlebih dahulu.", 401)
            
        session_string = res.data[0]["session_string"]
        client = TelegramClient(StringSession(session_string), TELEGRAM_API_ID, TELEGRAM_API_HASH)
        
        # --- [MAGIC FIX] DYNAMIC FORUM TOPIC RESOLVER ---
        logger.info(f"🧐 [DEBUG] Telethon Version: {telethon.__version__}")
        
        GetForumTopicsReq = getattr(functions.channels, 'GetForumTopicsRequest',
                            getattr(functions.messages, 'GetForumTopicsRequest',
                            getattr(functions.channels, 'GetForumTopics', None)))

        HAS_RAW_API = GetForumTopicsReq is not None
        if not HAS_RAW_API:
            logger.warning("⚠️ [FATAL] Forum API tidak ditemukan di versi Telethon ini.")

        groups_data = []
        stats = {'groups': 0, 'forums': 0, 'topics_found': 0}
        
        await client.connect()
        if not await client.is_user_authorized():
            await client.disconnect()
            return api_error("Sesi Telegram kadaluarsa. Silakan login ulang.", 401)
            
        logger.info("🚀 Memulai proses scanning Grup & Topik...")
        
        # Looping Dialogs
        async for dialog in client.iter_dialogs(limit=500):
            if dialog.is_group or dialog.is_channel:
                entity = dialog.entity
                
                # Fokus ke Megagroup untuk membaca Topik
                if getattr(entity, 'megagroup', False) or dialog.is_group:
                    is_forum = getattr(entity, 'forum', False)
                    group_id = str(dialog.id) # Pakai ID absolut (dengan -100) untuk dikirim
                    
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
                                
                                # Scan up to 5 Pages (seperti di BlastPro)
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
                                                t_title = f"(Deleted) #{t_id}"
                                            elif not t_title:
                                                t_title = f"Topic #{t_id}"
                                                
                                            if t_id == 1 and ("Topic #1" in t_title or not t_title):
                                                t_title = "General 📌"
                                                
                                            group_info["topics"].append({"id": t_id, "title": t_title})
                                            stats['topics_found'] += 1
                                            
                                    last_topic = topic_res.topics[-1]
                                    offset_id = getattr(last_topic, 'id', 0)
                                    offset_date = getattr(last_topic, 'date', 0)
                                    await asyncio.sleep(0.2) # Anti FloodWait
                                    
                                # Urutkan dan pastikan General selalu ada
                                group_info["topics"].sort(key=lambda x: x['id'])
                                if not any(t['id'] == 1 for t in group_info["topics"]):
                                    group_info["topics"].insert(0, {'id': 1, 'title': 'General (Topik Utama) 📌'})
                                    
                            except Exception as forum_e:
                                logger.error(f"Forum Scan Error {dialog.name}: {forum_e}")
                                group_info["topics"] = [{'id': 1, 'title': 'General (Fallback - Error)'}]
                        else:
                            group_info["topics"] = [{'id': 1, 'title': 'General (Fallback - API Missing)'}]
                            
                    else:
                        stats['groups'] += 1
                        
                    groups_data.append(group_info)
                    
        await client.disconnect()
        logger.info(f"✅ Selesai Scanning: {stats}")
        return api_success(message="Berhasil mengekstrak data dari Telegram", data=groups_data)
        
    except Exception as e:
        logger.error(f"❌ [FETCH TELEGRAM ERROR]: {str(e)}")
        return api_error(f"Gagal menyinkronkan data Telegram: {str(e)}", 500)

# ==============================================================================
# 4. API: SAVE / UPDATE TEMPLATE
# ==============================================================================
# ==============================================================================
# 4. API: SAVE / UPDATE TEMPLATE
# ==============================================================================
@router.post("/save")
async def save_crm_template(
    payload: TemplatePayload, 
    admin=Depends(get_current_admin)
):
    """Menyimpan template/target ke Database"""
    if not supabase: return api_error("Database offline", 503)

    try:
        data = {
            "name": payload.name.strip(),
            "type": payload.type,
            "content": payload.content.strip(),
            "created_by": admin.get("admin_id")
        }

        # Cek ID dari payload
        if payload.template_id:
            res = supabase.table("crm_templates").update(data).eq("id", payload.template_id).execute()
            msg = "Aset CRM berhasil diperbarui!"
        else:
            res = supabase.table("crm_templates").insert(data).execute()
            msg = "Aset CRM baru berhasil ditambahkan!"

        return api_success(message=msg, data=res.data[0] if res.data else {})

    except Exception as e:
        logger.error(f"❌ [SAVE TEMPLATE ERROR]: {str(e)}")
        return api_error(f"Gagal menyimpan data: {str(e)}", 500)

# ==============================================================================
# 5. API: DELETE TEMPLATE
# ==============================================================================
@router.delete("/delete/{id}")
async def delete_crm_template(id: str, admin=Depends(get_current_admin)):
    """Menghapus template secara permanen"""
    if not supabase: return api_error("Database offline", 503)

    try:
        supabase.table("crm_templates")\
                .delete()\
                .eq("id", id)\
                .eq("created_by", admin.get("admin_id"))\
                .execute()
        return api_success(message="Data berhasil dihapus dari sistem.")
    except Exception as e:
        logger.error(f"❌ [DELETE TEMPLATE ERROR]: {str(e)}")
        return api_error(f"Gagal menghapus data: {str(e)}", 500)