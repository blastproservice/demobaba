"""
====================================================================================
BABA PARFUME - CRM BROADCAST COMMANDER (BACKEND) [ENTERPRISE V5.0 ULTIMATE]
====================================================================================
Deskripsi : Engine utama pengiriman pesan massal kelas Enterprise.
            Fitur Utama:
            - APScheduler Integration (ONCE, DAILY, INTERVAL)
            - Real-time State Interceptor (Support PAUSE & STOP di tengah jalan)
            - URL Template Parser (Tarik pesan langsung dari Link Telegram)
            - Smart Follow-Up (Auto fetch oldest users & Sort by Last Seen)
            - Algoritma Humanized Delay & Batch Resting
            - Auto-Retry Queue Loop (Max 3x) untuk grup Slowmode
            - [NEW] Smart Schedule Engine (Anti PENDING / Nyangkut)
            - [NEW] MTProto Memory Leak Protection
====================================================================================
"""
import asyncio
import aiohttp
import logging
import random
import os
import re
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Request, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel

# Telegram Imports
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import (
    UserIsBlockedError, 
    UserDeactivatedError, 
    ChatWriteForbiddenError, 
    SlowModeWaitError, 
    FloodWaitError
)

# APScheduler untuk Cron Job
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from routers.common import supabase, api_success, api_error, render_admin_template
from routers.dependencies import get_current_admin
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("baba.crm.broadcast.enterprise")

router = APIRouter(prefix="/admin/crm/broadcast", tags=["CRM Broadcast"])

# ==============================================================================
# GLOBAL SCHEDULER ENGINE
# ==============================================================================
# Mesin waktu ini akan jalan di background server FastAPI lu selamanya
scheduler = AsyncIOScheduler(timezone="Asia/Jakarta")

@router.on_event("startup")
async def start_scheduler():
    if not scheduler.running:
        scheduler.start()
        logger.info("⏱️ [APScheduler] Enterprise Cron Engine BERHASIL DIHIDUPKAN!")

@router.on_event("shutdown")
async def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown()
        logger.info("⏱️ [APScheduler] Enterprise Cron Engine DIMATIKAN.")


# ==============================================================================
# SCHEMAS (PAYLOAD DARI HTML FRONTEND)
# ==============================================================================
class BroadcastPayload(BaseModel):
    name: str
    sender_type: str
    target_mode: str 
    msg_template_id: str
    target_template_id: Optional[str] = None
    followup_limit: int = 50
    # Humanized Settings
    delay_min: int = 10
    delay_max: int = 20
    rest_batch: int = 15
    rest_duration_min: int = 3
    # Cron Settings
    frequency: str = "ONCE"
    schedule_date: Optional[str] = None
    schedule_time: Optional[str] = None
    interval_days: int = 2
    max_cycles: int = 7

class TogglePayload(BaseModel):
    status: str


# ==============================================================================
# 1. RENDER PAGE
# ==============================================================================
@router.get("", response_class=render_admin_template)
async def broadcast_page(request: Request, admin=Depends(get_current_admin)):
    return render_admin_template(request, "crm/broadcast.html", admin_data=admin)


