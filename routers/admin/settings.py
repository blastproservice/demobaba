"""
====================================================================================
BABA PARFUME - SYSTEM SETTINGS ENGINE (ENTERPRISE V4.0)
====================================================================================
Deskripsi : Menangani halaman Pengaturan Sistem Pusat.
            - CRUD Informasi Toko & AI Config
            - Manajemen & Moderasi Testimoni (Approve/Reject)
            - Manajemen Loyalty Rewards
            - Cek status koneksi MTProto (Telegram Userbot)
====================================================================================
"""
import logging
from typing import Optional
from fastapi import APIRouter, Request, Form, HTTPException, status, Depends
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from pydantic import BaseModel, Field

# Gunakan fungsi render tersentralisasi dari common.py
from routers.common import require_admin_roles, render_admin_template
from routers.dependencies import get_current_admin

logger = logging.getLogger("baba.settings")

try:
    from database import supabase
except ImportError:
    logger.critical("❌ [SYSTEM] File database.py tidak ditemukan!")
    supabase = None

# Inisiasi Router
router = APIRouter(prefix="/admin", tags=["Admin Settings"])

# ==============================================================================
# SCHEMAS UNTUK API AJAX
# ==============================================================================
class ModerateReviewPayload(BaseModel):
    review_id: str
    action: str = Field(..., description="'approve' atau 'reject'")

class RewardPayload(BaseModel):
    name: str
    cost: int = Field(..., gt=0)
    desc: Optional[str] = ""

def get_pending_count() -> int:
    if not supabase: return 0
    try:
        res = supabase.table("orders").select("id", count="exact").eq("status", "Menunggu Pembayaran").execute()
        return res.count or 0
    except Exception as e:
        logger.error(f"Error count pending: {e}")
        return 0

# ==============================================================================
# 1. RENDER HALAMAN PENGATURAN COMMAND CENTER
# ==============================================================================
@router.get("/settings", response_class=HTMLResponse, dependencies=[require_admin_roles("super_admin")])
async def admin_settings(request: Request, admin=Depends(get_current_admin)):
    # Default fallback
    settings_data = {
        "store_name": "BABA Parfume", 
        "admin_whatsapp": "", 
        "store_email": "",
        "store_address": "",
        "checkout_message": "Halo BABA Parfume, saya mau pesan...",
        "is_bot_active": True,
        "maintenance_mode": False,
        "ai_system_prompt": "Anda adalah representatif Customer Service dari BABA Parfume..."
    }
    
    mtproto_data = {"status": "disconnected", "phone": ""}
    pending_reviews = []
    rewards_list = []
    
    if supabase:
        try:
            # A. Tarik data Store Settings & AI Config
            res_set = supabase.table("store_settings").select("*").eq("id", 1).single().execute()
            if res_set.data: 
                settings_data.update(res_set.data)
                
            # B. Cek status koneksi MTProto
            admin_id = admin.get("admin_id")
            if admin_id:
                session_res = supabase.table("crm_telegram_sessions")\
                                      .select("phone_number, status")\
                                      .eq("admin_id", admin_id)\
                                      .eq("status", "active")\
                                      .execute()
                
                if session_res.data and len(session_res.data) > 0:
                    mtproto_data["status"] = "connected"
                    mtproto_data["phone"] = session_res.data[0].get("phone_number", "")

            # C. Tarik Ulasan yang Butuh Moderasi (is_approved = False)
            res_reviews = supabase.table("testimonials")\
                                  .select("id, rating, review_text, created_at, customer:customers(full_name)")\
                                  .eq("is_approved", False)\
                                  .order("created_at", desc=False)\
                                  .execute()
            
            for r in (res_reviews.data or []):
                pending_reviews.append({
                    "id": r.get("id"),
                    "customer_name": r.get("customer", {}).get("full_name", "Pelanggan"),
                    "rating": r.get("rating"),
                    "text": r.get("review_text", ""),
                    "date": r.get("created_at")[:16].replace("T", " ") # Format simple YYYY-MM-DD HH:MM
                })

            # D. Tarik Daftar Loyalty Rewards
            res_rewards = supabase.table("store_rewards").select("*").eq("is_active", True).order("cost_in_points").execute()
            for w in (res_rewards.data or []):
                rewards_list.append({
                    "id": w.get("id"),
                    "name": w.get("name"),
                    "desc": w.get("description", ""),
                    "cost": w.get("cost_in_points"),
                    "icon": w.get("icon_name", "gift")
                })
                    
        except Exception as e:
            logger.error(f"⚠️ [INFO SETTING]: Gagal menarik data setting. Detail: {e}")
            
    return render_admin_template(
        request, 
        "admin/settings.html", 
        admin_data=admin,
        settings=settings_data, 
        mtproto=mtproto_data,
        pending_reviews=pending_reviews,
        rewards=rewards_list,
        pending_count=get_pending_count()
    )

