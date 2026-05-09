"""
====================================================================================
BABA PARFUME - TELEGRAM AUTOPILOT ENGINE [ULTRA ENTERPRISE V15.0]
====================================================================================
Deskripsi : Engine Bot Telegram Utama BABA Parfume dengan Arsitektur Enterprise.
Developer : BABA Enterprise Core Team
Versi     : 15.0 (Seamless Media Transition + Middleware Protection)
Fitur Utama:
            1. Seamless Media Editor (Anti-Kedip UI/UX) untuk pergantian gambar tiap Menu.
               (Menggunakan welcome.jpg, pesanan_saya.jpg, loyalty.jpg, profile_saya.jpg, dll).
            2. Anti-Spam / Throttling Middleware Protection.
            3. WebApp Checkout Listener & Realtime Inventory Deductor (Super Lengkap).
            4. Dynamic Pagination untuk Katalog Bot (Dengan rotasi gambar katalog1, 2, 3).
            5. Advanced FSM (Profile, Address, Phone, Feedback System).
            6. Admin Dashboard dengan Realtime Analytics & Broadcast Commander.
            7. Global Exception Handling (Anti-Crash Server).
            8. Colored Terminal Logging System.
====================================================================================
"""

import os
import re
import json
import math
import asyncio
import logging
import traceback
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any, Union, Callable, Awaitable

from dotenv import load_dotenv

# Aiogram v3 Stack Utama
from aiogram import Bot, Dispatcher, F, Router, html, BaseMiddleware
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, 
    WebAppInfo, BotCommand, ReplyKeyboardRemove, TelegramObject,
    InputMediaPhoto, URLInputFile, ErrorEvent
)
from aiogram.filters import CommandStart, Command, StateFilter
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest

# ==============================================================================
# 0. INITIALIZATION, SECURITY & CONFIGURATION
# ==============================================================================
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = os.getenv("ADMIN_ID") # ID Telegram Dika (Bos Utama)
WEB_APP_URL = os.getenv("WEB_APP_URL", "").rstrip('/') # Pastikan tidak ada slash di akhir

if not BOT_TOKEN:
    raise ValueError("[FATAL_ERROR] BOT_TOKEN tidak ditemukan di environment variables (.env)!")

# ---------------------------------------------------------
# Enterprise Logging Setup (Warna-warni di Terminal VPS)
# ---------------------------------------------------------
class ColoredFormatter(logging.Formatter):
    """Formatter Log dengan warna untuk mempermudah debugging di Terminal VPS"""
    grey = "\x1b[38;20m"
    yellow = "\x1b[33;20m"
    red = "\x1b[31;20m"
    bold_red = "\x1b[31;1m"
    emerald = "\x1b[32;20m"
    reset = "\x1b[0m"
    format_str = "%(asctime)s | [BABA_BOT_ENGINE] %(levelname)s - %(message)s"

    FORMATS = {
        logging.DEBUG: grey + format_str + reset,
        logging.INFO: emerald + format_str + reset,
        logging.WARNING: yellow + format_str + reset,
        logging.ERROR: red + format_str + reset,
        logging.CRITICAL: bold_red + format_str + reset
    }

    def format(self, record):
        log_fmt = self.FORMATS.get(record.levelno)
        formatter = logging.Formatter(log_fmt, datefmt='%Y-%m-%d %H:%M:%S')
        return formatter.format(record)

logger = logging.getLogger("BabaEnterpriseBot")
logger.setLevel(logging.INFO)
ch = logging.StreamHandler()
ch.setFormatter(ColoredFormatter())
if not logger.handlers:
    logger.addHandler(ch)

# ---------------------------------------------------------
# Core Aiogram Objects
# ---------------------------------------------------------
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())
router = Router()

# ---------------------------------------------------------
# Database Bridge (Supabase)
# ---------------------------------------------------------
try:
    from database import supabase
    logger.info("✅ Supabase Bridge Connected Successfully.")
except ImportError:
    logger.critical("❌ Database module not found! Pastikan file database.py ada dan terhubung ke Supabase.")
    supabase = None

# Pagination Config untuk Katalog
ITEMS_PER_PAGE = 3

# ==============================================================================
# 1. FINITE STATE MACHINES (FSM) - STATE MANAGEMENT
# ==============================================================================
class AdminStates(StatesGroup):
    waiting_for_broadcast_message = State()

class UserProfileStates(StatesGroup):
    waiting_for_address = State()
    waiting_for_phone = State()

class FeedbackStates(StatesGroup):
    waiting_for_rating = State()
    waiting_for_complaint = State()

# ==============================================================================
# 2. MIDDLEWARES (SECURITY & ANTI-SPAM)
# ==============================================================================
class ThrottlingMiddleware(BaseMiddleware):
    """
    Middleware Anti-Spam (Throttling).
    Mencegah user iseng mengklik tombol ribuan kali per detik yang bisa membuat server down.
    Akan menahan request jika interval klik di bawah 1 detik.
    """
    def __init__(self, limit: float = 1.0):
        self.limit = limit
        self.users = {}

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        
        user_id = None
        if isinstance(event, Message):
            user_id = event.from_user.id
        elif isinstance(event, CallbackQuery):
            user_id = event.from_user.id

        if user_id:
            now = datetime.now().timestamp()
            last_time = self.users.get(user_id, 0)
            
            # Jika user request terlalu cepat
            if now - last_time < self.limit:
                if isinstance(event, CallbackQuery):
                    try:
                        await event.answer("⚠️ Santai kak, sistem sedang memuat... (Jangan klik terlalu cepat)", show_alert=False)
                    except: pass
                logger.warning(f"🛡️ Spam Blocked dari User ID: {user_id}")
                return # Block request sepenuhnya
                
            self.users[user_id] = now

        return await handler(event, data)

# Mendaftarkan Middleware ke Router Utama
router.message.middleware(ThrottlingMiddleware(limit=0.5))
router.callback_query.middleware(ThrottlingMiddleware(limit=0.8))

