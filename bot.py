import os
import json
import logging
import asyncio
import math
from datetime import datetime
from typing import Optional, List, Dict, Any

from dotenv import load_dotenv

# Aiogram v3 Stack
from aiogram import Bot, Dispatcher, F, Router, html
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, 
    WebAppInfo, BotCommand, ReplyKeyboardRemove
)
from aiogram.filters import CommandStart, Command, StateFilter
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# ==============================================================================
# 0. INITIALIZATION, SECURITY & CONFIGURATION
# ==============================================================================
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = os.getenv("ADMIN_ID") # ID Telegram Dika (Bos Utama)
WEB_APP_URL = os.getenv("WEB_APP_URL")

if not BOT_TOKEN:
    raise ValueError("[FATAL] BOT_TOKEN missing in .env!")

# Logging Setup - Professional Grade
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - [%(levelname)s] - %(message)s'
)
logger = logging.getLogger("BabaEnterpriseBot")

# Core Aiogram Objects
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())
router = Router()

# Database Bridge (Supabase)
try:
    from database import supabase
except ImportError:
    logger.error("❌ Database module not found! Pastikan file database.py ada dan terhubung ke Supabase.")
    supabase = None

# Pagination Config
ITEMS_PER_PAGE = 3

# ==============================================================================
# 1. FSM STATES (FINITE STATE MACHINES)
# ==============================================================================
class AdminStates(StatesGroup):
    waiting_for_broadcast_message = State()

class UserProfileStates(StatesGroup):
    waiting_for_address = State()
    waiting_for_phone = State()

# ==============================================================================
# 2. DATABASE UTILITIES & BRIDGES (ADVANCED LOGIC)
# ==============================================================================
async def sync_user(user_id: int, username: str, full_name: str):
    """Pastikan data pelanggan sinkron dengan tabel customers di Supabase"""
    if not supabase: return
    try:
        res = supabase.table("customers").select("id, total_orders").eq("telegram_id", user_id).execute()
        payload = {
            "telegram_id": user_id,
            "username": username or "",
            "full_name": full_name or "User BABA",
            "updated_at": datetime.now().isoformat()
        }
        if not res.data:
            supabase.table("customers").insert(payload).execute()
            logger.info(f"🆕 New Customer Synced: {full_name} ({user_id})")
        else:
            supabase.table("customers").update(payload).eq("telegram_id", user_id).execute()
    except Exception as e:
        logger.error(f"⚠️ User Sync Error: {e}")

async def get_user_stats(user_id: int) -> Dict:
    """Tarik data history belanja dan poin loyalty dari DB"""
    if not supabase: return {}
    try:
        res = supabase.table("customers").select("total_orders, total_spent, loyalty_points").eq("telegram_id", user_id).single().execute()
        return res.data or {}
    except: return {}

async def get_order_qty(order_uuid: str) -> int:
    """Menghitung total kuantitas botol/item dari sebuah order (Mencegah tampilan harga)"""
    if not supabase: return 0
    try:
        res = supabase.table("order_items").select("quantity").eq("order_id", order_uuid).execute()
        if res.data:
            return sum(int(item['quantity']) for item in res.data)
        return 0
    except Exception as e:
        logger.error(f"⚠️ Error get order qty: {e}")
        return 0

async def get_products_by_category(category_id: int, limit: int = 50) -> List[Dict]:
    """Mengambil daftar produk berdasarkan kategori untuk bot catalog"""
    if not supabase: return []
    try:
        res = supabase.table("products").select("id, name, original_price, stock_quantity, description").eq("category_id", category_id).eq("is_active", True).limit(limit).execute()
        return res.data or []
    except Exception as e:
        logger.error(f"⚠️ Error fetching products: {e}")
        return []

