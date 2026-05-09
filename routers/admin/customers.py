"""
====================================================================================
BABA PARFUME - CRM CUSTOMERS ENGINE (ULTRA ENTERPRISE V12.0)
====================================================================================
Deskripsi : Arsitektur Backend Skala Besar untuk Manajemen Data Pelanggan.
Developer : BABA Enterprise Core Team
Fitur     : 
            1. Single Source of Truth (Tabel 'customers' dengan kolom 'source')
            2. Real-Time Telethon Sync & Data Enrichment (Melengkapi data kosong)
            3. [NEW] Broadcast Commander Integrator -> Delegasi penuh ke broadcast.py
            4. RFM Analytics Engine (Recency, Frequency, Monetary)
            5. Server-Side Export Engine (CSV/JSON generation)
            6. Fault Tolerance & Retry Mechanism (Anti-Crash DB)
            7. Admin Audit Trail Logging
====================================================================================
"""

import os
import io
import csv
import json
import time
import uuid
import asyncio
import random
import logging
from typing import Optional, List, Dict, Any, Union, Tuple
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Request, Depends, HTTPException, status, Form, BackgroundTasks, Query
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field, validator

# Telethon untuk Deep Sync
from telethon import TelegramClient
from telethon.sessions import StringSession

# Supabase Bridge & Core Routers
try:
    from database import supabase
except ImportError:
    supabase = None

from routers.common import render_admin_template, api_success, api_error
from routers.dependencies import get_current_admin

# ==============================================================================
# ENTERPRISE LOGGING & AUDIT SYSTEM
# ==============================================================================
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("telethon").setLevel(logging.WARNING)

class EnterpriseLogger:
    """Manajer Log Kelas Enterprise untuk Observabilitas Sistem"""
    def __init__(self):
        self.logger = logging.getLogger("baba.crm.customers")
        if not self.logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter('%(asctime)s | [BABA_CRM] %(levelname)s - %(message)s')
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)
            self.logger.setLevel(logging.INFO)

    def info(self, msg: str): self.logger.info(msg)
    def warning(self, msg: str): self.logger.warning(msg)
    def error(self, msg: str): self.logger.error(msg)
    def critical(self, msg: str): self.logger.critical(msg)
    
    def audit(self, admin_id: int, action: str, details: str):
        """Mencatat aktivitas admin untuk keperluan Audit Trail keamanan"""
        self.logger.info(f"[AUDIT TRAIL] Admin ID: {admin_id} | Action: {action} | Details: {details}")
        if supabase:
            try:
                supabase.table("admins").update({"last_activity_desc": f"{action}: {details}"}).eq("id", admin_id).execute()
            except:
                pass

logger = EnterpriseLogger()

# ==============================================================================
# ENVIRONMENT VARIABLES & ROUTER INIT
# ==============================================================================
router = APIRouter(prefix="/admin", tags=["Admin CRM Customers"])

TELEGRAM_API_ID = int(os.getenv("API_ID", "0"))
TELEGRAM_API_HASH = os.getenv("API_HASH", "")

# ==============================================================================
# PYDANTIC SCHEMAS (DATA VALIDATION LAYER)
# ==============================================================================
class CommanderSettings(BaseModel):
    min_delay: int
    max_delay: int
    batch_size: int

class CommanderBroadcastPayload(BaseModel):
    """Schema Validasi Ketat untuk Eksekusi Broadcast Commander V12.0"""
    target_ids: List[Union[int, str]] = Field(..., min_items=1, description="List Telegram ID target broadcast")
    template_id: str = Field(..., description="ID Template Copywriting yang sudah diekstrak")
    schedule_time: str = Field(..., description="Format: YYYY-MM-DD HH:MM")
    settings: CommanderSettings

class CustomerSyncPayload(BaseModel):
    """Schema untuk API Sinkronisasi Dinamis"""
    force_update: bool = False
    limit: int = Field(1000, description="Jumlah limit history chat yang akan ditarik dari Telegram")