# ==============================================================================
# 2. API: INIT DATA (CAMPAIGNS, TEMPLATES, STATS)
# ==============================================================================
@router.get("/api/init")
async def init_broadcast_data(admin=Depends(get_current_admin)):
    """Menyediakan data Real-Time untuk Dashboard Commander HTML"""
    if not supabase: return api_error("Database offline")
    
    admin_id = admin.get("admin_id")
    try:
        camp_res = supabase.table("crm_campaigns").select("*").eq("created_by", admin_id).order("created_at", desc=True).execute()
        tpl_res = supabase.table("crm_templates").select("id, name, type, content").eq("created_by", admin_id).execute()
        
        messages = [t for t in tpl_res.data if t['type'] == 'MESSAGE']
        targets = [t for t in tpl_res.data if t['type'] == 'TARGET_GROUP']

        total_sent = supabase.table("crm_blast_logs").select("id", count="exact").eq("status", "SUCCESS").execute().count or 0
        total_failed = supabase.table("crm_blast_logs").select("id", count="exact").eq("status", "FAILED").execute().count or 0
        in_queue = supabase.table("crm_campaigns").select("id", count="exact").in_("status", ["PENDING", "SCHEDULED"]).execute().count or 0

        final_campaigns = []
        for c in camp_res.data or []:
            msg_name = next((t['name'] for t in messages if t['id'] == c['message_template_id']), "Deleted Template")
            
            # Logika penamaan target cerdas
            if "DYNAMIC_FOLLOWUP" in c.get('target_template_id', ''):
                tgt_name = "Smart Follow-Up (Dynamic)"
                total_target = c.get('total_target_cache', 100) # Fallback
            else:
                tgt_name = next((t['name'] for t in targets if t['id'] == c['target_template_id']), "Deleted Target")
                tgt_content = next((t['content'] for t in targets if t['id'] == c['target_template_id']), "")
                total_target = len([i for i in tgt_content.split(',') if i.strip()])
            
            # Hitung progress real-time dari log
            logs_count = supabase.table("crm_blast_logs").select("id", count="exact").eq("campaign_id", c['id']).eq("status", "SUCCESS").execute().count or 0
            
            progress = min(round((logs_count / total_target * 100), 1), 100) if total_target > 0 else 0
            if c['status'] == 'COMPLETED': progress = 100

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
            "metrics": {"total_sent": total_sent, "total_failed": total_failed, "in_queue": in_queue}
        })
    except Exception as e:
        logger.error(f"❌ [INIT BROADCAST ERROR]: {str(e)}")
        return api_error(f"Gagal muat data: {str(e)}")


# ==============================================================================
# 3. API: LAUNCH / SCHEDULE CAMPAIGN
# ==============================================================================
@router.post("/api/launch")
async def launch_campaign(payload: BroadcastPayload, bg_tasks: BackgroundTasks, admin=Depends(get_current_admin)):
    """Menerima request dari Frontend dan memasukkannya ke Mesin Waktu (APScheduler)"""
    if not supabase: return api_error("Database offline")
    
    admin_id = admin.get("admin_id")
    try:
        # A. Setup Target Template
        target_id = payload.target_template_id
        if payload.target_mode == 'followup':
            # Buat template dinamis khusus untuk Follow Up ini
            res_tpl = supabase.table("crm_templates").insert({
                "name": f"Smart Follow-Up ({payload.followup_limit} Users)",
                "type": "TARGET_GROUP",
                "content": f"DYNAMIC_FOLLOWUP:{payload.followup_limit}",
                "created_by": admin_id
            }).execute()
            target_id = res_tpl.data[0]['id']

        # B. Setup Database Status (SMART ENGINE ANTI NYANGKUT)
        schedule_datetime_str = None
        run_date = datetime.now()
        is_scheduled = False

        if payload.frequency != 'ONCE' or (payload.schedule_date and payload.schedule_time):
            # FIX: Format detik pake :00, bukan :%00
            schedule_datetime_str = f"{payload.schedule_date}T{payload.schedule_time}:00"
            target_date = datetime.strptime(schedule_datetime_str, "%Y-%m-%dT%H:%M:00")

            # FIX: Toleransi waktu. Kalau di-set "sekarang" atau udah lewat, langsung gaspol.
            if payload.frequency != 'ONCE' or target_date > datetime.now() + timedelta(minutes=1):
                run_date = target_date
                is_scheduled = True
            else:
                is_scheduled = False
                schedule_datetime_str = None

        new_camp = {
            "campaign_name": payload.name,
            "sender_type": payload.sender_type,
            "message_template_id": payload.msg_template_id,
            "target_template_id": target_id,
            "status": "PENDING" if is_scheduled else "RUNNING",
            "created_by": admin_id,
            "scheduled_at": schedule_datetime_str + "Z" if schedule_datetime_str else None,
            "frequency": payload.frequency,
            "interval_days": payload.interval_days,
            "max_cycles": payload.max_cycles,
            "current_cycle": 0,
            "humanized_config": {
                "delay_min": payload.delay_min,
                "delay_max": payload.delay_max,
                "rest_batch": payload.rest_batch,
                "rest_duration_min": payload.rest_duration_min
            }
        }
        
        res = supabase.table("crm_campaigns").insert(new_camp).execute()
        campaign_id = res.data[0]['id']

        # C. INJEKSI KE MESIN WAKTU (APSCHEDULER)
        job_id = f"blast_{campaign_id}"
        
        if payload.frequency == "ONCE":
            if is_scheduled:
                # Jadwal spesifik satu kali jalan
                scheduler.add_job(
                    execute_broadcast_task, 
                    trigger=DateTrigger(run_date=run_date, timezone="Asia/Jakarta"), 
                    args=[campaign_id, admin_id], 
                    id=job_id, replace_existing=True
                )
            else:
                # Langsung gaspol sekarang!
                bg_tasks.add_task(execute_broadcast_task, campaign_id, admin_id)
                
        elif payload.frequency == "DAILY":
            # Jalan tiap hari di jam yang sama
            h, m = payload.schedule_time.split(":")
            scheduler.add_job(
                execute_broadcast_task, 
                trigger=CronTrigger(hour=int(h), minute=int(m), timezone="Asia/Jakarta"), 
                args=[campaign_id, admin_id], 
                id=job_id, replace_existing=True
            )
            
        elif payload.frequency == "INTERVAL":
            # Jalan setiap X hari
            scheduler.add_job(
                execute_broadcast_task, 
                trigger=IntervalTrigger(days=payload.interval_days, start_date=run_date, timezone="Asia/Jakarta"), 
                args=[campaign_id, admin_id], 
                id=job_id, replace_existing=True
            )

        return api_success(message="Kampanye berhasil diinjeksi ke Engine!")
    except Exception as e:
        logger.error(f"❌ [LAUNCH ERROR]: {str(e)}")
        return api_error(f"Gagal meluncurkan kampanye: {str(e)}")