# ==============================================================================
# 3. KEYBOARD BUILDERS (DYNAMIC UI ENGINES)
# ==============================================================================
def get_main_kb(user_id: int) -> InlineKeyboardMarkup:
    """Keyboard Utama Bot - Dynamic berdasarkan User ID"""
    web_shop = WebAppInfo(url=WEB_APP_URL) if WEB_APP_URL else None
    web_ai = WebAppInfo(url=f"{WEB_APP_URL}/cs") if WEB_APP_URL else None
    
    buttons = []
    
    # Safely add Web App buttons if URL exists
    if web_shop and web_ai:
        buttons.append([InlineKeyboardButton(text="🛍️ MULAI BELANJA (MINI APP)", web_app=web_shop)])
        buttons.append([InlineKeyboardButton(text="🤖 KONSULTASI PARFUM (AI)", web_app=web_ai)])
    else:
        buttons.append([InlineKeyboardButton(text="🛍️ MULAI BELANJA (URL MISING)", callback_data="error_url")])
        
    buttons.extend([
        [
            InlineKeyboardButton(text="📋 Pesanan Saya", callback_data="my_orders"),
            InlineKeyboardButton(text="💎 Loyalty Point", callback_data="my_points")
        ],
        [
            InlineKeyboardButton(text="🏬 Katalog Bot", callback_data="bot_catalog"),
            InlineKeyboardButton(text="⚙️ Profil Saya", callback_data="my_profile")
        ],
        [
            InlineKeyboardButton(text="❓ Bantuan & FAQ", callback_data="help_center")
        ],
        [
            # MENGARAH KE GRUP KOMUNITAS (Ganti link-nya sama link grup Telegram lu bre!)
            InlineKeyboardButton(text="👥 Join Grup Komunitas", url="https://t.me/parfumebaba")
        ],
    ])
    
    # Tombol Khusus Admin (Dika)
    if str(user_id) == str(ADMIN_ID):
        buttons.append([InlineKeyboardButton(text="⚡ ADMIN DASHBOARD", callback_data="admin_panel")])
        
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_back_kb(target: str = "main_menu", text: str = "🔙 Kembali") -> InlineKeyboardMarkup:
    """Keyboard universal untuk kembali ke menu tertentu"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=text, callback_data=target)]
    ])

def get_catalog_pagination_kb(category_id: int, current_page: int, total_pages: int) -> InlineKeyboardMarkup:
    """Sistem Paginasi Super Canggih buat lihat katalog produk di dalam bot"""
    buttons = []
    nav_buttons = []
    
    if current_page > 1:
        nav_buttons.append(InlineKeyboardButton(text="◀️ Prev", callback_data=f"page_{category_id}_{current_page - 1}"))
    
    nav_buttons.append(InlineKeyboardButton(text=f"📄 {current_page}/{total_pages}", callback_data="ignore_pagination"))
    
    if current_page < total_pages:
        nav_buttons.append(InlineKeyboardButton(text="Next ▶️", callback_data=f"page_{category_id}_{current_page + 1}"))
        
    buttons.append(nav_buttons)
    buttons.append([InlineKeyboardButton(text="🔙 Kembali ke Kategori", callback_data="bot_catalog")])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_profile_kb() -> InlineKeyboardMarkup:
    """Keyboard untuk manajemen profil user"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 Update Alamat", callback_data="edit_address")],
        [InlineKeyboardButton(text="🔙 Menu Utama", callback_data="main_menu")]
    ])

# ==============================================================================
# 4. CORE HANDLERS: ENTRY POINTS
# ==============================================================================
@router.message(CommandStart())
async def start_handler(message: Message, state: FSMContext):
    """Pintu masuk utama bot. Membersihkan state dan menyapa user."""
    await state.clear()
    await sync_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
    
    welcome_msg = (
        f"🌟 <b>BABA PARFUME ENTERPRISE</b> 🌟\n\n"
        f"Halo kak {html.bold(message.from_user.first_name)}! Selamat datang di layanan autopilot kami.\n\n"
        f"Kami menyediakan parfum kualitas <i>Import Paris</i> dengan ketahanan seharian. "
        f"Biar kami yang atur wanginya, kakak tinggal pilih dan nikmati.\n\n"
        f"👇 <b>Silakan klik menu di bawah untuk memulai:</b>"
    )
    
    try:
        # Coba kirim dengan logo jika tersedia di URL static
        if WEB_APP_URL:
            await message.answer_photo(
                photo=f"{WEB_APP_URL}/static/img/Logo_BABA.png",
                caption=welcome_msg,
                reply_markup=get_main_kb(message.from_user.id)
            )
        else:
            await message.answer(welcome_msg, reply_markup=get_main_kb(message.from_user.id))
    except Exception as e:
        logger.warning(f"Failed to send image, falling back to text: {e}")
        await message.answer(welcome_msg, reply_markup=get_main_kb(message.from_user.id))