# ==============================================================================
# 3. SEAMLESS MEDIA ENGINE (THE KASTA DEWA TRANSITION)
# ==============================================================================
async def safe_edit_media(
    message_or_call: Union[Message, CallbackQuery], 
    image_filename: str, 
    text: str, 
    reply_markup: InlineKeyboardMarkup
):
    """
    Engine Transisi Gambar Anti-Kedip (The Real Seamless UI).
    Mengubah gambar dan teks di dalam satu pesan yang sama tanpa menghapusnya.
    Sudah dilengkapi Fallback 3 Lapis jika API Telegram menolak.
    """
    if not WEB_APP_URL:
        # Fallback Darurat 1: Jika Web URL tidak diset di .env
        logger.warning("WEB_APP_URL tidak diset. Mode fallback teks murni diaktifkan.")
        try:
            if isinstance(message_or_call, CallbackQuery):
                if message_or_call.message.caption is not None:
                    await message_or_call.message.edit_caption(caption=text, reply_markup=reply_markup)
                else:
                    await message_or_call.message.edit_text(text=text, reply_markup=reply_markup)
            else:
                await message_or_call.answer(text, reply_markup=reply_markup)
        except Exception as e: 
            logger.error(f"Fallback UI Error: {e}")
        return

    # Tarik gambar dari folder static VPS
    image_url = f"{WEB_APP_URL}/static/img/{image_filename}"
    media = InputMediaPhoto(media=URLInputFile(image_url), caption=text)
    
    if isinstance(message_or_call, CallbackQuery):
        try:
            # 1. Transisi Mulus Utama: Timpa media dan caption sekaligus
            await message_or_call.message.edit_media(media=media, reply_markup=reply_markup)
        except TelegramBadRequest as e:
            err_str = str(e).lower()
            # 2. Fallback Darurat 2: Jika pesan sebelumnya HANYA TEKS (tidak ada media)
            # Telegram menolak edit_media pada pesan teks. Solusi: Hapus pesan lama, kirim Foto baru.
            if "there is no media in the message" in err_str or "message is not modified" in err_str:
                try:
                    await message_or_call.message.delete()
                    await message_or_call.message.answer_photo(photo=URLInputFile(image_url), caption=text, reply_markup=reply_markup)
                except Exception as del_err:
                    logger.error(f"Gagal transisi (Teks -> Media): {del_err}")
            else:
                logger.error(f"Telegram API Edit Media Bad Request: {e}")
        except Exception as ex:
            logger.error(f"Unhandled Exception in safe_edit_media: {ex}")
    else:
        # 3. Mode Kirim Pesan Baru (Misal dipanggil via command /start)
        try:
            await message_or_call.answer_photo(photo=URLInputFile(image_url), caption=text, reply_markup=reply_markup)
        except Exception as e:
            logger.error(f"Gagal mengirim foto direct dari /start: {e}")
            await message_or_call.answer(text, reply_markup=reply_markup)

# ==============================================================================
# 4. DATABASE UTILITIES & ANALYTICS BRIDGES
# ==============================================================================
async def sync_user(user_id: int, username: str, full_name: str) -> str:
    """Pastikan data pelanggan sinkron dengan tabel customers di Supabase. Mengembalikan ID (UUID)."""
    if not supabase: return None
    try:
        res = supabase.table("customers").select("id, total_orders").eq("telegram_id", user_id).execute()
        payload = {
            "telegram_id": user_id,
            "username": username or "",
            "full_name": full_name or "User BABA",
            "updated_at": datetime.now().isoformat(),
            "last_interaction": datetime.now().isoformat(),
            "source": "bot"
        }
        if not res.data:
            ins = supabase.table("customers").insert(payload).execute()
            logger.info(f"🆕 Pelanggan Baru Terdaftar: {full_name} ({user_id})")
            return ins.data[0]['id'] if ins.data else None
        else:
            # Hanya update last_interaction jika data sudah ada
            supabase.table("customers").update({
                "last_interaction": datetime.now().isoformat(),
                "username": username or ""
            }).eq("telegram_id", user_id).execute()
            return res.data[0]['id']
    except Exception as e:
        logger.error(f"⚠️ User Sync Error: {e}")
        return None

async def get_user_stats(user_id: int) -> Dict:
    """Menarik metrik keuangan dan loyalty user dari database"""
    if not supabase: return {}
    try:
        res = supabase.table("customers").select("total_orders, total_spent, loyalty_points").eq("telegram_id", user_id).single().execute()
        return res.data or {}
    except: return {}

async def get_products_by_category(category_id: int, limit: int = 50) -> List[Dict]:
    """Mengambil daftar produk dari etalase database yang aktif berdasarkan kategori"""
    if not supabase: return []
    try:
        res = supabase.table("products").select("id, name, original_price, discounted_price, stock_quantity, description").eq("category_id", category_id).eq("is_active", True).limit(limit).execute()
        return res.data or []
    except Exception as e:
        logger.error(f"⚠️ Error fetching products: {e}")
        return []

async def get_admin_financial_stats() -> Dict:
    """Mengambil metrik analitik khusus untuk Dashboard Admin (Omset Hari/Bulan)"""
    if not supabase: return {"today": 0, "month": 0, "pending": 0}
    try:
        now = datetime.now()
        today_str = now.strftime('%Y-%m-%d')
        month_str = now.strftime('%Y-%m')
        
        # Total Pending Orders
        p_res = supabase.table("orders").select("id", count='exact').eq("status", "Menunggu Pembayaran").execute()
        pending = p_res.count if hasattr(p_res, 'count') else len(p_res.data or [])
        
        # Tarik data pesanan sukses bulan ini
        o_res = supabase.table("orders").select("total_amount, created_at").eq("status", "Selesai").gte("created_at", f"{month_str}-01T00:00:00Z").execute()
        
        today_revenue = 0.0
        month_revenue = 0.0
        
        for order in (o_res.data or []):
            amt = float(order.get('total_amount', 0))
            month_revenue += amt
            if today_str in order.get('created_at', ''):
                today_revenue += amt
                
        return {"today": today_revenue, "month": month_revenue, "pending": pending}
    except Exception as e:
        logger.error(f"Admin Stats Error: {e}")
        return {"today": 0, "month": 0, "pending": 0}

