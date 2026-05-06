"""
====================================================================================
BABA PARFUME - CUSTOMER PROFILE ROUTER (ULTRA ENTERPRISE V12.0)
====================================================================================
Deskripsi : Menangani rendering UI Profil, kalkulasi Loyalty Points dinamis, 
            tarikan riwayat pesanan (Order History), pembaruan data pengguna,
            dan webhook penukaran poin terintegrasi dengan tabel loyalty_logs.
Developer : BABA Enterprise Core Team
====================================================================================
"""

import os
import logging
import asyncio
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone

from fastapi import APIRouter, Request, HTTPException, status, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

# Supabase Bridge
try:
    from database import supabase
except ImportError:
    supabase = None

# ==============================================================================
# ENTERPRISE LOGGING SYSTEM
# ==============================================================================
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

class ProfileLogger:
    """Manajer Log Mandiri untuk Modul Profil & Loyalty BABA"""
    def __init__(self):
        self.logger = logging.getLogger("baba.profile")
        if not self.logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter('%(asctime)s | [PROFILE_ENGINE] %(levelname)s - %(message)s')
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)
            self.logger.setLevel(logging.INFO)

    def info(self, msg: str): self.logger.info(msg)
    def warning(self, msg: str): self.logger.warning(msg)
    def error(self, msg: str): self.logger.error(msg)
    def critical(self, msg: str): self.logger.critical(msg)

logger = ProfileLogger()

templates = Jinja2Templates(directory="templates")
router = APIRouter(tags=["Customer Profile"])

# ==============================================================================
# SCHEMAS (DATA VALIDATION LAYER)
# ==============================================================================
class ProfileUpdatePayload(BaseModel):
    tele_id: int = Field(..., description="Telegram ID Pelanggan")
    phone: Optional[str] = Field("", description="Nomor HP/WhatsApp Baru")
    address: str = Field(..., description="Alamat Pengiriman Utama")

class RewardRedeemPayload(BaseModel):
    tele_id: int
    reward_id: int
    reward_name: str
    points_cost: int

def api_response(success: bool, message: str, data: Dict[str, Any] = None, status_code: int = 200):
    """Standarisasi balikan API SaaS"""
    content = {"status": "success" if success else "error", "message": message}
    if data: content.update(data)
    return JSONResponse(status_code=status_code, content=content)

# ==============================================================================
# UTILITY: DATABASE RETRY MECHANISM (ANTI-RTO)
# ==============================================================================
async def execute_with_retry(func, *args, max_retries: int = 3, delay: float = 1.0, **kwargs):
    """Sistem kebal RTO (Request Timeout) saat narik data riwayat yang berat"""
    for attempt in range(max_retries):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            if attempt == max_retries - 1:
                logger.error(f"DB Fetch Failed Permanently after {max_retries} attempts: {e}")
                raise e
            logger.warning(f"DB timeout/error. Retrying in {delay}s... (Attempt {attempt+1}/{max_retries})")
            await asyncio.sleep(delay)
            delay *= 1.5  