@router.callback_query(F.data == "main_menu")
async def back_to_main(callback: CallbackQuery, state: FSMContext):
    """Fungsi kembali ke menu utama dari cabang manapun"""
    await state.clear()
    text = "👇 <b>Silakan pilih menu utama BABA:</b>"
    
    # Cek apakah message punya caption (artinya dia foto) atau text biasa
    try:
        if callback.message.caption is not None:
            await callback.message.edit_caption(caption=text, reply_markup=get_main_kb(callback.from_user.id))
        else:
            await callback.message.edit_text(text=text, reply_markup=get_main_kb(callback.from_user.id))
    except Exception as e:
        logger.error(f"Error returning to main menu: {e}")
        # Fallback kirim pesan baru jika edit gagal (misal message terlalu usang)
        await callback.message.answer(text, reply_markup=get_main_kb(callback.from_user.id))
        await callback.message.delete()

# ==============================================================================
# 5. USER FEATURES: HISTORY, LOYALTY, PROFILE, HELP
# ==============================================================================
@router.callback_query(F.data == "my_points")
async def show_points(callback: CallbackQuery):
    """Menampilkan sistem poin loyalty tanpa harus menunjukkan detail dolar/rupiah yang mengintimidasi"""
    stats = await get_user_stats(callback.from_user.id)
    
    # Ambil poin langsung dari DB jika ada, jika tidak kalkulasi manual
    points = stats.get("loyalty_points", 0)
    if points == 0 and stats.get("total_spent"):
        # Fallback perhitungan lama
        points = int(stats.get("total_spent", 0) * 10)
    
    # Tentukan Tier (Gamification)
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
    
    if callback.message.caption is not None:
        await callback.message.edit_caption(caption=text, reply_markup=get_back_kb())
    else:
        await callback.message.edit_text(text=text, reply_markup=get_back_kb())

@router.callback_query(F.data == "my_orders")
async def show_order_history(callback: CallbackQuery):
    """Menampilkan history pesanan dengan DETAIL NAMA AROMA, tanpa harga"""
    if not supabase: 
        await callback.answer("Sistem database sedang offline.", show_alert=True)
        return
    
    # Ambil Customer UUID
    cust = supabase.table("customers").select("id").eq("telegram_id", callback.from_user.id).single().execute()
    if not cust.data: 
        await callback.answer("Data pelanggan tidak ditemukan.", show_alert=True)
        return
    
    # Ambil 5 pesanan terakhir
    res = supabase.table("orders").select("id, order_number, status, created_at").eq("customer_id", cust.data['id']).order("created_at", desc=True).limit(5).execute()
    
    if not res.data:
        text = (
            "❌ <b>Kakak belum pernah melakukan pemesanan.</b>\n"
            "Yuk klik <b>Mulai Belanja</b> untuk koleksi wangi BABA pertamamu!"
        )
    else:
        text = "📋 <b>5 PESANAN TERAKHIR KAMU:</b>\n\n"
        for o in res.data:
            # Ambil detail item dan join dengan nama produk dari tabel products
            try:
                # Query relasional Supabase untuk ngambil nama produk sekaligus
                items_res = supabase.table("order_items").select("quantity, products(name)").eq("order_id", o['id']).execute()
                items_data = items_res.data or []
                
                detail_items = ""
                total_qty = 0
                
                for item in items_data:
                    qty = item.get('quantity', 0)
                    total_qty += qty
                    
                    # Parsing relasi Supabase (handle dict/list dari inner join)
                    prod_info = item.get('products')
                    if isinstance(prod_info, dict):
                        prod_name = prod_info.get('name', 'Parfum BABA')
                    elif isinstance(prod_info, list) and len(prod_info) > 0:
                        prod_name = prod_info[0].get('name', 'Parfum BABA')
                    else:
                        prod_name = "Parfum BABA"
                        
                    detail_items += f"   ├ {qty}x <i>{prod_name}</i>\n"
                    
                if not detail_items:
                    detail_items = "   ├ <i>Item tidak terdata</i>\n"
                    
            except Exception as e:
                logger.error(f"Error fetching order items details: {e}")
                detail_items = "   ├ <i>Gagal memuat detail item</i>\n"
                total_qty = 0

            # Format Tanggal
            try:
                dt = datetime.fromisoformat(o['created_at'].replace('Z', '+00:00'))
                date_str = dt.strftime("%d %b %Y")
            except:
                date_str = "Tgl Tidak Diketahui"

            emoji = "🕒" if o['status'] == "Menunggu Pembayaran" else "✅" if o['status'] == "Selesai" else "📦"
            
            # Format Output Akhir per Pesanan
            text += (
                f"{emoji} <code>{o['order_number']}</code> ({date_str})\n"
                f"📦 <b>Total: {total_qty} Botol</b>\n"
                f"{detail_items}"
                f"   └ Status: <b>{o['status']}</b>\n\n"
            )
            
    if callback.message.caption is not None:
        await callback.message.edit_caption(caption=text, reply_markup=get_back_kb())
    else:
        await callback.message.edit_text(text=text, reply_markup=get_back_kb())