# ==============================================================================
# 5. KEYBOARD BUILDERS (DYNAMIC UI ENGINES)
# ==============================================================================
def get_main_kb(user_id: int) -> InlineKeyboardMarkup:
    """Merender antarmuka utama (Main Menu) dengan tombol adaptif"""
    web_shop = WebAppInfo(url=WEB_APP_URL) if WEB_APP_URL else None
    web_ai = WebAppInfo(url=f"{WEB_APP_URL}/cs") if WEB_APP_URL else None
    
    buttons = []
    
    # 1. Core Web Apps Button
    if web_shop and web_ai:
        buttons.append([InlineKeyboardButton(text="🛍️ MULAI BELANJA (MINI APP)", web_app=web_shop)])
        buttons.append([InlineKeyboardButton(text="🤖 KONSULTASI PARFUM (AI)", web_app=web_ai)])
    else:
        buttons.append([InlineKeyboardButton(text="⚠️ SISTEM SEDANG MAINTENANCE", callback_data="error_url")])
        
    # 2. Main Navigation Button Grid
    buttons.extend([
        [
            InlineKeyboardButton(text="📋 Pesanan Saya", callback_data="my_orders"),
            InlineKeyboardButton(text="💎 Loyalty Point", callback_data="my_points")
        ],
        [
            InlineKeyboardButton(text="🏬 Katalog Parfume", callback_data="bot_catalog"),
            InlineKeyboardButton(text="⚙️ Profil Saya", callback_data="my_profile")
        ],
        [
            InlineKeyboardButton(text="❓ Bantuan & FAQ", callback_data="help_center"),
            InlineKeyboardButton(text="💡 Beri Feedback", callback_data="give_feedback")
        ],
        [
            InlineKeyboardButton(text="👥 Join Grup Komunitas", url="https://t.me/parfumebaba")
        ],
    ])
    
    # 3. Mode Super Admin Tertutup
    if str(user_id) == str(ADMIN_ID):
        buttons.append([InlineKeyboardButton(text="⚡ ADMIN DASHBOARD", callback_data="admin_panel")])
        
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_back_kb(target: str = "main_menu", text: str = "🔙 Kembali") -> InlineKeyboardMarkup:
    """Keyboard universal untuk kembali ke navigasi sebelumnya"""
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=text, callback_data=target)]])