# ==============================================================================
# CORE ENGINE: PROFILE, LOYALTY, & ACCOUNT SETTINGS
# ==============================================================================
class ProfileService:
    """Service layer untuk mengelola komputasi profil dan transaksi non-finansial"""

    @staticmethod
    async def get_full_profile_data(tele_id: int) -> Dict[str, Any]:
        """
        Narik semua data pelanggan termasuk riwayat belanja dan rewards.
        """
        if not supabase:
            raise ValueError("Sistem Database Sedang Offline")

        # 1. Fetch Data Customer Master
        cust_res = await execute_with_retry(
            lambda: supabase.table("customers").select("*").eq("telegram_id", tele_id).single().execute()
        )
        
        if not cust_res.data:
            return {"customer": None, "stats": {}, "orders": [], "rewards": []}

        customer_data = cust_res.data
        cust_uuid = customer_data["id"]

        # 2. Fetch Order History dengan Relational Join (Orders -> Order_Items -> Products)
        orders_res = await execute_with_retry(
            lambda: supabase.table("orders")
            .select("*, items:order_items(*, product:products(*))")
            .eq("customer_id", cust_uuid)
            .order("created_at", desc=True)
            .execute()
        )
        
        raw_orders = orders_res.data or []
        
        # 3. Data Processing 
        formatted_orders = []
        total_bottles = 0
        total_valid_orders = 0
        favorite_tags_pool = {}

        for ord in raw_orders:
            order_status = ord.get("status", "Diproses")
            items_list = []
            
            for item in ord.get("items", []):
                product_data = item.get("product", {}) or {}
                qty = int(item.get("quantity", 0))
                
                items_list.append({
                    "id": item.get("id"),
                    "product_id": item.get("product_id"),
                    "qty": qty,
                    "price_at_time": float(item.get("price_at_time", 0.0)),
                    "name": product_data.get("name", "Varian BABA"),
                    "image_url": product_data.get("image_url", "https://placehold.co/100x100/f1f5f9/94a3b8?text=BABA"),
                })
                
                # Kalkulasi Botol & Tag (Hanya order valid)
                if order_status.lower() != "dibatalkan":
                    total_bottles += qty
                    
                    tags = product_data.get("tags", [])
                    if isinstance(tags, str):
                        tags = [t.strip() for t in tags.split(",") if t.strip()]
                    
                    for tag in tags:
                        clean_tag = tag.lower().strip()
                        favorite_tags_pool[clean_tag] = favorite_tags_pool.get(clean_tag, 0) + 1

            formatted_orders.append({
                "id": ord.get("id"),
                "order_number": ord.get("order_number"),
                "total_amount": float(ord.get("total_amount", 0.0)),
                "status": order_status,
                "created_at": ord.get("created_at"),
                "payment_method": ord.get("payment_method"),
                "items": items_list
            })
            
            if order_status.lower() != "dibatalkan":
                total_valid_orders += 1

        # 4. Tentukan 3 Tag Wangi Favorit
        sorted_tags = sorted(favorite_tags_pool.items(), key=lambda x: x[1], reverse=True)
        top_3_tags = [t[0].title() for t in sorted_tags[:3]]

        # Ambil poin loyalty langsung dari schema database yang baru
        loyalty_points = customer_data.get("loyalty_points", 0)

        stats = {
            "total_orders": total_valid_orders,
            "total_spent": float(customer_data.get("total_spent", 0.0)),
            "total_bottles": total_bottles,
            "loyalty_points": loyalty_points,
            "favorite_tags": top_3_tags
        }

        # 5. Fetch Dynamic Rewards dari tabel store_rewards
        rewards_res = await execute_with_retry(
            lambda: supabase.table("store_rewards").select("*").eq("is_active", True).order("cost_in_points", desc=False).execute()
        )
        active_rewards = rewards_res.data or []

        logger.info(f"✅ Profil dimuat: {customer_data.get('full_name')} | {loyalty_points} Poin | {len(active_rewards)} Rewards Aktif")

        return {
            "customer": customer_data,
            "stats": stats,
            "orders": formatted_orders,
            "rewards": active_rewards
        }

    @staticmethod
    async def update_customer_settings(tele_id: int, phone: str, address: str) -> bool:
        """Memperbarui informasi kontak dan alamat pelanggan"""
        if not supabase: return False
        try:
            await execute_with_retry(
                lambda: supabase.table("customers").update({
                    "phone": phone.strip(),
                    "default_address": address.strip(),
                    "updated_at": datetime.now(timezone.utc).isoformat()
                }).eq("telegram_id", tele_id).execute()
            )
            logger.info(f"✅ Data pelanggan ID {tele_id} berhasil diperbarui.")
            return True
        except Exception as e:
            logger.error(f"❌ Gagal update pelanggan ID {tele_id}: {e}")
            return False

# ==============================================================================
# BACKGROUND WORKERS (NOTIFICATIONS)
# ==============================================================================
async def notify_admin_reward_redeem(tele_id: int, reward_name: str, points: int):
    """Mengirim notifikasi ke admin jika ada user yang menukar poin"""
    try:
        from bot import bot as bot_instance
        admin_id = os.getenv("ADMIN_ID")
        
        if admin_id and supabase:
            # Ambil detail user buat notifikasi
            cust = supabase.table("customers").select("full_name, username, phone").eq("telegram_id", tele_id).single().execute()
            c_data = cust.data or {}
            
            msg = (
                f"🎁 <b>KLAIM REWARD BABA LOYALTY!</b>\n\n"
                f"User: <b>{c_data.get('full_name', 'Unknown')}</b> (@{c_data.get('username', '-')})\n"
                f"HP: <code>{c_data.get('phone', 'Belum diatur')}</code>\n\n"
                f"Menukarkan <b>{points} Poin</b> untuk:\n"
                f"👉 <b>{reward_name}</b>\n\n"
                f"<i>Poin telah otomatis dipotong dari akun customer. Silakan proses reward ini.</i>"
            )
            await bot_instance.send_message(chat_id=admin_id, text=msg, parse_mode="HTML")
            logger.info(f"Notifikasi redeem {reward_name} untuk {tele_id} terkirim ke Admin.")
    except Exception as e:
        logger.warning(f"Gagal mengirim notif redeem ke bot: {e}")