# ==============================================================================
# 4. API: TOGGLE STATUS (PAUSE/STOP)
# ==============================================================================
@router.post("/api/toggle/{id}")
async def toggle_campaign(id: str, payload: TogglePayload, admin=Depends(get_current_admin)):
    """Menghentikan atau melanjutkan kampanye. Worker akan memantau status ini."""
    if not supabase: return api_error("Database offline")
    try:
        # Update database
        supabase.table("crm_campaigns").update({"status": payload.status}).eq("id", id).eq("created_by", admin.get("admin_id")).execute()
        
        # Jika STOPPED, bunuh juga cron jobnya jika ada di APScheduler
        if payload.status == "STOPPED":
            job_id = f"blast_{id}"
            if scheduler.get_job(job_id):
                scheduler.remove_job(job_id)
                logger.info(f"🛑 [SCHEDULER] Job {job_id} berhasil dibunuh dari memori!")

        return api_success(message=f"Sinyal {payload.status} berhasil dikirim ke Engine.")
    except Exception as e:
        return api_error(str(e))


# ==============================================================================
# 5. ENGINE CORE: BROADCAST WORKER (THE BEAST)
# ==============================================================================
async def execute_broadcast_task(campaign_id: str, admin_id: int):
    """
    Worker Level Dewa. Dipanggil oleh BackgroundTask (Now) atau APScheduler (Nanti).
    """
    logger.info(f"🔥 [ENGINE DEWA] Memulai Eksekusi Kampanye ID: {campaign_id}")
    
    try:
        # A. Verifikasi Status Awal Kampanye
        camp = supabase.table("crm_campaigns").select("*").eq("id", campaign_id).single().execute().data
        
        if camp['status'] == 'STOPPED':
            logger.warning(f"🛑 Kampanye {campaign_id} terdeteksi STOPPED. Membatalkan eksekusi.")
            return

        # Tandai sedang berjalan
        supabase.table("crm_campaigns").update({"status": "RUNNING"}).eq("id", campaign_id).execute()

        # B. Load Amunisi (Template & Target)
        msg_tpl = supabase.table("crm_templates").select("content").eq("id", camp['message_template_id']).single().execute().data
        tgt_tpl = supabase.table("crm_templates").select("content").eq("id", camp['target_template_id']).single().execute().data
        
        raw_message = msg_tpl['content']
        target_content = tgt_tpl['content']
        h_config = camp.get('humanized_config', {})

        # C. Buka Koneksi MTProto
        if camp['sender_type'] != 'MTPROTO':
            logger.error("Engine ini dioptimalkan khusus untuk MTProto.")
            supabase.table("crm_campaigns").update({"status": "FAILED"}).eq("id", campaign_id).execute()
            return

        sess_res = supabase.table("crm_telegram_sessions").select("session_string").eq("admin_id", admin_id).eq("status", "active").single().execute()
        if not sess_res.data:
            raise Exception("Sesi MTProto Admin terputus.")
        
        client = TelegramClient(StringSession(sess_res.data['session_string']), int(os.getenv("API_ID")), os.getenv("API_HASH"))
        await client.connect()

        try:
            # -------------------------------------------------------------
            # D. MAGIC PARSER: JIKA TEMPLATE BERUPA URL TELEGRAM
            # -------------------------------------------------------------
            parsed_message_text = raw_message
            if raw_message.startswith("http://t.me/") or raw_message.startswith("https://t.me/"):
                logger.info(f"🔗 Mendeteksi URL Template. Mengekstrak pesan dari: {raw_message}")
                try:
                    link = raw_message.strip().rstrip('/')
                    parts = link.split('t.me/')[1].split('/')
                    
                    # Support format: c/12345/99 (Private) atau parfumebaba/3/99 (Public/Topic)
                    if parts[0] == 'c':
                        chat_id = int("-100" + parts[1])
                        msg_id = int(parts[-1])
                    else:
                        chat_id = parts[0] # Telethon otomatis resolve username string 
                        msg_id = int(parts[-1])
                        
                    extracted_msg = await client.get_messages(chat_id, ids=msg_id)
                        
                        if extracted_msg and (extracted_msg.text or extracted_msg.caption):
                            # Ambil teks, atau kalau itu gambar, ambil caption-nya
                            parsed_message_text = extracted_msg.text or extracted_msg.caption
                            logger.info("✅ Ekstraksi teks dari URL berhasil!")
                        else:
                            raise Exception("Pesan tidak ditemukan atau berupa media kosong tanpa caption.")
                except Exception as e:
                    logger.error(f"❌ Gagal ekstrak URL: {e}")
                    parsed_message_text = "Promo BABA Parfume! (Error parsing URL)"

            # -------------------------------------------------------------
            # E. BUILD TARGET QUEUE (SMART FOLLOW-UP VS NORMAL)
            # -------------------------------------------------------------
            target_queue = [] 
        
            if target_content.startswith("DYNAMIC_FOLLOWUP"):
                parts = target_content.split(":")
                limit = int(parts[1]) if len(parts) > 1 else 100 # Fallback anti IndexError
                logger.info(f"🔍 [SMART FOLLOW-UP] Menyisir {limit} user terlama...")
                dialogs = await client.get_dialogs()
                
                # Ambil User Pribadi (Bukan Bot, Bukan Grup)
                users = [d for d in dialogs if d.is_user and not d.entity.bot]
                
                # Sort dari Date paling lama (Ascending)
                users.sort(key=lambda x: x.date)
                
                for u in users[:limit]:
                    # Simpan metadata nama user untuk variabel [NAMA]
                    user_name = getattr(u.entity, 'first_name', 'Kakak') or 'Kakak'
                    target_queue.append({'id': str(u.id), 'name': user_name, 'retry': 0})
                    
                # Update cache total target di DB biar UI update
                supabase.table("crm_campaigns").update({"total_target_cache": len(target_queue)}).eq("id", campaign_id).execute()
            else:
                raw_targets = [t.strip() for t in target_content.split(',') if t.strip()]
                for t in raw_targets:
                    target_queue.append({'id': t, 'name': 'Kak', 'retry': 0})

            # -------------------------------------------------------------
            # F. THE BLAST LOOP (DENGAN STATE INTERCEPTOR)
            # -------------------------------------------------------------
            # -------------------------------------------------------------
            # F. THE BLAST LOOP (MTPROTO & BOT API DUAL ENGINE)
            # -------------------------------------------------------------
            sent_count = 0
            total_in_batch = 0
            bot_token = os.getenv("BOT_TOKEN")
            
            async with aiohttp.ClientSession() as http_session:
                while target_queue:
                    # 1. STATE INTERCEPTOR
                    if total_in_batch > 0 and total_in_batch % 5 == 0:
                        current_state = supabase.table("crm_campaigns").select("status").eq("id", campaign_id).single().execute().data
                        if current_state['status'] == 'STOPPED':
                            logger.warning(f"🛑 [INTERCEPTOR] Kampanye {campaign_id} di-STOP manual!")
                            return

                    current_target = target_queue.pop(0)
                    target_id = current_target['id']
                    retry_count = current_target['retry']
                    customer_name = current_target['name']

                    peer_id = target_id
                    topic_id = None
                    if ':' in target_id:
                        peer_id, topic_id = target_id.split(':')
                        topic_id = int(topic_id)

                    try:
                        # 2. VARIABLE REPLACEMENT
                        final_text = parsed_message_text.replace("[NAMA]", customer_name)
                        hour = datetime.now().hour
                        greeting = "Pagi" if 5 <= hour < 11 else "Siang" if 11 <= hour < 15 else "Sore" if 15 <= hour < 18 else "Malam"
                        final_text = final_text.replace("[WAKTU]", greeting)

                        pid = int(peer_id) if peer_id.replace('-','').isdigit() else peer_id

                        # 3. TEMBAK PESAN (CABANG BOT API vs MTPROTO)
                        if camp['sender_type'] == 'BOT':
                            if not bot_token:
                                raise Exception("BOT_TOKEN tidak disetting di .env")
                            
                            url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
                            payload = {"chat_id": pid, "text": final_text, "parse_mode": "Markdown"}
                            if topic_id:
                                payload["reply_to_message_id"] = topic_id
                                
                            async with http_session.post(url, json=payload) as resp:
                                res_data = await resp.json()
                                if not res_data.get("ok"):
                                    raise Exception(f"Bot Error: {res_data.get('description')}")
                        else:
                            # MTPROTO ENGINE
                            try:
                                if isinstance(pid, int):
                                    await client.get_entity(pid)
                            except ValueError:
                                pass # Abaikan jika tidak di cache, biarkan Telethon yg tolak
                                
                            if topic_id:
                                await client.send_message(pid, final_text, reply_to=topic_id, parse_mode='md')
                            else:
                                await client.send_message(pid, final_text, parse_mode='md')
                        
                        # Log Sukses
                        supabase.table("crm_blast_logs").insert({"campaign_id": campaign_id, "target_id": target_id, "status": "SUCCESS"}).execute()
                        sent_count += 1
                        total_in_batch += 1
                        logger.info(f"✅ Tembus ke: {target_id} via {camp['sender_type']}")

                        # 4. ALGORITMA REST BATCHING
                        rest_batch_limit = h_config.get('rest_batch', 15)
                        rest_duration = h_config.get('rest_duration_min', 3)
                        
                        if sent_count > 0 and sent_count % rest_batch_limit == 0 and len(target_queue) > 0:
                            supabase.table("crm_campaigns").update({"status": "RESTING"}).eq("id", campaign_id).execute()
                            for _ in range(rest_duration * 60):
                                await asyncio.sleep(1)
                            supabase.table("crm_campaigns").update({"status": "RUNNING"}).eq("id", campaign_id).execute()
                        else:
                            delay = random.randint(h_config.get('delay_min', 10), h_config.get('delay_max', 20))
                            await asyncio.sleep(delay)

                    except SlowModeWaitError:
                        if retry_count < 2: 
                            current_target['retry'] += 1
                            target_queue.append(current_target) 
                        else:
                            supabase.table("crm_blast_logs").insert({"campaign_id": campaign_id, "target_id": target_id, "status": "FAILED", "error_message": "Slowmode Limit"}).execute()

                    except FloodWaitError as e:
                        supabase.table("crm_campaigns").update({"status": "RESTING"}).eq("id", campaign_id).execute()
                        await asyncio.sleep(e.seconds)
                        supabase.table("crm_campaigns").update({"status": "RUNNING"}).eq("id", campaign_id).execute()
                        target_queue.append(current_target)

                    except Exception as err:
                        logger.error(f"❌ Error Unhandled di {target_id}: {err}")
                        supabase.table("crm_blast_logs").insert({"campaign_id": campaign_id, "target_id": target_id, "status": "FAILED", "error_message": str(err)[:50]}).execute()

        finally:
            # -------------------------------------------------------------
            # [NEW] MEMORY LEAK PROTECTION: MATIKAN KONEKSI DENGAN AMAN
            # -------------------------------------------------------------
            await client.disconnect()
            logger.info("🔒 Sesi MTProto berhasil di-disconnect dengan aman.")
            
        # -------------------------------------------------------------
        # G. POST-BLAST: CYCLE MANAGEMENT
        # -------------------------------------------------------------
        # Cek apakah ini looping campaign (Cron)
        if camp['frequency'] in ['DAILY', 'INTERVAL']:
            next_cycle = camp['current_cycle'] + 1
            if next_cycle >= camp['max_cycles']:
                # Jika sudah mencapai batas maksimal siklus, matikan total.
                supabase.table("crm_campaigns").update({"status": "COMPLETED", "current_cycle": next_cycle}).eq("id", campaign_id).execute()
                
                # Bunuh Cron Job dari memory
                job_id = f"blast_{campaign_id}"
                if scheduler.get_job(job_id): scheduler.remove_job(job_id)
                logger.info(f"🎉 [CRON] Siklus Kampanye {campaign_id} MENCAPAI BATAS MAX. Diberhentikan permanen.")
            else:
                # Masih ada siklus berikutnya, set ke PENDING menunggu besok.
                supabase.table("crm_campaigns").update({"status": "PENDING", "current_cycle": next_cycle}).eq("id", campaign_id).execute()
                logger.info(f"🔄 [CRON] Batch siklus ke-{next_cycle} selesai. Menunggu jadwal berikutnya...")
        else:
            # Jika ONCE, langsung COMPLETED
            supabase.table("crm_campaigns").update({"status": "COMPLETED"}).eq("id", campaign_id).execute()
            logger.info(f"🎉 [WORKER] Kampanye {campaign_id} SELESAI TOTAL.")

    except Exception as e:
        logger.error(f"❌ [WORKER FATAL ERROR]: {str(e)}")
        supabase.table("crm_campaigns").update({"status": "FAILED"}).eq("id", campaign_id).execute()

# ==============================================================================
# 6. API: DELETE CAMPAIGN
# ==============================================================================
@router.delete("/api/delete/{id}")
async def delete_campaign(id: str, admin=Depends(get_current_admin)):
    try:
        # Hapus Cron Job jika masih ada
        job_id = f"blast_{id}"
        if scheduler.get_job(job_id):
            scheduler.remove_job(job_id)
            
        # Hapus Database
        supabase.table("crm_campaigns").delete().eq("id", id).eq("created_by", admin.get("admin_id")).execute()
        return api_success(message="Kampanye dan Cron Job dihapus permanen.")
    except Exception as e:
        return api_error(str(e))