@router.callback_query(F.data == "my_profile")
async def show_profile(callback: CallbackQuery):
    """Manajemen Profil User (Alamat & Data Diri)"""
    if not supabase: return
    
    cust = supabase.table("customers").select("*").eq("telegram_id", callback.from_user.id).single().execute()
    data = cust.data or {}
    
    name = data.get("full_name", callback.from_user.full_name)
    address = data.get("default_address") or "<i>Belum diatur</i>"
    
    text = (
        f"⚙️ <b>PROFIL SAYA</b>\n\n"
        f"👤 Nama: <b>{name}</b>\n"
        f"🏠 Alamat Pengiriman:\n{address}\n\n"
        f"<i>Pastikan alamat kakak sudah benar agar kurir tidak nyasar ya!</i>"
    )
    
    if callback.message.caption is not None:
        await callback.message.edit_caption(caption=text, reply_markup=get_profile_kb())
    else:
        await callback.message.edit_text(text=text, reply_markup=get_profile_kb())

@router.callback_query(F.data == "help_center")
async def help_center(callback: CallbackQuery):
    """Pusat Bantuan (FIXED Bug tombol tidak berfungsi)"""
    text = (
        "❓ <b>PUSAT BANTUAN BABA PARFUME KPS</b> 🇮🇩🇰🇭\n\n"
        "<b>1. Berapa lama wangi parfum bertahan?</b>\n"
        "Sangat awet kak! Di kulit wangi *soft*-nya bisa tahan 12-24 jam lebih. Kalau di pakaian, kadang bajunya sudah dicuci pun wanginya masih nempel! Tahan minimal 8 jam++.\n\n"
        "<b>2. Apakah aman di kulit dan baju?</b>\n"
        "100% aman! BABA Parfume diracik tanpa alkohol (aman buat dibawa ibadah), gak panas di kulit, gak lengket, gak bikin gatal/iritasi, dan pastinya tidak meninggalkan noda di baju.\n\n"
        "<b>3. Komposisi bahannya dari mana kak?</b>\n"
        "Kualitas kita Import Premium tapi harga santai kak! Dibuat dari paduan 80% bibit import asli Paris dan 20% racikan expert Indonesia. Oh ya, kita juga sudah tersertifikasi BPOM ya!\n\n"
        "<b>4. Apakah ada minimal order untuk pengiriman?</b>\n"
        "Tenang aja kak, kami siap antar ke seluruh area KPS (Kompong Som) TANPA minimal order! Tersedia kemasan 30ml padat manfaat dengan 2 varian khusus: Indoor & Outdoor.\n\n"
        "<i>Ada pertanyaan lain atau mau gabung jadi Reseller/Distributor BABA? Hubungi tim Admin kami di bawah ini ya.</i>"
    )
    
    # Kasih tombol langsung ke WhatsApp Admin atau link kontak
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💬 Hubungi Admin", url="https://t.me/babaparfume_bot")],
        [InlineKeyboardButton(text="🔙 Kembali", callback_data="main_menu")]
    ])
    
    if callback.message.caption is not None:
        await callback.message.edit_caption(caption=text, reply_markup=kb)
    else:
        await callback.message.edit_text(text=text, reply_markup=kb)

# ==============================================================================
# 6. PROFILE EDITING FSM (STATE MACHINE)
# ==============================================================================
@router.callback_query(F.data == "edit_address")
async def start_edit_address(callback: CallbackQuery, state: FSMContext):
    await state.set_state(UserProfileStates.waiting_for_address)
    
    msg = (
        "🏠 <b>UBAH ALAMAT PENGIRIMAN</b>\n\n"
        "Silakan ketik alamat lengkap pengiriman kakak.\n"
        "<i>Format saran: Jalan, RT/RW, Desa/Kelurahan, Kecamatan, Kota/Kabupaten, Provinsi, Kode Pos.</i>\n\n"
        "Ketik <code>Batal</code> jika tidak ingin mengubah."
    )
    
    # Hapus inline keyboard sebelumnya dan minta input text
    await callback.message.delete()
    await callback.message.answer(msg)