# ==============================================================================
# WEB ROUTE (SERVER-SIDE RENDERING JINJA2)
# ==============================================================================
@router.get("/profile", response_class=HTMLResponse)
async def customer_profile_page(request: Request, tele_id: Optional[int] = None):
    """Render Halaman Profil Pelanggan (SSR)"""
    customer_data = None
    stats_data = {"total_orders": 0, "total_bottles": 0, "loyalty_points": 0, "favorite_tags": []}
    orders_data = []
    rewards_data = []

    if tele_id and supabase:
        try:
            profile_payload = await ProfileService.get_full_profile_data(tele_id)
            customer_data = profile_payload["customer"]
            stats_data = profile_payload["stats"]
            orders_data = profile_payload["orders"]
            rewards_data = profile_payload["rewards"]
        except Exception as e:
            logger.error(f"❌ Gagal SSR Profil untuk ID {tele_id}: {e}")

    return templates.TemplateResponse("customer/profile.html", {
        "request": request,
        "customer": customer_data,
        "stats": stats_data,
        "orders": orders_data,
        "rewards": rewards_data
    })

# ==============================================================================
# API ROUTES (DYNAMIC FETCHING & UPDATES)
# ==============================================================================
@router.get("/api/v1/profile/{tele_id}")
async def api_get_profile(tele_id: int):
    """Endpoint untuk refresh data profil di background via JS"""
    if not supabase: return api_response(False, "Database Offline", status_code=503)
    try:
        data = await ProfileService.get_full_profile_data(tele_id)
        if not data["customer"]:
            return api_response(False, "Pengguna belum terdaftar. Silakan berbelanja terlebih dahulu.", status_code=404)
        return api_response(True, "Data profil berhasil dimuat", {"data": data})
    except Exception as e:
        logger.error(f"❌ [API PROFILE ERROR]: {e}")
        return api_response(False, "Terjadi kesalahan sistem saat memuat profil.", status_code=500)

@router.post("/api/v1/profile/update")
async def api_update_profile(payload: ProfileUpdatePayload):
    """Endpoint untuk menyimpan pengaturan alamat & telepon dari Profile Modal"""
    success = await ProfileService.update_customer_settings(payload.tele_id, payload.phone, payload.address)
    if success:
        return api_response(True, "Informasi pengiriman berhasil diperbarui.")
    return api_response(False, "Gagal memperbarui informasi. Coba lagi nanti.", status_code=500)

@router.post("/api/v1/profile/redeem")
async def api_redeem_reward(payload: RewardRedeemPayload, bg_tasks: BackgroundTasks):
    """
    Endpoint Webhook untuk menukar Loyalty Poin dengan keamanan Ledger Database.
    """
    if not supabase: return api_response(False, "Database Offline", status_code=503)
    
    try:
        # 1. Validasi saldo User
        cust_res = supabase.table("customers").select("id, loyalty_points").eq("telegram_id", payload.tele_id).single().execute()
        if not cust_res.data:
            return api_response(False, "User tidak terdaftar.", status_code=404)
            
        cust = cust_res.data
        current_points = cust.get("loyalty_points", 0)
        
        if current_points < payload.points_cost:
            return api_response(False, "Poin tidak mencukupi untuk klaim ini!", status_code=400)
            
        # 2. Transaksi Potong Saldo
        new_points = current_points - payload.points_cost
        supabase.table("customers").update({"loyalty_points": new_points}).eq("id", cust["id"]).execute()
        
        # 3. Catat di Audit Trail (loyalty_logs)
        supabase.table("loyalty_logs").insert({
            "customer_id": cust["id"],
            "transaction_type": "REDEEM",
            "points": -payload.points_cost,
            "description": f"Klaim Reward: {payload.reward_name}"
        }).execute()
        
        # 4. Delegasikan notifikasi ke background biar UI ngacir
        bg_tasks.add_task(notify_admin_reward_redeem, payload.tele_id, payload.reward_name, payload.points_cost)
        
        logger.info(f"✅ User {payload.tele_id} sukses redeem {payload.reward_name}. Sisa Poin: {new_points}")
        return api_response(True, f"Klaim {payload.reward_name} berhasil! Admin segera memprosesnya.")
        
    except Exception as e:
        logger.error(f"❌ [REDEEM ERROR]: {e}")
        return api_response(False, "Gagal memproses klaim poin. Coba lagi.", status_code=500)