# ==============================================================================
# ENTERPRISE UTILITIES: RETRY MECHANISM
# ==============================================================================
async def execute_with_retry(func, *args, max_retries: int = 4, delay: float = 1.0, **kwargs):
    """
    Eksekutor Fungsi Database yang kebal terhadap Request Timeout (RTO) sementara.
    Sistem akan menerapkan Exponential Backoff sebelum melemparkan error 500.
    """
    for attempt in range(max_retries):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            if attempt == max_retries - 1:
                logger.error(f"Operasi Database Gagal Permanen setelah {max_retries} percobaan: {e}")
                raise e
            logger.warning(f"Database timeout/error. Retrying in {delay}s... (Attempt {attempt+1}/{max_retries})")
            await asyncio.sleep(delay)
            delay *= 1.5  

# ==============================================================================
# ANALYTICS ENGINE: RFM CALCULATOR (Recency, Frequency, Monetary)
# ==============================================================================
class CustomerAnalyticsEngine:
    """Modul untuk memproses dan mengkategorikan pelanggan berdasarkan metrik transaksi"""
    
    @staticmethod
    def calculate_rfm_score(customers: List[Dict]) -> List[Dict]:
        """
        Memperkaya data pelanggan dengan segmentasi CRM otomatis.
        Syarat VIP: Spend >= $100 ATAU Orders >= 3.
        """
        now = datetime.now(timezone.utc)
        enriched_customers = []
        
        for c in customers:
            # Safely parse last_interaction date
            last_inter = c.get('last_interaction') or c.get('created_at')
            try:
                if isinstance(last_inter, str):
                    clean_date = last_inter.replace(' ', 'T')
                    if not clean_date.endswith('Z') and '+' not in clean_date:
                        clean_date += 'Z'
                    dt = datetime.fromisoformat(clean_date)
                else:
                    dt = now
            except:
                dt = now
                
            days_since = (now - dt).days
            
            # Parsing metrics
            orders = int(c.get('total_orders', 0) or 0)
            spent = float(c.get('total_spent', 0.0) or 0.0)
            
            # Determine Segment
            segment = "Baru"
            if orders > 0:
                segment = "Aktif"
            if spent >= 100 or orders >= 3:
                segment = "VIP"
                
            # Deteksi Resiko Churn (Sudah lama tidak interaksi)
            churn_risk = False
            if days_since > 30 and orders > 0:
                churn_risk = True

            c['analytics'] = {
                'days_since_interaction': days_since,
                'is_churn_risk': churn_risk,
                'segment': segment
            }
            enriched_customers.append(c)
            
        return enriched_customers

