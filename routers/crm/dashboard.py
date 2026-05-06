"""
====================================================================================
BABA PARFUME - CRM DASHBOARD ENGINE (BACKEND) [ENTERPRISE]
====================================================================================
Deskripsi : Engine untuk menyuplai data analitik ke CRM Dashboard secara Real-Time.
            Mengelola metrik kampanye, efektivitas blast, status MTProto, 
            dan aktivitas AI Google Gemini.
====================================================================================
"""
import logging
from datetime import datetime
from typing import Dict, Any

from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse

from routers.common import supabase, render_admin_template
from routers.dependencies import get_current_admin

logger = logging.getLogger("baba.crm.dashboard")

router = APIRouter(prefix="/admin/crm", tags=["CRM Dashboard"])

# ==============================================================================
# 1. RENDER PAGE
# ==============================================================================
@router.get("/dashboard", response_class=HTMLResponse)
async def crm_dashboard_page(request: Request, admin=Depends(get_current_admin)):
    """Menampilkan skeleton HTML Dashboard CRM"""
    return render_admin_template(
        request, 
        "crm/dashboard.html",
        admin_data=admin
    )

# ==============================================================================
# 2. API ENDPOINT: DASHBOARD STATS (REAL-TIME POLLING ENGINE)
# ==============================================================================
@router.get("/api/stats")
async def get_crm_stats(admin=Depends(get_current_admin)):
    """Mengambil data statistik CRM real-time dari seluruh tabel Supabase"""
    if not supabase:
        return JSONResponse(status_code=503, content={"status": "error", "message": "Database offline"})

    admin_id = admin.get("admin_id")

    try:
        # ---------------------------------------------------------
        # A. CEK KONEKSI MTPROTO ADMIN
        # ---------------------------------------------------------
        mtproto_status = {"online": False, "phone": ""}
        session_res = supabase.table("crm_telegram_sessions")\
                              .select("phone_number, status")\
                              .eq("admin_id", admin_id)\
                              .eq("status", "active")\
                              .execute()
        
        if session_res.data:
            mtproto_status["online"] = True
            mtproto_status["phone"] = session_res.data[0].get("phone_number", "")

        # ---------------------------------------------------------
        # B. HITUNG METRIKS UTAMA (ANALYTICS)
        # ---------------------------------------------------------
        # 1. Total Sent (Total semua baris di tabel logs)
        log_res = supabase.table("crm_blast_logs").select("status", count="exact").execute()
        total_logs = log_res.count or 0
        
        # 2. Success Rate
        success_res = supabase.table("crm_blast_logs").select("id", count="exact").eq("status", "SUCCESS").execute()
        total_success = success_res.count or 0
        success_rate = round((total_success / total_logs * 100), 1) if total_logs > 0 else 0

        # 3. Active Campaigns
        active_camp_res = supabase.table("crm_campaigns").select("id", count="exact").in_("status", ["RUNNING", "RESTING"]).execute()
        active_campaigns = active_camp_res.count or 0

        # 4. AI Hits (Dari tabel pesan AI)
        ai_res = supabase.table("ai_chat_messages").select("id", count="exact").eq("role", "assistant").execute()
        ai_hits = ai_res.count or 0

        # ---------------------------------------------------------
        # C. LIST KAMPANYE TERKINI (Top 5)
        # ---------------------------------------------------------
        campaigns_list = []
        
        # FIX: Hapus total_target_cache dari query select biar PostgreSQL gak ngamuk
        c_res = supabase.table("crm_campaigns")\
                        .select("id, campaign_name, sender_type, status, target_template_id")\
                        .order("created_at", desc=True)\
                        .limit(5)\
                        .execute()
        
        t_res = supabase.table("crm_templates").select("id, content").eq("type", "TARGET_GROUP").execute()
        targets_dict = {t['id']: t['content'] for t in t_res.data or []}
        
        for c in c_res.data or []:
            c_logs = supabase.table("crm_blast_logs").select("id", count="exact").eq("campaign_id", c['id']).eq("status", "SUCCESS").execute()
            done = c_logs.count or 0
            
            tgt_content = targets_dict.get(c['target_template_id'], "")
            
            # Logic baru: Cek apakah target merupakan Smart Follow-up (DYNAMIC_FOLLOWUP)
            if tgt_content and tgt_content.startswith("DYNAMIC_FOLLOWUP"):
                try:
                    # Ambil limit dari string (contoh: "DYNAMIC_FOLLOWUP:50")
                    total_target = int(tgt_content.split(":")[1])
                except:
                    total_target = 100 # Fallback jika parsing gagal
            elif tgt_content:
                # Jika folder biasa, hitung jumlah ID yang dipisah koma
                total_target = len([i for i in tgt_content.split(',') if i.strip()])
            else:
                total_target = 0
                
            prog = min(round((done / total_target * 100), 1), 100) if total_target > 0 else 0
            if c['status'] == 'COMPLETED': prog = 100

            campaigns_list.append({
                "id": c['id'],
                "name": c['campaign_name'],
                "type": c['sender_type'],
                "progress": prog,
                "status": c['status'],
                "total_target": total_target
            })

        # ---------------------------------------------------------
        # D. LOG AKTIVITAS TERBARU (Mini Logs)
        # ---------------------------------------------------------
        recent_logs = []
        activities = supabase.table("crm_blast_logs")\
                             .select("status, target_id, sent_at, error_message")\
                             .order("sent_at", desc=True)\
                             .limit(6)\
                             .execute()
        
        for act in activities.data or []:
            status_type = "SUCCESS" if act['status'] == "SUCCESS" else "ERROR"
            
            if status_type == "SUCCESS":
                msg = f"Berhasil mengirim pesan ke target: {act['target_id']}"
            else:
                err_cause = act.get('error_message', 'Unknown Error')
                msg = f"Gagal mengirim ke {act['target_id']} ({err_cause[:30]}...)"
                
            recent_logs.append({
                "id": act.get("target_id", "") + str(act.get("sent_at", "")),
                "type": status_type,
                "msg": msg,
                "time_iso": act['sent_at'] 
            })

        return {
            "status": "success",
            "metrics": {
                "total_sent": total_success,
                "success_rate": success_rate,
                "active_campaigns": active_campaigns,
                "ai_hits": ai_hits
            },
            "campaigns": campaigns_list,
            "recent_logs": recent_logs,
            "connection": mtproto_status
        }

    except Exception as e:
        logger.error(f"❌ [CRM STATS ERROR]: {str(e)}")
        return JSONResponse(status_code=500, content={"status": "error", "message": "Gagal memproses data analitik dashboard"})