# ==============================================================================
# 2. API UPDATE STORE SETTINGS (HTML FORM POST)
# ==============================================================================
@router.post("/settings/update", dependencies=[require_admin_roles("super_admin")])
async def update_settings(
    store_name: str = Form("BABA Parfume"),
    admin_whatsapp: str = Form(""),
    store_email: str = Form(""),
    store_address: str = Form(""),
    checkout_message: str = Form(""),
    ai_system_prompt: str = Form(""),
    is_bot_active: str = Form("false"),
    maintenance_mode: str = Form("false"),
    admin=Depends(get_current_admin)
):
    try:
        # PENGAMANAN BOOLEAN DARI FORM HTML
        bot_status = True if str(is_bot_active).lower() in ['true', 'on', '1', 'yes'] else False
        maint_status = True if str(maintenance_mode).lower() in ['true', 'on', '1', 'yes'] else False
        
        payload = {
            "store_name": store_name,
            "admin_whatsapp": admin_whatsapp,
            "store_email": store_email,
            "store_address": store_address,
            "checkout_message": checkout_message,
            "ai_system_prompt": ai_system_prompt,
            "is_bot_active": bot_status,
            "maintenance_mode": maint_status
        }
        
        if supabase:
            supabase.table("store_settings").upsert({**payload, "id": 1}).execute()
            logger.info(f"✅ [SUKSES] Engine Settings di-update oleh {admin.get('admin_name')}")
            
        return RedirectResponse(url="/admin/settings", status_code=status.HTTP_303_SEE_OTHER)
        
    except Exception as e:
        logger.error(f"❌ [ERROR SETTING]: {e}")
        raise HTTPException(status_code=500, detail="Gagal menyimpan pengaturan sistem.")

# ==============================================================================
# 3. API MODERASI TESTIMONI (AJAX)
# ==============================================================================
@router.post("/api/settings/testimonials/moderate", dependencies=[require_admin_roles("super_admin")])
async def moderate_testimoni(payload: ModerateReviewPayload):
    if not supabase: return JSONResponse({"status": "error", "message": "Database Offline"}, status_code=503)
    
    try:
        if payload.action == "approve":
            supabase.table("testimonials").update({"is_approved": True}).eq("id", payload.review_id).execute()
            msg = "Ulasan berhasil di-approve dan tayang di Store!"
        elif payload.action == "reject":
            supabase.table("testimonials").delete().eq("id", payload.review_id).execute()
            msg = "Ulasan ditolak dan dihapus dari sistem."
        else:
            return JSONResponse({"status": "error", "message": "Aksi tidak valid"}, status_code=400)
            
        return {"status": "success", "message": msg}
    except Exception as e:
        logger.error(f"Gagal moderasi ulasan {payload.review_id}: {e}")
        return JSONResponse({"status": "error", "message": "Sistem gagal memproses ulasan."}, status_code=500)

# ==============================================================================
# 4. API MANAJEMEN LOYALTY REWARDS (AJAX)
# ==============================================================================
@router.post("/api/settings/rewards/add", dependencies=[require_admin_roles("super_admin")])
async def add_reward(payload: RewardPayload):
    if not supabase: return JSONResponse({"status": "error", "message": "Database Offline"}, status_code=503)
    
    try:
        supabase.table("store_rewards").insert({
            "name": payload.name,
            "cost_in_points": payload.cost,
            "description": payload.desc,
            "is_active": True
        }).execute()
        return {"status": "success", "message": "Reward berhasil ditambahkan!"}
    except Exception as e:
        logger.error(f"Gagal tambah reward: {e}")
        return JSONResponse({"status": "error", "message": "Gagal menyimpan reward baru."}, status_code=500)

@router.delete("/api/settings/rewards/{reward_id}", dependencies=[require_admin_roles("super_admin")])
async def delete_reward(reward_id: int):
    if not supabase: return JSONResponse({"status": "error", "message": "Database Offline"}, status_code=503)
    
    try:
        # Soft delete (sembunyikan dari user)
        supabase.table("store_rewards").update({"is_active": False}).eq("id", reward_id).execute()
        return {"status": "success", "message": "Reward dinonaktifkan."}
    except Exception as e:
        logger.error(f"Gagal hapus reward {reward_id}: {e}")
        return JSONResponse({"status": "error", "message": "Gagal menghapus reward."}, status_code=500)