@router.message(StateFilter(UserProfileStates.waiting_for_address))
async def process_edit_address(message: Message, state: FSMContext):
    if message.text.lower() == 'batal':
        await state.clear()
        await message.answer("❌ Ubah alamat dibatalkan.", reply_markup=get_back_kb("my_profile", "Kembali ke Profil"))
        return

    new_address = message.text

    if supabase:
        try:
            supabase.table("customers").update({"default_address": new_address}).eq("telegram_id", message.from_user.id).execute()
            await message.answer(
                "✅ <b>Alamat berhasil diperbarui!</b>\n\nPengiriman pesanan selanjutnya akan diarahkan ke alamat ini.",
                reply_markup=get_back_kb("my_profile", "Lihat Profil")
            )
        except Exception as e:
            logger.error(f"Error update address: {e}")
            await message.answer("Terjadi kesalahan sistem. Coba lagi nanti.")
    
    await state.clear()

# ==============================================================================
# 7. BOT NATIVE CATALOG & PAGINATION (SUPER CANGGIH SYSTEM)
# ==============================================================================
@router.callback_query(F.data == "bot_catalog")
async def bot_catalog_root(callback: CallbackQuery):
    """Menampilkan kategori utama dari Database (FIXED)"""
    if not supabase: 
        await callback.answer("Database tidak tersedia saat ini.", show_alert=True)
        return
        
    res = supabase.table("categories").select("*").execute()
    
    if not res.data:
        await callback.answer("Belum ada kategori yang tersedia kak.", show_alert=True)
        return
        
    kb = []
    # Dinamis bikin tombol kategori
    for cat in res.data:
        kb.append([InlineKeyboardButton(text=f"📂 {cat['name']}", callback_data=f"cat_{cat['id']}_1")]) # Default ke halaman 1
        
    kb.append([InlineKeyboardButton(text="🔙 Kembali", callback_data="main_menu")])
    
    text = (
        "🗂️ <b>PILIH KATEGORI PRODUK:</b>\n"
        "Silakan pilih kategori aroma yang paling merepresentasikan dirimu kak."
    )
    
    if callback.message.caption is not None:
        await callback.message.edit_caption(caption=text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    else:
        await callback.message.edit_text(text=text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@router.callback_query(F.data.startswith("cat_") | F.data.startswith("page_"))
async def show_category_products(callback: CallbackQuery):
    """Menangani klik kategori ('Top Seller', 'Man', dll) dan fitur Paginasi (Next/Prev)"""
    # Parse callback data: cat_ID_PAGE atau page_ID_PAGE
    parts = callback.data.split("_")
    category_id = int(parts[1])
    current_page = int(parts[2])
    
    # Ambil semua produk di kategori ini
    products = await get_products_by_category(category_id)
    
    if not products:
        await callback.answer("Maaf kak, produk di kategori ini sedang kosong.", show_alert=True)
        return
        
    # Logic Paginasi Matematika Murni
    total_products = len(products)
    total_pages = math.ceil(total_products / ITEMS_PER_PAGE)
    
    # Proteksi Overpage
    if current_page > total_pages: current_page = total_pages
    if current_page < 1: current_page = 1
    
    start_idx = (current_page - 1) * ITEMS_PER_PAGE
    end_idx = start_idx + ITEMS_PER_PAGE
    
    page_items = products[start_idx:end_idx]
    
    # Render Text Katalog
    # Note: Kita TIDAK menampilkan harga untuk memancing mereka klik ke Mini App
    text = f"📦 <b>KATALOG PRODUK BABA (Halaman {current_page}/{total_pages})</b>\n\n"
    
    for p in page_items:
        stok_status = "🟢 Ready" if p['stock_quantity'] > 0 else "🔴 Sold Out"
        desc = p['description'][:1000] + "..." if p['description'] and len(p['description']) > 1000 else p.get('description', 'Aroma memikat.')
        
        text += (
            f"🔹 <b>{p['name']}</b>\n"
            f"   └ <i>{desc}</i>\n"
            f"   └ Stok: {stok_status}\n\n"
        )
        
    text += "<i>Untuk melihat detail lengkap dan memproses pembelian, silakan buka Web Mini App kami ya kak!</i>"
    
    kb = get_catalog_pagination_kb(category_id, current_page, total_pages)
    
    if callback.message.caption is not None:
        await callback.message.edit_caption(caption=text, reply_markup=kb)
    else:
        await callback.message.edit_text(text=text, reply_markup=kb)

@router.callback_query(F.data == "ignore_pagination")
async def ignore_page_click(callback: CallbackQuery):
    """Hanya penanda halaman, tidak melakukan aksi apa-apa jika diklik"""
    await callback.answer("Ini indikator halaman kak 😉")

# ==============================================================================
# 8. WEB APP LISTENER (FINANCE & CHECKOUT ENGINE)
# ==============================================================================
@router.message(F.web_app_data)
async def handle_checkout_data(message: Message):
    """Menerima dan memproses payload belanja dari Web App (Struk Autopilot)"""
    try:
        raw_data = json.loads(message.web_app_data.data)
        if raw_data.get("action") != "checkout": 
            return

        cust_info = raw_data.get("customer", {})
        items = raw_data.get("items", [])
        total_usd = float(raw_data.get("total_amount", 0))
        pay_method = raw_data.get("payment_method", "COD")
        
        # Generator Nomor Order Canggih
        order_no = f"BABA-{datetime.now().strftime('%y%m%d')}-{str(message.from_user.id)[-4:]}"

        total_qty = 0 # Variabel untuk menghitung total botol parfum

        if supabase:
            # 1. Pastikan Customer Database Terupdate Alamat & Namanya
            supabase.table("customers").update({
                "default_address": cust_info.get("address", ""),
                "full_name": cust_info.get('full_name', message.from_user.full_name)
            }).eq("telegram_id", message.from_user.id).execute()
            
            cust_db = supabase.table("customers").select("id").eq("telegram_id", message.from_user.id).single().execute()
            cust_uuid = cust_db.data.get("id")

            # 2. Injeksi Order Master ke Database (USD di background, tidak dilihat user)
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

            # 3. Looping Items: Simpan Item, Kurangi Stok Fisik, Kalkulasi Kuantitas
            items_text = ""
            for item in items:
                qty = int(item['qty'])
                total_qty += qty
                
                # Rakit text untuk list di Telegram (TIDAK ADA HARGA)
                items_text += f"✔️ {item['name']} — <b>{qty} Botol</b>\n"
                
                # Database injection
                supabase.table("order_items").insert({
                    "order_id": order_uuid,
                    "product_id": item['id'],
                    "quantity": qty,
                    "price_at_time": item['price']
                }).execute()
                
                # Auto Kurangi Stok Fisik Sistem
                p_res = supabase.table("products").select("stock_quantity").eq("id", item['id']).single().execute()
                if p_res.data:
                    current_stock = int(p_res.data['stock_quantity'])
                    new_stok = max(0, current_stock - qty)
                    supabase.table("products").update({"stock_quantity": new_stok}).eq("id", item['id']).execute()

                    # Catat ke Stock Logs untuk tracking audit
                    supabase.table("stock_logs").insert({
                        "product_id": item['id'],
                        "action": "OUT",
                        "adjustment_amount": -qty,
                        "final_stock": new_stok,
                        "reason": f"Sale Order {order_no}",
                        "reference_type": "ORDER",
                        "reference_id": order_uuid
                    }).execute()

        # =========================================================
        # OUTPUT STRUK USER (HARGA DISEMBUNYIKAN SESUAI REQUEST)
        # =========================================================
        # Kita hanya menampilkan "12 botol parfum" untuk menghindari nyesek dollar
        struk = (
            f"🎉 <b>YAY! PESANAN BERHASIL DIAMANKAN!</b> 🎉\n\n"
            f"Terima kasih banyak kak <b>{cust_info.get('full_name')}</b> sudah mempercayakan wangi harinya ke BABA!\n\n"
            f"🧾 <b>Nomor Resi Internal:</b> <code>{order_no}</code>\n\n"
            f"📦 <b>Rincian Barang Bawaan:</b>\n"
            f"{items_text}\n"
            f"Total Angkutan: <b>{total_qty} Botol Parfum</b>\n"
            f"Metode Bayar: <b>{pay_method}</b>\n\n"
            f"<i>Silakan duduk manis kak, tim khusus Admin BABA akan segera memproses dan menghubungi kakak secepat kilat! 🚀🫶</i>"
        )
        
        # Kirim animasi kecil untuk apresiasi
        try:
            await message.reply("Sedang memproses ke gudang... 🚛")
            await asyncio.sleep(1)
            await message.reply(struk, reply_markup=get_main_kb(message.from_user.id))
        except:
            await message.reply(struk)

        # =========================================================
        # NOTIFIKASI RAHASIA KHUSUS ADMIN DIKA (FULL TRANSPARAN USD)
        # =========================================================
        if ADMIN_ID:
            alert = (
                f"🚨 <b>INCOMING SALE MASUK BOS!</b> 🚨\n\n"
                f"ID Order: <code>{order_no}</code>\n"
                f"Customer: {cust_info.get('full_name')} (@{message.from_user.username})\n"
                f"Total Qty: {total_qty} Item\n"
                f"💵 <b>NILAI DEAL: ${total_usd:,.2f}</b>\n"
                f"Sistem Bayar: {pay_method}\n\n"
                f"👉 <i>Segera cek Dashboard Web buat eksekusi konversi kurs IDR dan amankan cuan ke rekening!</i>"
            )
            await bot.send_message(chat_id=ADMIN_ID, text=alert)

    except Exception as e:
        logger.error(f"❌ MiniApp Critical Error: {e}")
        await message.reply("Maaf kak, jalur ke gudang sedang sibuk. Mohon screenshot ini dan hubungi admin manual ya.")

# ==============================================================================
# 9. ADMIN PANEL & COMMAND CENTER (STRATEGIC LEVERAGE)
# ==============================================================================
@router.callback_query(F.data == "admin_panel")
async def admin_main(callback: CallbackQuery):
    """Dashboard Admin Tertutup - Hanya Bos Dika yang bisa lihat"""
    if str(callback.from_user.id) != str(ADMIN_ID): 
        await callback.answer("Akses Ditolak. Area Khusus Direksi.", show_alert=True)
        return
    
    # Analytics Singkat dari Database
    pending_count = 0
    low_stock_count = 0
    if supabase:
        o_res = supabase.table("orders").select("id", count='exact').eq("status", "Menunggu Pembayaran").execute()
        pending_count = o_res.count if hasattr(o_res, 'count') else len(o_res.data or [])
        
        s_res = supabase.table("products").select("id", count='exact').lt("stock_quantity", 10).execute()
        low_stock_count = s_res.count if hasattr(s_res, 'count') else len(s_res.data or [])
    
    text = (
        f"⚡ <b>BABA EXECUTIVE COMMAND CENTER</b> ⚡\n\n"
        f"Status *Engine*: 🟢 <b>OPTIMAL</b>\n\n"
        f"🚨 Pesanan Tertunda: <b>{pending_count} Order</b>\n"
        f"📉 Peringatan Stok (<10): <b>{low_stock_count} Produk</b>\n\n"
        f"<i>Apa instruksi eksekusi selanjutnya, Bos?</i>"
    )
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Broadcast Promo Massal", callback_data="admin_broadcast_init")],
        [InlineKeyboardButton(text="📊 List Stok Menipis", callback_data="admin_low_stock")],
        [InlineKeyboardButton(text="🔙 Balik ke Menu User", callback_data="main_menu")]
    ])
    
    if callback.message.caption is not None:
        await callback.message.edit_caption(caption=text, reply_markup=kb)
    else:
        await callback.message.edit_text(text=text, reply_markup=kb)