# ==============================================================================
# CORE SERVICE 1: TELETHON DEEP SYNC & ENRICHMENT ENGINE
# ==============================================================================
class DeepSyncService:
    """Service khusus untuk menarik pengguna lama MTProto dan menginjeksinya ke CRM"""
    
    @staticmethod
    async def run_sync_engine(admin_id: int, fetch_limit: int = 1000) -> Tuple[int, int, int]:
        """
        Engine Penarik Data dengan logika Upsert & Enrichment ke tabel `customers`.
        Return: (Total Insert Baru, Total Data Diperbarui/Enriched, Total Gagal)
        """
        if not supabase:
            logger.error("Sync Engine Aborted: Modul Supabase Offline")
            return 0, 0, 0

        logger.info(f"Memulai MTProto Deep Sync & Enrichment Engine (Admin ID: {admin_id})...")
        inserted_count = 0
        updated_count = 0
        error_count = 0

        try:
            # 1. AUTENTIKASI: Ambil session string dari DB
            session_res = await execute_with_retry(
                lambda: supabase.table("crm_telegram_sessions").select("session_string").eq("admin_id", admin_id).eq("status", "active").execute()
            )
            if not session_res.data:
                raise Exception("Sesi MTProto tidak aktif. Harap hubungkan akun Telegram di Pengaturan.")
            
            session_string = session_res.data[0]["session_string"]

            # 2. KONEKSI KE TELEGRAM API
            client = TelegramClient(StringSession(session_string), TELEGRAM_API_ID, TELEGRAM_API_HASH)
            await client.connect()
            
            if not await client.is_user_authorized():
                await client.disconnect()
                raise Exception("Sesi Telegram telah kadaluarsa. Silakan scan ulang nomor di Pengaturan.")

            logger.info(f"Telethon terhubung. Mengambil {fetch_limit} riwayat dialog terakhir...")
            
            # 3. FETCHING DIALOGS & PARSING METADATA
            dialogs = await client.get_dialogs(limit=fetch_limit, ignore_migrated=True)
            mtproto_users = []
            
            for dialog in dialogs:
                if dialog.is_user and not dialog.entity.bot:
                    if getattr(dialog.entity, 'deleted', False):
                        continue
                        
                    user = dialog.entity
                    first_name = user.first_name or ""
                    last_name = user.last_name or ""
                    full_name = f"{first_name} {last_name}".strip() or f"User {user.id}"
                    
                    last_msg_date = dialog.message.date.isoformat() if dialog.message and dialog.message.date else datetime.now(timezone.utc).isoformat()
                    
                    # [TAMBAHAN DEWA 1]: Tangkap Access Hash dari Telethon!
                    acc_hash = getattr(user, 'access_hash', None)
                        
                    mtproto_users.append({
                        "telegram_id": user.id,
                        "access_hash": str(acc_hash) if acc_hash else None, # Simpan sebagai string
                        "full_name": full_name,
                        "username": user.username or None,
                        "phone": user.phone or None,
                        "last_interaction": last_msg_date
                    })
                    
            await client.disconnect()
            logger.info(f"Berhasil menarik {len(mtproto_users)} entitas manusia dari Telegram.")

            # 4. CROSS-CHECK DENGAN MASTER TABLE CUSTOMERS
            # [TAMBAHAN DEWA 2]: Tambahkan 'access_hash' ke dalam list select DB
            customers_res = await execute_with_retry(
                lambda: supabase.table("customers").select("id, telegram_id, source, username, phone, access_hash").execute()
            )
            
            existing_cust_map = {int(c["telegram_id"]): c for c in (customers_res.data or [])}

            # 5. FILTERING, BATCHING, & DATA ENRICHMENT
            new_customers = []
            updates_queue = []
            current_time = datetime.now(timezone.utc).isoformat()
            
            for u in mtproto_users:
                tid = int(u["telegram_id"])
                
                if tid not in existing_cust_map:
                    # PENGGUNA BARU
                    new_customers.append({
                        "telegram_id": tid,
                        "access_hash": u["access_hash"], # [TAMBAHAN DEWA 3]: Suntik Hash untuk User Baru
                        "full_name": u["full_name"],
                        "username": u["username"],
                        "phone": u["phone"],
                        "source": "mtproto",
                        "last_interaction": u["last_interaction"],
                        "total_orders": 0,
                        "total_spent": 0.0,
                        "created_at": current_time,
                        "updated_at": current_time
                    })
                else:
                    # PENGGUNA LAMA -> ENRICHMENT
                    db_user = existing_cust_map[tid]
                    current_source = db_user.get("source") or "bot"
                    
                    needs_update = False
                    update_payload = {"last_interaction": u["last_interaction"]}
                    
                    if "mtproto" not in current_source.lower():
                        update_payload["source"] = f"{current_source}, mtproto"
                        needs_update = True
                        
                    if not db_user.get("username") and u["username"]:
                        update_payload["username"] = u["username"]
                        needs_update = True
                        
                    if not db_user.get("phone") and u["phone"]:
                        update_payload["phone"] = u["phone"]
                        needs_update = True
                        
                    # [TAMBAHAN DEWA 4]: Update Hash jika di DB kosong atau berubah
                    if u["access_hash"] and str(db_user.get("access_hash")) != str(u["access_hash"]):
                        update_payload["access_hash"] = u["access_hash"]
                        needs_update = True
                        
                    # Selalu update last_interaction
                    needs_update = True 
                        
                    if needs_update:
                        updates_queue.append({"id": db_user["id"], "payload": update_payload})

            # 6. EKSEKUSI BATCH INSERT
            chunk_size = 100
            if new_customers:
                logger.info(f"Memulai Batch Insert {len(new_customers)} pelanggan baru...")
                for i in range(0, len(new_customers), chunk_size):
                    chunk = new_customers[i:i + chunk_size]
                    try:
                        await execute_with_retry(lambda c=chunk: supabase.table("customers").insert(c).execute())
                        inserted_count += len(chunk)
                    except Exception as e:
                        logger.error(f"Gagal memproses batch Insert (Index {i}): {e}")
                        error_count += len(chunk)

            # 7. EKSEKUSI BATCH UPDATE (Data Enrichment)
            if updates_queue:
                logger.info(f"Memperbarui & Memperkaya (Enrichment) {len(updates_queue)} data pelanggan lama...")
                for item in updates_queue:
                    try:
                        await execute_with_retry(
                            lambda cid=item["id"], p=item["payload"]: supabase.table("customers").update(p).eq("id", cid).execute()
                        )
                        updated_count += 1
                    except Exception as e:
                        logger.warning(f"Gagal mengupdate pelanggan ID {item['id']}: {e}")
                        error_count += 1

            logger.info(f"Sync Selesai. Baru: {inserted_count}, Diperbarui: {updated_count}, Gagal: {error_count}.")
            return inserted_count, updated_count, error_count

        except Exception as e:
            logger.critical(f"Kegagalan Fatal pada Deep Sync Engine: {e}")
            raise e