def get_catalog_pagination_kb(category_id: int, current_page: int, total_pages: int) -> InlineKeyboardMarkup:
    """Sistem navigasi Paginasi Katalog yang dinamis dengan prev/next logic"""
    buttons = []
    nav_buttons = []
    
    if current_page > 1:
        nav_buttons.append(InlineKeyboardButton(text="◀️ Prev", callback_data=f"page_{category_id}_{current_page - 1}"))
    
    nav_buttons.append(InlineKeyboardButton(text=f"📄 Hal {current_page} dari {total_pages}", callback_data="ignore_pagination"))
    
    if current_page < total_pages:
        nav_buttons.append(InlineKeyboardButton(text="Next ▶️", callback_data=f"page_{category_id}_{current_page + 1}"))
        
    buttons.append(nav_buttons)
    buttons.append([InlineKeyboardButton(text="🔙 Kembali ke Kategori", callback_data="bot_catalog")])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_profile_kb() -> InlineKeyboardMarkup:
    """Navigasi pengaturan profil pengguna"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📝 Edit Alamat", callback_data="edit_address"),
            InlineKeyboardButton(text="📱 Edit No HP", callback_data="edit_phone")
        ],
        [InlineKeyboardButton(text="🔙 Menu Utama", callback_data="main_menu")]
    ])

# ==============================================================================
# 6. CORE HANDLERS: ENTRY POINTS (/START)
# ==============================================================================
@router.message(CommandStart())
async def start_handler(message: Message, state: FSMContext):
    """Fungsi Pintu Gerbang saat pengguna baru pertama kali chat atau menekan /start"""
    await state.clear()
    await sync_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
    
    welcome_msg = (
        f"🌟 <b>BABA PARFUME ENTERPRISE</b> 🌟\n\n"
        f"Halo kak {html.bold(message.from_user.first_name)}! Selamat datang di layanan autopilot kami.\n\n"
        f"Kami menyediakan parfum kualitas <i>Import Paris</i> dengan ketahanan seharian. "
        f"Biar kami yang atur wanginya, kakak tinggal pilih dan nikmati.\n\n"
        f"👇 <b>Silakan klik menu di bawah untuk memulai:</b>"
    )
    
    # Memanggil Seamless Editor dengan spesifik welcome.jpg
    await safe_edit_media(message, "welcome.jpg", welcome_msg, get_main_kb(message.from_user.id))

@router.callback_query(F.data == "main_menu")
async def back_to_main(callback: CallbackQuery, state: FSMContext):
    """Menangani tombol Kembali ke Main Menu (Root Menu)"""
    await state.clear()
    text = "👇 <b>Silakan pilih menu utama BABA:</b>"
    # Mengembalikan gambar ke welcome.jpg secara mulus
    await safe_edit_media(callback, "welcome.jpg", text, get_main_kb(callback.from_user.id))

# ==============================================================================
# 7. USER FEATURES: LOYALTY, HISTORY, PROFILE
# ==============================================================================

@router.callback_query(F.data == "my_points")
async def show_points(callback: CallbackQuery):
    """Fitur BABA Loyalty Program (Gamification)"""
    stats = await get_user_stats(callback.from_user.id)
    
    points = stats.get("loyalty_points", 0)
    if points == 0 and stats.get("total_spent"):
        points = int(stats.get("total_spent", 0) * 10)
    
    # Penentuan Kasta Membership
    tier = "Bronze Member 🥉"
    if points > 1000: tier = "Silver Member 🥈"
    if points > 5000: tier = "Gold Member 🥇"
    if points > 10000: tier = "VIP BABA 💎"

    text = (
        f"💎 <b>BABA LOYALTY PROGRAM</b>\n\n"
        f"Status Akun: <b>{tier}</b>\n"
        f"Poin Terkumpul: <b>{points} Poin</b>\n\n"
        f"<i>Kumpulkan terus poinmu dari setiap pembelian parfum dan tukarkan dengan botol gratis atau merchandise eksklusif BABA!</i>"
    )
    # Transisi Mulus dengan spesifik loyalty.jpg
    await safe_edit_media(callback, "loyalty.jpg", text, get_back_kb())

@router.callback_query(F.data == "my_orders")
async def show_order_history(callback: CallbackQuery):
    """Menampilkan History Pesanan Pengguna dengan Rincian Nama Aroma"""
    if not supabase: 
        await callback.answer("Sistem database sedang offline.", show_alert=True)
        return
    
    cust = supabase.table("customers").select("id").eq("telegram_id", callback.from_user.id).single().execute()
    if not cust.data: 
        await callback.answer("Data pelanggan tidak ditemukan.", show_alert=True)
        return
    
    # Query 5 pesanan terakhir
    res = supabase.table("orders").select("id, order_number, status, created_at").eq("customer_id", cust.data['id']).order("created_at", desc=True).limit(5).execute()
    
    if not res.data:
        text = (
            "❌ <b>Kakak belum pernah melakukan pemesanan.</b>\n\n"
            "Yuk klik <b>Mulai Belanja</b> untuk koleksi wangi BABA pertamamu!"
        )
    else:
        text = "📋 <b>5 PESANAN TERAKHIR KAMU:</b>\n\n"
        for o in res.data:
            try:
                # Query detail produk dalam pesanan
                items_res = supabase.table("order_items").select("quantity, products(name)").eq("order_id", o['id']).execute()
                items_data = items_res.data or []
                
                detail_items = ""
                total_qty = 0
                
                for item in items_data:
                    qty = item.get('quantity', 0)
                    total_qty += qty
                    prod_info = item.get('products')
                    
                    if isinstance(prod_info, dict):
                        prod_name = prod_info.get('name', 'Parfum BABA')
                    elif isinstance(prod_info, list) and len(prod_info) > 0:
                        prod_name = prod_info[0].get('name', 'Parfum BABA')
                    else:
                        prod_name = "Parfum BABA"
                        
                    detail_items += f"   ├ {qty}x <i>{prod_name}</i>\n"
                    
                if not detail_items: detail_items = "   ├ <i>Item tidak terdata</i>\n"
            except Exception as e:
                logger.error(f"Error fetching order items: {e}")
                detail_items = "   ├ <i>Gagal memuat detail</i>\n"
                total_qty = 0

            # Konversi Tanggal Standar ISO ke Format Manusia
            try:
                dt = datetime.fromisoformat(o['created_at'].replace('Z', '+00:00'))
                date_str = dt.strftime("%d %b %Y")
            except:
                date_str = "Tgl Tidak Diketahui"

            emoji = "🕒" if o['status'] == "Menunggu Pembayaran" else "✅" if o['status'] == "Selesai" else "📦"
            
            text += (
                f"{emoji} <code>{o['order_number']}</code> ({date_str})\n"
                f"📦 <b>Total: {total_qty} Botol</b>\n"
                f"{detail_items}"
                f"   └ Status: <b>{o['status']}</b>\n\n"
            )
            
    # Transisi Mulus dengan spesifik pesanan_saya.jpg
    await safe_edit_media(callback, "pesanan_saya.jpg", text, get_back_kb())

@router.callback_query(F.data == "my_profile")
async def show_profile(callback: CallbackQuery):
    """Menampilkan Informasi Akun, Nomor HP, & Alamat"""
    if not supabase: return
    
    cust = supabase.table("customers").select("*").eq("telegram_id", callback.from_user.id).single().execute()
    data = cust.data or {}
    
    name = data.get("full_name", callback.from_user.full_name)
    phone = data.get("phone") or "<i>Belum diatur</i>"
    address = data.get("default_address") or "<i>Belum diatur</i>"
    
    text = (
        f"⚙️ <b>PROFIL SAYA</b>\n\n"
        f"👤 Nama: <b>{name}</b>\n"
        f"📱 No HP: <b>{phone}</b>\n"
        f"🏠 Alamat Pengiriman:\n{address}\n\n"
        f"<i>Pastikan data kakak sudah benar agar kurir kami tidak nyasar ya!</i>"
    )
    
    # Transisi Mulus dengan spesifik profile_saya.jpg
    await safe_edit_media(callback, "profile_saya.jpg", text, get_profile_kb())


# ==============================================================================
# 8. HELP CENTER & ADVANCED FEEDBACK SYSTEM (FSM)
# ==============================================================================
@router.callback_query(F.data == "help_center")
async def help_center(callback: CallbackQuery):
    """Pusat Bantuan Lengkap (FAQ)"""
    text = (
        "❓ <b>PUSAT BANTUAN BABA PARFUME KPS</b> 🇮🇩🇰🇭\n\n"
        "<b>1. Berapa lama wangi parfum bertahan?</b>\n"
        "Sangat awet kak! Di kulit wangi <i>soft</i>-nya bisa tahan 12-24 jam. Di pakaian minimal 8 jam++.\n\n"
        "<b>2. Apakah aman di kulit dan baju?</b>\n"
        "100% aman! BABA Parfume diracik tanpa alkohol keras, gak bikin gatal/iritasi, dan tidak meninggalkan noda kuning di baju putih.\n\n"
        "<b>3. Komposisi bahannya dari mana kak?</b>\n"
        "Dibuat dari paduan 80% bibit import asli Paris dan 20% racikan expert lokal (Sudah tersertifikasi BPOM).\n\n"
        "<b>4. Apakah ada minimal order pengiriman?</b>\n"
        "Kabar gembira! TANPA minimal order ke seluruh area KPS (Kompong Som)!\n\n"
        "<i>Ada pertanyaan lain? Jangan ragu hubungi tim CS Admin kami di bawah ini.</i>"
    )
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💬 Hubungi Admin CS", url="https://t.me/parfumebaba")],
        [InlineKeyboardButton(text="🔙 Kembali", callback_data="main_menu")]
    ])
    # Transisi Mulus dengan spesifik Faq.jpg
    await safe_edit_media(callback, "Faq.jpg", text, kb)

# --- FSM: User Feedback System ---
@router.callback_query(F.data == "give_feedback")
async def start_feedback(callback: CallbackQuery, state: FSMContext):
    """Inisiasi state untuk memberikan ulasan / keluhan ke tabel ai_feedbacks"""
    await state.set_state(FeedbackStates.waiting_for_rating)
    
    text = (
        "💡 <b>KIRIM FEEDBACK / SARAN</b>\n\n"
        "Berapa rating kepuasan kakak terhadap layanan BABA Parfume? (Skala 1-5)\n\n"
        "<i>Ketikkan angka 1 (Sangat Buruk) sampai 5 (Sangat Puas).</i>\n\n"
        "Ketik <code>Batal</code> untuk membatalkan."
    )
    # Hapus media, kembali ke chat biasa untuk proses form input teks
    try:
        await callback.message.delete()
    except: pass
    await callback.message.answer(text)

@router.message(StateFilter(FeedbackStates.waiting_for_rating))
async def process_feedback_rating(message: Message, state: FSMContext):
    if message.text.lower() == 'batal':
        await state.clear()
        await message.answer("❌ Pengisian feedback dibatalkan.", reply_markup=get_back_kb())
        return
        
    if not message.text.isdigit() or not (1 <= int(message.text) <= 5):
        await message.answer("⚠️ Harap masukkan hanya angka bulat dari 1 sampai 5 saja kak.")
        return
        
    await state.update_data(rating=int(message.text))
    await state.set_state(FeedbackStates.waiting_for_complaint)
    
    await message.answer("Terima kasih ratingnya! Sekarang tuliskan kritik, saran, atau pujian kakak di sini ya:")

@router.message(StateFilter(FeedbackStates.waiting_for_complaint))
async def process_feedback_complaint(message: Message, state: FSMContext):
    if message.text.lower() == 'batal':
        await state.clear()
        await message.answer("❌ Pengisian feedback dibatalkan.", reply_markup=get_back_kb())
        return
        
    data = await state.get_data()
    rating = data.get("rating")
    complaint = message.text
    
    if supabase:
        try:
            supabase.table("ai_feedbacks").insert({
                "telegram_id": message.from_user.id,
                "rating": rating,
                "complaint": complaint
            }).execute()
        except Exception as e:
            logger.error(f"Gagal simpan feedback ke DB: {e}")
            
    await state.clear()
    await message.answer("✅ <b>Selesai! Terima kasih banyak atas waktu dan masukannya kak!</b> Tim BABA sangat menghargainya.", reply_markup=get_back_kb())


# ==============================================================================
# 9. PROFILE EDITING FSM (STATE MACHINE)
# ==============================================================================

# --- FSM Edit Alamat ---
@router.callback_query(F.data == "edit_address")
async def start_edit_address(callback: CallbackQuery, state: FSMContext):
    await state.set_state(UserProfileStates.waiting_for_address)
    msg = (
        "🏠 <b>UBAH ALAMAT PENGIRIMAN</b>\n\n"
        "Silakan ketik alamat lengkap pengiriman kakak.\n"
        "<i>Format saran: Jalan/Nama Gedung, Patokan khusus, Area, Kota.</i>\n\n"
        "Ketik <code>Batal</code> jika tidak ingin merubah."
    )
    try: await callback.message.delete()
    except: pass
    await callback.message.answer(msg)

@router.message(StateFilter(UserProfileStates.waiting_for_address))
async def process_edit_address(message: Message, state: FSMContext):
    if message.text.lower() == 'batal':
        await state.clear()
        await message.answer("❌ Ubah alamat dibatalkan.", reply_markup=get_back_kb("my_profile", "Kembali ke Profil"))
        return

    if supabase:
        try:
            supabase.table("customers").update({"default_address": message.text}).eq("telegram_id", message.from_user.id).execute()
            await message.answer("✅ <b>Alamat berhasil diperbarui!</b>", reply_markup=get_back_kb("my_profile", "Lihat Profil"))
        except Exception as e:
            logger.error(f"Address update error: {e}")
            await message.answer("Terjadi kesalahan sistem database. Coba lagi nanti.")
    await state.clear()

# --- FSM Edit Phone ---
@router.callback_query(F.data == "edit_phone")
async def start_edit_phone(callback: CallbackQuery, state: FSMContext):
    await state.set_state(UserProfileStates.waiting_for_phone)
    msg = (
        "📱 <b>UBAH NOMOR HANDPHONE / WA</b>\n\n"
        "Silakan masukkan nomor telepon kakak yang aktif.\n"
        "<i>Contoh: 08123456789 atau +855987654</i>\n\n"
        "Ketik <code>Batal</code> jika batal mengubah."
    )
    try: await callback.message.delete()
    except: pass
    await callback.message.answer(msg)

@router.message(StateFilter(UserProfileStates.waiting_for_phone))
async def process_edit_phone(message: Message, state: FSMContext):
    if message.text.lower() == 'batal':
        await state.clear()
        await message.answer("❌ Ubah nomor dibatalkan.", reply_markup=get_back_kb("my_profile", "Kembali ke Profil"))
        return

    # Validasi regex nomor telepon dasar
    phone = message.text.replace(" ", "").replace("-", "")
    if len(phone) < 8 or not phone.replace("+", "").isdigit():
        await message.answer("⚠️ Format nomor tidak valid. Masukkan hanya angka (awalan + diperbolehkan). Coba lagi:")
        return

    if supabase:
        try:
            supabase.table("customers").update({"phone": phone}).eq("telegram_id", message.from_user.id).execute()
            await message.answer("✅ <b>Nomor telepon berhasil diperbarui!</b>", reply_markup=get_back_kb("my_profile", "Lihat Profil"))
        except Exception as e:
            logger.error(f"Phone update error: {e}")
            await message.answer("Terjadi kesalahan sistem. Coba lagi nanti.")
    await state.clear()

# ==============================================================================
# 10. DYNAMIC BOT CATALOG & PAGINATION (THE ROTATING MEDIA)
# ==============================================================================
@router.callback_query(F.data == "bot_catalog")
async def bot_catalog_root(callback: CallbackQuery):
    """Menampilkan halaman utama Katalog Produk (Kategori)"""
    if not supabase: 
        await callback.answer("Database sedang maintenance.", show_alert=True)
        return
        
    res = supabase.table("categories").select("*").execute()
    if not res.data:
        await callback.answer("Belum ada kategori tersedia di database.", show_alert=True)
        return
        
    kb = []
    for cat in res.data:
        kb.append([InlineKeyboardButton(text=f"📂 {cat['name']}", callback_data=f"cat_{cat['id']}_1")])
        
    kb.append([InlineKeyboardButton(text="🔙 Kembali", callback_data="main_menu")])
    
    text = (
        "🗂️ <b>ETALASE BABA PARFUME:</b>\n\n"
        "Kami membagi aroma berdasarkan kategori. Silakan pilih kategori aroma yang paling merepresentasikan dirimu kak."
    )
    # Gunakan katalog1.jpg sebagai sampul kategori utama
    await safe_edit_media(callback, "katalog1.jpg", text, InlineKeyboardMarkup(inline_keyboard=kb))

@router.callback_query(F.data.startswith("cat_") | F.data.startswith("page_"))
async def show_category_products(callback: CallbackQuery):
    """Handler Paginasi Dinamis Produk dengan Sistem Rotasi Gambar (katalog1, 2, 3)"""
    parts = callback.data.split("_")
    category_id = int(parts[1])
    current_page = int(parts[2])
    
    products = await get_products_by_category(category_id)
    if not products:
        await callback.answer("Maaf kak, produk di kategori ini sedang di-restock.", show_alert=True)
        return
        
    total_products = len(products)
    total_pages = math.ceil(total_products / ITEMS_PER_PAGE)
    
    if current_page > total_pages: current_page = total_pages
    if current_page < 1: current_page = 1
    
    start_idx = (current_page - 1) * ITEMS_PER_PAGE
    end_idx = start_idx + ITEMS_PER_PAGE
    page_items = products[start_idx:end_idx]
    
    text = f"📦 <b>KATALOG PRODUK BABA (Halaman {current_page} dari {total_pages})</b>\n\n"
    
    for p in page_items:
        stok_status = "🟢 Tersedia" if p['stock_quantity'] > 0 else "🔴 Habis"
        desc = p['description'][:1000] + "..." if p['description'] and len(p['description']) > 1000 else p.get('description', 'Aroma memikat yang tak terlupakan.')
        
        # Sembunyikan harga agar User tertarik membuka WebApp
        text += (
            f"🔹 <b>{p['name']}</b>\n"
            f"   ├ <i>{desc}</i>\n"
            f"   └ Stok Saat Ini: <b>{stok_status}</b>\n\n"
        )
        
    text += "<i>Tertarik? Klik tombol 'Mulai Belanja' di Menu Utama untuk melihat galeri foto dan melakukan pesanan!</i>"
    
    kb = get_catalog_pagination_kb(category_id, current_page, total_pages)
    
    # 🔥 DYNAMIC IMAGE ROTATION: Agar transisi menu tidak membosankan, 
    # putar gambar katalog1.jpg, katalog2.jpg, katalog3.jpg berdasarkan ID kategori dan halaman.
    img_index = ((category_id + current_page) % 3) + 1
    dynamic_katalog_img = f"katalog{img_index}.jpg"
    
    await safe_edit_media(callback, dynamic_katalog_img, text, kb)

@router.callback_query(F.data == "ignore_pagination")
async def ignore_page_click(callback: CallbackQuery):
    """Mencegah tombol indikator halaman memicu error jika diklik"""
    await callback.answer("Halaman sedang aktif 😉", show_alert=False)

# ==============================================================================
# 11. WEB APP LISTENER (FINANCE, INVENTORY & CHECKOUT ENGINE)
# ==============================================================================
@router.message(F.web_app_data)
async def handle_checkout_data(message: Message):
    """Menerima Struk JSON dari WebApp JS, Potong Stok Gudang, dan Kirim Invoice ke User"""
    try:
        raw_data = json.loads(message.web_app_data.data)
        if raw_data.get("action") != "checkout": return

        cust_info = raw_data.get("customer", {})
        items = raw_data.get("items", [])
        total_usd = float(raw_data.get("total_amount", 0))
        pay_method = raw_data.get("payment_method", "COD")
        
        # Generator Invoice ID (Format: BABA-YYMMDD-XXXX)
        order_no = f"BABA-{datetime.now().strftime('%y%m%d')}-{str(message.from_user.id)[-4:]}"
        total_qty = 0 

        if supabase:
            # 1. Update profil alamat & HP terakhir pelanggan secara otomatis
            supabase.table("customers").update({
                "default_address": cust_info.get("address", ""),
                "full_name": cust_info.get('full_name', message.from_user.full_name),
                "phone": cust_info.get("phone", "")
            }).eq("telegram_id", message.from_user.id).execute()
            
            cust_db = supabase.table("customers").select("id").eq("telegram_id", message.from_user.id).single().execute()
            cust_uuid = cust_db.data.get("id")

            # 2. Buat Order Baru (USD tersimpan di database untuk keamanan kalkulasi, tapi user tidak melihat)
            order_res = supabase.table("orders").insert({
                "order_number": order_no,
                "customer_id": cust_uuid,
                "shipping_address": cust_info.get("address", ""),
                "total_amount": total_usd, 
                "status": "Menunggu Pembayaran",
                "payment_method": pay_method,
                "order_source": "Telegram Mini App"
            }).execute()
            
            order_uuid = order_res.data[0].get("id")

            # 3. Masukkan rincian keranjang ke DB dan Potong Fisik Gudang (Inventory Deductor)
            items_text = ""
            for item in items:
                qty = int(item['qty'])
                total_qty += qty
                items_text += f"✔️ {item['name']} — <b>{qty} Botol</b>\n"
                
                supabase.table("order_items").insert({
                    "order_id": order_uuid,
                    "product_id": item['id'],
                    "quantity": qty,
                    "price_at_time": item['price']
                }).execute()
                
                p_res = supabase.table("products").select("stock_quantity").eq("id", item['id']).single().execute()
                if p_res.data:
                    current_stock = int(p_res.data['stock_quantity'])
                    new_stok = max(0, current_stock - qty) # Anti minus system
                    supabase.table("products").update({"stock_quantity": new_stok}).eq("id", item['id']).execute()

                    # Audit Trail untuk Stock Movements (Sangat penting buat Akuntan)
                    supabase.table("stock_logs").insert({
                        "product_id": item['id'],
                        "action": "OUT",
                        "adjustment_amount": -qty,
                        "final_stock": new_stok,
                        "reason": f"Sistem memproses Sale Order {order_no}",
                        "reference_type": "ORDER",
                        "reference_id": order_uuid
                    }).execute()

        # ---------------------------------------------------------
        # PUSH STRUK KE USER (HARGA DISEMBUNYIKAN UNTUK NYAMAN DI MATA)
        # ---------------------------------------------------------
        struk = (
            f"🎉 <b>YAY! PESANAN BERHASIL MASUK SISTEM!</b> 🎉\n\n"
            f"Terima kasih luar biasa kak <b>{cust_info.get('full_name')}</b> sudah mempercayakan BABA Parfume!\n\n"
            f"🧾 <b>Nomor Resi / Invoice:</b> <code>{order_no}</code>\n\n"
            f"📦 <b>Rincian Barang yang Diangkut:</b>\n"
            f"{items_text}\n"
            f"Total Pembelian: <b>{total_qty} Botol Eksklusif</b>\n"
            f"Sistem Pembayaran: <b>{pay_method}</b>\n\n"
            f"<i>Silakan duduk manis kak, tim Customer Service khusus BABA akan segera memproses barang kakak dan menghubungi secepat kilat! 🚀🫶</i>"
        )
        
        # Eksekusi Animasi Kirim Struk
        try:
            temp_msg = await message.reply("Sedang meneruskan rincian ke gudang logistik... 🚛")
            await asyncio.sleep(1.5)
            await temp_msg.delete()
            
            # Kirim struk dengan foto tematik pesanan_saya.jpg
            if WEB_APP_URL:
                await message.answer_photo(photo=URLInputFile(f"{WEB_APP_URL}/static/img/pesanan_saya.jpg"), caption=struk, reply_markup=get_main_kb(message.from_user.id))
            else:
                await message.reply(struk, reply_markup=get_main_kb(message.from_user.id))
        except Exception as e:
            logger.error(f"Error mengirim Struk UI: {e}")
            await message.reply(struk)

        # ---------------------------------------------------------
        # PUSH NOTIFICATION ALERT KHUSUS ADMIN DIKA (TRANSPARAN FULL USD)
        # ---------------------------------------------------------
        if ADMIN_ID:
            alert = (
                f"🚨 <b>INCOMING SALE ALERT BOS!</b> 🚨\n\n"
                f"ID Sistem: <code>{order_no}</code>\n"
                f"Customer Info: {cust_info.get('full_name')} (@{message.from_user.username})\n"
                f"Muatan Keluar: {total_qty} Item\n"
                f"💵 <b>NILAI DEAL (ESTIMASI USD): ${total_usd:,.2f}</b>\n"
                f"Tipe Bayar: {pay_method}\n\n"
                f"👉 <i>Segera buka Web Dashboard Enterprise BABA buat eksekusi konversi kurs IDR dan amankan cuan ke rekening!</i>"
            )
            try:
                await bot.send_message(chat_id=ADMIN_ID, text=alert)
            except: pass

    except Exception as e:
        logger.critical(f"❌ MiniApp Critical Checkout Error: {e}\n{traceback.format_exc()}")
        await message.reply("⚠️ Maaf kak, terjadi kesalahan di sistem gudang saat kalkulasi. Pesanan lu mungkin nyangkut, silakan screenshot layar ini dan hubungi CS manual.")

# ==============================================================================
# 12. ADMIN PANEL & COMMAND CENTER (STRATEGIC LEVERAGE)
# ==============================================================================
@router.callback_query(F.data == "admin_panel")
async def admin_main(callback: CallbackQuery):
    """Dashboard Admin Super Tertutup - Mengatur Keseluruhan Sistem Bot"""
    if str(callback.from_user.id) != str(ADMIN_ID): 
        await callback.answer("Akses Ditolak. Area Terlarang Khusus Direksi.", show_alert=True)
        return
    
    # Tarik Advanced Analytics Data
    stats = await get_admin_financial_stats()
    
    text = (
        f"⚡ <b>BABA EXECUTIVE COMMAND CENTER</b> ⚡\n\n"
        f"Status Sistem Engine: 🟢 <b>OPTIMAL & RUNNING</b>\n"
        f"Waktu Server (WIB): {datetime.now(timezone(timedelta(hours=7))).strftime('%d %b %Y %H:%M')}\n\n"
        f"💰 <b>FINANCIAL METRICS (USD)</b>\n"
        f"Omset Sukses Hari Ini: <b>${stats['today']:,.2f}</b>\n"
        f"Omset Sukses Bulan Ini: <b>${stats['month']:,.2f}</b>\n\n"
        f"🚨 <b>OPERATIONAL ALERTS</b>\n"
        f"Pesanan Belum Tuntas: <b>{stats['pending']} Order Pending</b>\n\n"
        f"<i>Apa instruksi eksekusi selanjutnya hari ini, Bos?</i>"
    )
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Broadcast Promo Massal", callback_data="admin_broadcast_init")],
        [InlineKeyboardButton(text="📊 Radar Stok Menipis", callback_data="admin_low_stock")],
        [InlineKeyboardButton(text="🔙 Balik ke Menu User", callback_data="main_menu")]
    ])
    
    # Transisi Mulus pakai Logo Utama Perusahaan untuk Admin Panel
    await safe_edit_media(callback, "Logo_BABA.png", text, kb)

@router.callback_query(F.data == "admin_low_stock")
async def admin_low_stock(callback: CallbackQuery):
    """Peringatan Dini Stok Barang untuk Restock Cepat"""
    if str(callback.from_user.id) != str(ADMIN_ID): return
    if not supabase: return
    
    res = supabase.table("products").select("name, stock_quantity").lt("stock_quantity", 10).order("stock_quantity").execute()
    
    if not res.data:
        text = "✅ Radar Aman Bos. Gak ada satupun produk yang nyentuh sisa di bawah 10 botol."
    else:
        text = "📉 <b>WARNING: ZONA KRITIS STOK (< 10 Botol)</b>\n\n"
        for p in res.data:
            text += f"⚠️ {p['name']} — Sisa di Gudang: <b>{p['stock_quantity']}</b>\n"
        text += "\n<i>Tindakan Disarankan: Segera kontak supplier buat restock biar perputaran uang di web app ga mandek!</i>"
        
    await safe_edit_media(callback, "Logo_BABA.png", text, get_back_kb("admin_panel", "Balik ke Dashboard Admin"))

# ==============================================================================
# 13. ADMIN BROADCAST COMMANDER (FSM)
# ==============================================================================
@router.callback_query(F.data == "admin_broadcast_init")
async def start_broadcast(callback: CallbackQuery, state: FSMContext):
    """Sistem Quick Blast Promo via Telegram (Emergency Manual Blast)"""
    if str(callback.from_user.id) != str(ADMIN_ID): return
    
    await state.set_state(AdminStates.waiting_for_broadcast_message)
    try: await callback.message.delete()
    except: pass
    
    await callback.message.answer(
        "📢 <b>MODE QUICK BROADCAST AKTIF</b>\n\n"
        "Silakan kirim pesan ATAU GAMBAR + TEKS yang ingin di-blast ke SEMUA pengguna bot ini sekarang juga.\n"
        "Sistem mendukung penuh Format HTML murni (<b>Bold</b>, <i>Italic</i>, <a>Link</a>).\n\n"
        "Ketik <code>Batal</code> untuk menggagalkan peluncuran rudal."
    )

@router.message(StateFilter(AdminStates.waiting_for_broadcast_message))
async def process_broadcast(message: Message, state: FSMContext):
    if message.text and message.text.lower() == 'batal':
        await state.clear()
        await message.answer("✅ Peluncuran Broadcast Dibatalkan, Bos.")
        return

    if not supabase:
        await message.answer("Database sedang gangguan komunikasi, gagal narik data populasi user.")
        await state.clear()
        return

    # Kumpulkan seluruh ID Pelanggan
    res = supabase.table("customers").select("telegram_id").execute()
    users = res.data or []
    
    if not users:
        await message.answer("Gudang data kosong, belum ada user satupun untuk disasar.")
        await state.clear()
        return

    progress_msg = await message.answer(f"🚀 Menyalakan mesin roket blast ke {len(users)} pengguna...")
    
    success = 0
    failed = 0
    
    for u in users:
        tid = u.get("telegram_id")
        if not tid: continue
        
        try:
            # Gunakan copy_message agar gambar/dokumen/emoji dari admin ikut ter-broadcast bulat-bulat
            await bot.copy_message(chat_id=tid, from_chat_id=message.chat.id, message_id=message.message_id)
            success += 1
            await asyncio.sleep(0.05) # Jaga Rate Limit ketat API Telegram (20 messages per second)
        except Exception as e:
            logger.warning(f"Gagal broadcast ke {tid}: {e}")
            failed += 1
            
    try: await progress_msg.delete()
    except: pass
    
    await message.answer(
        f"📊 <b>LAPORAN QUICK BROADCAST SELESAI DIEKSEKUSI</b>\n\n"
        f"✅ Tembus Masuk: {success} User\n"
        f"❌ Gagal/Akun Mati: {failed} User\n\n"
        f"<i>Mesin engagement sukses diledakkan. Growth engine running smooth.</i>"
    )
    await state.clear()

# ==============================================================================
# 14. CATCH-ALL & GLOBAL ERROR HANDLERS (THE SHIELDS)
# ==============================================================================
@router.message(F.text & ~F.text.startswith('/'))
async def catch_all_messages(message: Message, state: FSMContext):
    """
    Penangkap jaring pengaman untuk semua teks biasa yang diketik user sembarangan.
    Hanya aktif jika user TIDAK sedang mengisi form apa-apa (state is None).
    """
    current_state = await state.get_state()
    if current_state is None:
        response = (
            "jangan cape cape ketik kak😁 langsung pencet /start aja dan klik klik pilihan di menu bawah ya🥰\n\n"
            "enjoy selalu sama wangi parfumnya^^ salam wangi🫶"
        )
        await message.reply(response)

@dp.errors()
async def global_error_handler(event: ErrorEvent):
    """
    GLOBAL EXCEPTION HANDLER:
    Mencegah Bot mati mendadak jika Telegram API mengembalikan error yang tidak ter-catch di fungsi spesifik.
    """
    logger.critical(f"⚠️ [CRITICAL GLOBAL EXCEPTION CAUGHT] ⚠️\nEvent Update: {event.update}\nException Data: {event.exception}")
    
    # Coba kirim alert darurat ke bos Dika kalau aplikasi sekarat
    try:
        if ADMIN_ID:
            err_msg = f"❌ <b>CRITICAL SYSTEM EXCEPTION IN BOT API</b> ❌\n<pre>{str(event.exception)[:500]}</pre>"
            await bot.send_message(chat_id=ADMIN_ID, text=err_msg)
    except: pass
    
    return True

# ==============================================================================
# 15. BACKGROUND TASKS (SCHEDULER & PERIODIC HEALTH CHECKS)
# ==============================================================================
async def scheduler_pending_orders():
    """Service pemantau performa yang berjalan abadi di background VPS"""
    await asyncio.sleep(60) # Beri nafas sistem saat baru menyala
    while True:
        try:
            if supabase and ADMIN_ID:
                res = supabase.table("orders").select("order_number").eq("status", "Menunggu Pembayaran").execute()
                orders = res.data or []
                
                if len(orders) >= 3:
                    msg = (
                        f"⚠️ <b>SYSTEM ALERT: TRAFFIC BOTTLENECK DETECTED!</b> ⚠️\n\n"
                        f"Bos, pergerakan melambat! Ada <b>{len(orders)}</b> pesanan pelanggan numpuk di database yang belum divalidasi pembayarannya.\n"
                        f"Segera buka Web Admin Dashboard, masuk ke menu Mutasi/Order, dan eksekusi secepatnya biar cashflow muter."
                    )
                    await bot.send_message(chat_id=ADMIN_ID, text=msg)
        except Exception as e:
            logger.error(f"Background Scheduler Exception: {e}")
            
        await asyncio.sleep(7200) # Cek kondisi kesehatan pesanan setiap 2 Jam

# ==============================================================================
# 16. MAIN ENTRY POINT (BOOTSTRAPPING & LIFECYCLE MANAGEMENT)
# ==============================================================================
async def main():
    """Fungsi Pemicu Utama (Ignition) untuk me-render bot dan memanaskan semua logic engine"""
    
    # 1. Setup UI Command Bar List (Untuk mempermudah pelanggan via tombol pojok Telegram)
    await bot.set_my_commands([
        BotCommand(command="start", description="🔄 Menu Utama & Beranda"),
        BotCommand(command="help", description="❓ Panduan Pemakaian & FAQ"),
    ])
    
    # 2. Registrasi Seluruh Router dan Komponen Handler
    dp.include_router(router)
    
    # 3. Menghidupkan Service Pekerja Keras di Balik Layar
    asyncio.create_task(scheduler_pending_orders())
    
    logger.info("🚀=============================================================🚀")
    logger.info("🔥 BABA ENTERPRISE TELEGRAM ENGINE [V15.0 SEAMLESS] IS LIVE! 🔥")
    logger.info("🚀=============================================================🚀")
    
    # 4. Protokol Pembersihan Jaringan sebelum Start
    # (Membersihkan pesan yang masuk saat VPS kita sedang restart/offline)
    await bot.delete_webhook(drop_pending_updates=True)
    
    # 5. Ignite the Polling Engine!
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        # Menjalankan Event Loop Asynchronous
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("👋 Sinyal penutupan diterima. Mematikan Engine BABA Enterprise dengan aman...")
        logger.info("Sistem offline. See you later, Builder.")