@router.callback_query(F.data == "admin_low_stock")
async def admin_low_stock(callback: CallbackQuery):
    if str(callback.from_user.id) != str(ADMIN_ID): return
    if not supabase: return
    
    res = supabase.table("products").select("name, stock_quantity").lt("stock_quantity", 10).order("stock_quantity").execute()
    
    if not res.data:
        text = "✅ Aman Bos. Gak ada stok produk yang di bawah 10 botol."
    else:
        text = "📉 <b>WARNING: STOK KRITIS (< 10 Botol)</b>\n\n"
        for p in res.data:
            text += f"⚠️ {p['name']} — Sisa <b>{p['stock_quantity']}</b>\n"
        text += "\n<i>Segera kontak supplier buat restock biar cashflow ga mandek!</i>"
        
    await callback.message.edit_text(text=text, reply_markup=get_back_kb("admin_panel", "Kembali ke Admin"))

# ==============================================================================
# 10. ADMIN BROADCAST FSM (ENGAGEMENT ENGINE)
# ==============================================================================
@router.callback_query(F.data == "admin_broadcast_init")
async def start_broadcast(callback: CallbackQuery, state: FSMContext):
    if str(callback.from_user.id) != str(ADMIN_ID): return
    
    await state.set_state(AdminStates.waiting_for_broadcast_message)
    await callback.message.answer(
        "📢 <b>MODE BROADCAST AKTIF</b>\n\n"
        "Silakan kirim pesan yang ingin di-*blast* ke SEMUA pengguna bot ini.\n"
        "Mendukung Format HTML (<b>Bold</b>, <i>Italic</i>, <a>Link</a>).\n\n"
        "Ketik <code>Batal</code> untuk membatalkan."
    )
    await callback.answer()