# ==============================================================================
# FASTAPI ROUTE HANDLERS (WEB & API CONTROLLERS)
# ==============================================================================

@router.get("/customers", response_class=HTMLResponse)
async def admin_customers(request: Request, admin=Depends(get_current_admin)):
    """
    Rute Utama untuk merender halaman Data Pelanggan.
    """
    pelanggan_final = []
    
    if supabase:
        try:
            res_cust = await execute_with_retry(
                lambda: supabase.table("customers").select("*").order("last_interaction", desc=True).execute()
            )
            
            for c in (res_cust.data or []):
                c['calc_total_orders'] = c.get('total_orders', 0)
                c['calc_total_spent'] = float(c.get('total_spent', 0.0))
                c['username'] = c.get('username') or ''
                c['phone'] = c.get('phone') or ''
                src = c.get('source', 'bot')
                if not src: src = 'bot'
                c['source'] = src.upper() 
                pelanggan_final.append(c)
                
        except Exception as e:
            logger.error(f"Gagal memuat arsitektur data pelanggan: {e}")
            
    # Eksekusi RFM Analytics
    pelanggan_final = CustomerAnalyticsEngine.calculate_rfm_score(pelanggan_final)
    
    logger.audit(admin.get("admin_id"), "VIEW_CUSTOMERS", f"Memuat halaman data pelanggan ({len(pelanggan_final)} records).")
    
    return render_admin_template(
        request, 
        "admin/customers.html", 
        pelanggan=pelanggan_final, 
        admin_data=admin
    )

@router.post("/customers/sync")
async def api_sync_customers(payload: Optional[CustomerSyncPayload] = None, admin=Depends(get_current_admin)):
    """
    API Endpoint untuk memicu Deep Sinkronisasi MTProto.
    """
    admin_id = admin.get("admin_id")
    limit = payload.limit if payload else 1000
    
    logger.audit(admin_id, "TRIGGER_SYNC", f"Meminta sinkronisasi dengan limit {limit}.")
    
    try:
        inserted, updated, errors = await DeepSyncService.run_sync_engine(admin_id, fetch_limit=limit)
        
        if inserted > 0 or updated > 0:
            return api_success(message=f"Deep Sync Berhasil! Menambahkan {inserted} pelanggan baru dan memperkaya data {updated} pelanggan lama.")
        elif errors > 0:
            return api_error(f"Deep Sync selesai dengan peringatan. {errors} data gagal diproses.")
        else:
            return api_success(message="Database sudah up-to-date. Tidak ada riwayat baru dari Telegram.")
            
    except Exception as e:
        logger.error(f"API Sync Crash: {e}")
        return api_error("Gagal melakukan sinkronisasi dengan Telegram API. Pastikan sesi MTProto Anda aktif.", 500)