@router.message(StateFilter(AdminStates.waiting_for_broadcast_message))
async def process_broadcast(message: Message, state: FSMContext):
    if message.text and message.text.lower() == 'batal':
        await state.clear()
        await message.answer("✅ Broadcast dibatalkan, Bos.")
        return

    if not supabase:
        await message.answer("Database mati, gagal narik data user.")
        await state.clear()
        return

    # Tarik semua user Telegram ID yang terdaftar
    res = supabase.table("customers").select("telegram_id").execute()
    users = res.data or []
    
    if not users:
        await message.answer("Belum ada user di database buat di broadcast.")
        await state.clear()
        return

    await message.answer(f"🚀 Memulai blast ke {len(users)} pengguna...")
    
    success = 0
    failed = 0
    
    # Looping eksekusi broadcast
    for u in users:
        tid = u.get("telegram_id")
        if not tid: continue
        
        try:
            # Copy text (atau photo) ke user
            await bot.copy_message(chat_id=tid, from_chat_id=message.chat.id, message_id=message.message_id)
            success += 1
            await asyncio.sleep(0.05) # Jaga Rate Limit API Telegram
        except Exception as e:
            failed += 1
            
    await message.answer(
        f"📊 <b>LAPORAN BROADCAST SELESAI</b>\n\n"
        f"✅ Berhasil Terkirim: {success}\n"
        f"❌ Gagal/Diblokir: {failed}\n\n"
        f"<i>Job done. Growth engine jalan.</i>"
    )
    await state.clear()

# ==============================================================================
# 11. CATCH-ALL HANDLER (PESAN TYPING SALAH / ISENG) - REQUEST DIKA
# ==============================================================================
@router.message(F.text & ~F.text.startswith('/'))
async def catch_all_messages(message: Message):
    """
    Menangkap semua teks biasa yang di-ketik oleh user yang bukan command.
    Sesuai instruksi: Harus ramah, sopan, dan mengarahkan mereka untuk tap-tap aja.
    """
    # Jangan reply kalau user lagi di state ngisi alamat atau ngisi broadcast!
    # Handler ini ditaruh PALING BAWAH, jadi dia gak nabrak StateFilter di atas.
    
    response = (
        "jangan cape cape ketik kak😁 langsung pencet /start aja dan klik klik aja🥰\n\n"
        "enjoy selalu ya belanja nya^^ salam wangi🫶"
    )
    await message.reply(response)


# ==============================================================================
# 12. BACKGROUND TASKS & HEALTH CHECK SCHEDULER
# ==============================================================================
async def scheduler_pending_orders():
    """Tugas latar belakang: Ingatkan Admin jika ada order lumutan yang belum dieksekusi kursnya"""
    await asyncio.sleep(60) # Delay awal 1 Menit setelah booting
    while True:
        try:
            if supabase and ADMIN_ID:
                res = supabase.table("orders").select("order_number, total_amount, created_at").eq("status", "Menunggu Pembayaran").execute()
                orders = res.data or []
                
                if len(orders) >= 3:
                    msg = (
                        f"⚠️ <b>SYSTEM ALERT: BOTTLENECK DETECTED!</b> ⚠️\n\n"
                        f"Bos, ada <b>{len(orders)}</b> pesanan numpuk di database belum lu konversi & validasi.\n"
                        f"Jangan ditunda, duitnya ngendap tuh! Segera buka Web Admin Dashboard dan eksekusi."
                    )
                    await bot.send_message(chat_id=ADMIN_ID, text=msg)
        except Exception as e:
            logger.error(f"Scheduler System Error: {e}")
            
        await asyncio.sleep(3600) # Cek ulang tiap 1 Jam biar ga spam

# ==============================================================================
# 13. MAIN ENTRY POINT (BOOTSTRAPPING)
# ==============================================================================
async def main():
    """Fungsi utama untuk me-render bot dan menyalakan semua logic engine"""
    
    # Set UI Menu Command di Telegram User (Garis tiga kiri bawah)
    await bot.set_my_commands([
        BotCommand(command="start", description="🔄 Refresh Bot & Menu Utama"),
        BotCommand(command="help", description="❓ Bantuan & Layanan CS"),
    ])
    
    # Load Routers
    dp.include_router(router)
    
    # Nyalakan Background Engine
    asyncio.create_task(scheduler_pending_orders())
    
    # Start Polling System
    logger.info("🚀===============================================🚀")
    logger.info("🔥 BABA ENTERPRISE BOT [V2 UPGRADE] IS ONLINE! 🔥")
    logger.info("🚀===============================================🚀")
    
    # Hapus webhook lama kalau ada biar gak bentrok
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("👋 Shutting down BABA Bot Gracefully...")