@router.post("/customers/edit/{cid}")
async def edit_customer(
    cid: str,
    full_name: str = Form(...),
    phone: str = Form(""),
    default_address: str = Form(""),
    admin=Depends(get_current_admin)
):
    """Menangani pembaruan profil pelanggan secara manual"""
    if not supabase: 
        raise HTTPException(status_code=500, detail="Database Offline")
        
    admin_id = admin.get("admin_id")
    try:
        await execute_with_retry(
            lambda: supabase.table("customers").update({
                "full_name": full_name.strip(),
                "phone": phone.strip(),
                "default_address": default_address.strip(),
                "updated_at": datetime.now(timezone.utc).isoformat()
            }).eq("id", cid).execute()
        )
        logger.audit(admin_id, "EDIT_CUSTOMER", f"Memperbarui profil pelanggan ID: {cid}")
        return RedirectResponse(url="/admin/customers", status_code=status.HTTP_303_SEE_OTHER)
        
    except Exception as e:
        logger.error(f"[EDIT CUSTOMER FATAL ERROR]: {e}")
        raise HTTPException(status_code=500, detail="Gagal memperbarui data pelanggan.")


# ==============================================================================
# MAGIC BRIDGE: BROADCAST COMMANDER (DELIVER TO ENGINE DEWA)
# Rute diubah menyesuaikan frontend baru (/crm/customers/broadcast/bulk)
# ==============================================================================
@router.post("/crm/customers/broadcast/bulk")
async def bulk_broadcast_commander(
    payload: CommanderBroadcastPayload,
    bg_tasks: BackgroundTasks, # KUNCI 1: Harus ada bg_tasks untuk eksekusi instan
    admin=Depends(get_current_admin)
):
    """API Broadcast yang sudah 100% nyambung dengan Watchdog Engine V15"""
    if not supabase: 
        return api_error("Database Offline - Broadcast Dibatalkan", 503)
        
    admin_id = admin.get("admin_id")
    
    try:
        import pytz
        from routers.crm.broadcast import execute_broadcast_task, CampaignWatchdog
        
        # 1. Bikin Grup Target dari Customer yang dipilih
        target_list_string = ",".join(map(str, payload.target_ids))
        tpl_tgt_res = await execute_with_retry(
            lambda: supabase.table("crm_templates").insert({
                "name": f"Commander_Targets_{len(payload.target_ids)}_{int(time.time())}",
                "type": "TARGET_GROUP", 
                "content": target_list_string,
                "created_by": admin_id
            }).execute()
        )
        target_template_id = tpl_tgt_res.data[0]['id']

        # 2. Cek Koneksi Telegram (Session ID)
        session_res = await execute_with_retry(
            lambda: supabase.table("crm_telegram_sessions").select("id").eq("admin_id", admin_id).eq("status", "active").execute()
        )
        mtproto_session_id = session_res.data[0]['id'] if session_res.data else None

        # 3. Kunci Timezone ke WIB (Asia/Jakarta)
        wib_tz = pytz.timezone("Asia/Jakarta")
        now_wib = datetime.now(wib_tz)
        
        try:
            dt_obj = datetime.strptime(payload.schedule_time, "%Y-%m-%d %H:%M")
            target_date = wib_tz.localize(dt_obj)
        except:
            target_date = now_wib
            
        # Toleransi 1 menit: Kalau jadwalnya "sekarang", sistem anggap instan
        is_scheduled = target_date > now_wib + timedelta(minutes=1)

        # 4. Insert ke Supabase
        camp_res = await execute_with_retry(
            lambda: supabase.table("crm_campaigns").insert({
                "campaign_name": f"Bulk_Commander_{len(payload.target_ids)}_{int(time.time())}",
                "sender_type": "MTPROTO" if mtproto_session_id else "BOT",
                "session_id": mtproto_session_id,
                "message_template_id": payload.template_id, 
                "target_template_id": target_template_id,   
                "status": "PENDING" if is_scheduled else "PROCESSING", 
                "start_time": target_date.isoformat(),
                "scheduled_at": target_date.isoformat(),  # KUNCI 2: Ini yang di-scan sama Watchdog!
                "frequency": "ONCE",
                "delay_min": payload.settings.min_delay,
                "delay_max": payload.settings.max_delay,
                "batch_size": payload.settings.batch_size,
                "humanized_config": {
                    "delay_min": payload.settings.min_delay,
                    "delay_max": payload.settings.max_delay,
                    "rest_batch": payload.settings.batch_size,
                    "rest_duration_min": 5
                },
                "created_by": admin_id
            }).execute()
        )
        campaign_id = camp_res.data[0]['id']

        # 5. Oper ke Engine Dewa (Watchdog / Background Tasks)
        try:
            if not is_scheduled:
                # Kalau jadwal 'sekarang', langsung tembak pake BackgroundTasks
                bg_tasks.add_task(execute_broadcast_task, str(campaign_id))
                logger.info(f"⚡ [COMMANDER] Campaign {campaign_id[:8]} diluncurkan INSTAN!")
            else:
                # Kalau 'nanti', bangunin Watchdog biar dia yang mantau Supabase
                await CampaignWatchdog.start()
                logger.info(f"⏳ [COMMANDER] Campaign dijadwalkan pada {target_date.strftime('%H:%M WIB')}. Watchdog Siaga!")
                
        except Exception as sched_e:
            logger.error(f"⚠️ [BRIDGE] Gagal meluncurkan ke Engine: {sched_e}")

        logger.audit(admin_id, "COMMANDER_BROADCAST", f"Membuat campaign bulk ke {len(payload.target_ids)} target.")
        
        return api_success(
            message=f"Mantap! Campaign dijadwalkan ke {len(payload.target_ids)} pelanggan.",
            data={"campaign_id": campaign_id, "queued_count": len(payload.target_ids)}
        )
        
    except Exception as e:
        logger.error(f"[COMMANDER BROADCAST FATAL]: {e}")
        return api_error("Gagal memulai kampanye broadcast.", 500)


# ==============================================================================
# SERVER-SIDE EXPORT ENGINE (API)
# ==============================================================================
@router.get("/customers/export/csv")
async def export_customers_csv(admin=Depends(get_current_admin)):
    """Engine Export Server-Side untuk menghasilkan CSV jika data puluhan ribu"""
    if not supabase: raise HTTPException(status_code=503, detail="Database Offline")
    
    logger.audit(admin.get("admin_id"), "EXPORT_DATA", "Mendownload CSV Data Pelanggan.")
    
    try:
        res = await execute_with_retry(
            lambda: supabase.table("customers").select("*").order("created_at", desc=True).execute()
        )
        data = res.data or []
        
        output = io.StringIO()
        writer = csv.writer(output, quoting=csv.QUOTE_MINIMAL)
        writer.writerow(["ID", "Telegram ID", "Full Name", "Username", "Phone", "Source", "Total Orders", "Total Spent", "Last Interaction", "Join Date"])
        
        for c in data:
            writer.writerow([
                c.get("id", ""),
                c.get("telegram_id", ""),
                c.get("full_name", ""),
                c.get("username", ""),
                c.get("phone", ""),
                c.get("source", "bot"),
                c.get("total_orders", 0),
                c.get("total_spent", 0.0),
                c.get("last_interaction", ""),
                c.get("created_at", "")
            ])
            
        output.seek(0)
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=BABA_Customers_Export_{datetime.now().strftime('%Y%m%d')}.csv"}
        )
    except Exception as e:
        logger.error(f"Export CSV Error: {e}")
        raise HTTPException(status_code=500, detail="Gagal mengekspor data.")
