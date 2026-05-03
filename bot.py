import os
import json
import logging
import asyncio
import hashlib
from datetime import datetime
from typing import Optional, List, Dict

from dotenv import load_dotenv

# Aiogram v3 Stack
from aiogram import Bot, Dispatcher, F, Router, html
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, 
    WebAppData, WebAppInfo, BotCommand, LabeledPrice, PreCheckoutQuery
)
from aiogram.filters import CommandStart, Command, StateFilter
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

# ==============================================================================
# 0. INITIALIZATION & SECURITY
# ==============================================================================
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = os.getenv("ADMIN_ID") # ID Telegram Lu (Bos Utama)
WEB_APP_URL = os.getenv("WEB_APP_URL")

if not BOT_TOKEN:
    raise ValueError("[FATAL] BOT_TOKEN missing in .env!")

# Logging Setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("BabaEnterpriseBot")

# Core Aiogram Objects
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
router = Router()

# Database Bridge
try:
    from database import supabase
except ImportError:
    logger.error("❌ Database module not found!")
    supabase = None

# ==============================================================================
# 1. DATABASE & FINANCE UTILS (SYNC WITH WEB ENGINE)
# ==============================================================================
async def sync_user(user_id: int, username: str, full_name: str):
    """Pastikan data pelanggan sinkron dengan tabel customers di Supabase"""
    if not supabase: return
    try:
        # Cek apakah sudah ada
        res = supabase.table("customers").select("id, total_orders").eq("telegram_id", user_id).execute()
        
        payload = {
            "telegram_id": user_id,
            "username": username or "",
            "full_name": full_name or "User BABA",
            "updated_at": datetime.now().isoformat()
        }
        
        if not res.data:
            supabase.table("customers").insert(payload).execute()
            logger.info(f"🆕 New Customer: {full_name} ({user_id})")
        else:
            supabase.table("customers").update(payload).eq("telegram_id", user_id).execute()
    except Exception as e:
        logger.error(f"⚠️ Sync Error: {e}")

async def get_user_stats(user_id: int) -> Dict:
    """Tarik data history belanja dan poin loyalty dari DB"""
    if not supabase: return {}
    try:
        res = supabase.table("customers").select("total_orders, total_spent").eq("telegram_id", user_id).single().execute()
        return res.data or {}
    except: return {}

# ==============================================================================
# 2. KEYBOARD BUILDERS (DYNAMICS)
# ==============================================================================
def get_main_kb(user_id: int) -> InlineKeyboardMarkup:
    # Mini Apps Integration
    web_shop = WebAppInfo(url=WEB_APP_URL)
    web_ai = WebAppInfo(url=f"{WEB_APP_URL}/cs")
    
    buttons = [
        [InlineKeyboardButton(text="🛍️ MULAI BELANJA (MINI APP)", web_app=web_shop)],
        [InlineKeyboardButton(text="🤖 KONSULTASI PARFUM (AI)", web_app=web_ai)],
        [
            InlineKeyboardButton(text="📋 Pesanan Saya", callback_data="my_orders"),
            InlineKeyboardButton(text="💎 Loyalty Point", callback_data="my_points")
        ],
        [
            InlineKeyboardButton(text="🏬 Katalog Bot", callback_data="bot_catalog"),
            InlineKeyboardButton(text="❓ Bantuan", callback_data="help_center")
        ]
    ]
    
    # Tombol Khusus Admin (Dika)
    if str(user_id) == str(ADMIN_ID):
        buttons.append([InlineKeyboardButton(text="⚡ ADMIN DASHBOARD", callback_data="admin_panel")])
        
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_back_kb(target: str = "main_menu") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Kembali", callback_data=target)]
    ])

# ==============================================================================
# 3. CORE HANDLERS (USER SIDE)
# ==============================================================================
@router.message(CommandStart())
async def start_handler(message: Message):
    """Pintu masuk utama bot"""
    await sync_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
    
    welcome_msg = (
        f"🌟 <b>BABA PARFUME ENTERPRISE</b> 🌟\n\n"
        f"Halo kak {html.bold(message.from_user.first_name)}! Selamat datang di layanan autopilot kami.\n\n"
        f"Kami menyediakan parfum kualitas <i>Import Paris</i> dengan ketahanan seharian. "
        f"Silakan gunakan menu di bawah untuk mulai menjelajah."
    )
    
    # Kirim foto logo jika ada di static web
    try:
        await message.answer_photo(
            photo=f"{WEB_APP_URL}/static/img/Logo_BABA.png",
            caption=welcome_msg,
            reply_markup=get_main_kb(message.from_user.id)
        )
    except:
        await message.answer(welcome_msg, reply_markup=get_main_kb(message.from_user.id))

@router.callback_query(F.data == "main_menu")
async def back_to_main(callback: CallbackQuery):
    await callback.message.edit_caption(
        caption="👇 <b>Silakan pilih menu utama BABA:</b>",
        reply_markup=get_main_kb(callback.from_user.id)
    )

@router.callback_query(F.data == "my_points")
async def show_points(callback: CallbackQuery):
    stats = await get_user_stats(callback.from_user.id)
    total_spent = stats.get("total_spent", 0)
    # Kalkulasi Loyalty Point (Misal: Tiap $1 dapet 10 poin)
    points = int(total_spent * 10)
    
    text = (
        f"💎 <b>BABA LOYALTY PROGRAM</b>\n\n"
        f"Status Akun: <b>Premium Member</b>\n"
        f"Total Belanja: <b>${total_spent:,.2f}</b>\n"
        f"Poin Terkumpul: <b>{points} Poin</b>\n\n"
        f"<i>Kumpulkan terus poinmu dan tukarkan dengan diskon khusus di pembelian selanjutnya!</i>"
    )
    await callback.message.edit_caption(caption=text, reply_markup=get_back_kb())

@router.callback_query(F.data == "my_orders")
async def show_order_history(callback: CallbackQuery):
    if not supabase: return
    
    # Ambil Customer ID dulu
    cust = supabase.table("customers").select("id").eq("telegram_id", callback.from_user.id).single().execute()
    if not cust.data: return
    
    # Ambil 5 pesanan terakhir
    res = supabase.table("orders").select("*").eq("customer_id", cust.data['id']).order("created_at", desc=True).limit(5).execute()
    
    if not res.data:
        text = "❌ <b>Kamu belum pernah melakukan pemesanan.</b>\nYuk mulai belanja sekarang!"
    else:
        text = "📋 <b>5 PESANAN TERAKHIR KAMU:</b>\n\n"
        for o in res.data:
            emoji = "🕒" if o['status'] == "Menunggu Pembayaran" else "✅" if o['status'] == "Selesai" else "📦"
            text += f"{emoji} <code>{o['order_number']}</code> | <b>${o['total_amount']}</b>\nStatus: <i>{o['status']}</i>\n\n"
            
    await callback.message.edit_caption(caption=text, reply_markup=get_back_kb())

# ==============================================================================
# 4. CATALOG SYSTEM (BOT EXPLORER)
# ==============================================================================
@router.callback_query(F.data == "bot_catalog")
async def bot_catalog_root(callback: CallbackQuery):
    """Menampilkan kategori produk langsung di Bot"""
    if not supabase: return
    res = supabase.table("categories").select("*").execute()
    
    kb = []
    for cat in res.data:
        kb.append([InlineKeyboardButton(text=f"📂 {cat['name']}", callback_data=f"cat_{cat['id']}")])
    kb.append([InlineKeyboardButton(text="🔙 Kembali", callback_data="main_menu")])
    
    await callback.message.edit_caption(
        caption="🗂️ <b>PILIH KATEGORI PRODUK:</b>\nSilakan pilih kategori yang ingin kakak lihat detailnya.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb)
    )

# ==============================================================================
# 5. MINI APP BRIDGE (REFINED FINANCE LOGIC)
# ==============================================================================
@router.message(F.web_app_data)
async def handle_checkout_data(message: Message):
    """Menerima data belanja dari Mini App"""
    try:
        raw_data = json.loads(message.web_app_data.data)
        if raw_data.get("action") != "checkout": return

        cust_info = raw_data.get("customer", {})
        items = raw_data.get("items", [])
        total_usd = float(raw_data.get("total_amount", 0))
        pay_method = raw_data.get("payment_method", "COD")
        
        # Buat Nomor Order Unik
        order_no = f"ORD-{datetime.now().strftime('%y%m%d')}-{str(message.from_user.id)[-4:]}"

        if supabase:
            # 1. Update/Get Customer UUID
            supabase.table("customers").update({
                "default_address": cust_info.get("address", ""),
                "full_name": cust_info.get('full_name', message.from_user.full_name)
            }).eq("telegram_id", message.from_user.id).execute()
            
            cust_db = supabase.table("customers").select("id").eq("telegram_id", message.from_user.id).single().execute()
            cust_uuid = cust_db.data.get("id")

            # 2. Simpan Order Utama (Input USD murni, Web yang konversi)
            order_res = supabase.table("orders").insert({
                "order_number": order_no,
                "customer_id": cust_uuid,
                "shipping_address": cust_info.get("address", ""),
                "total_amount": total_usd, # BOT TIDAK KONVERSI!
                "status": "Menunggu Pembayaran",
                "payment_method": pay_method,
                "order_source": "Telegram Mini App"
            }).execute()
            
            order_uuid = order_res.data[0].get("id")

            # 3. Simpan Item & Kurangi Stok (Booking)
            for item in items:
                supabase.table("order_items").insert({
                    "order_id": order_uuid,
                    "product_id": item['id'],
                    "quantity": item['qty'],
                    "price_at_time": item['price']
                }).execute()
                
                # Pengurangan stok fisik
                p_res = supabase.table("products").select("stock_quantity").eq("id", item['id']).single().execute()
                new_stok = max(0, int(p_res.data['stock_quantity']) - int(item['qty']))
                supabase.table("products").update({"stock_quantity": new_stok}).eq("id", item['id']).execute()

        # Feedback Struk ke Pelanggan
        struk = (
            f"✅ <b>ORDER BERHASIL DICATAT!</b>\n\n"
            f"No. Pesanan: <code>{order_no}</code>\n"
            f"Total Tagihan: <b>${total_usd:,.2f}</b>\n"
            f"Metode: <b>{pay_method}</b>\n\n"
            f"⚠️ <b>INSTRUKSI PEMBAYARAN:</b>\n"
            f"Silakan tunggu admin menghubungi kakak untuk konversi nilai ke <b>Rupiah (IDR)</b> "
            f"sesuai kurs yang berlaku di Web Dashboard kami.\n\n"
            f"<i>Terima kasih sudah memilih BABA Parfume!</i>"
        )
        await message.reply(struk)

        # Alert ke Admin (Dika)
        if ADMIN_ID:
            alert = (
                f"🚨 <b>ORDER BARU MASUK!</b>\n\n"
                f"ID: {order_no}\n"
                f"User: {cust_info.get('full_name')} (@{message.from_user.username})\n"
                f"Total: ${total_usd:,.2f}\n"
                f"Bayar: {pay_method}\n\n"
                f"👉 <i>Cek Dashboard Web buat konversi Kurs & Update Aset!</i>"
            )
            await bot.send_message(chat_id=ADMIN_ID, text=alert)

    except Exception as e:
        logger.error(f"❌ MiniApp Error: {e}")
        await message.reply("Maaf kak, sistem pendaftaran order sedang sibuk. Mohon hubungi admin manual.")

# ==============================================================================
# 6. ADMIN PANEL (COMMAND CENTER)
# ==============================================================================
@router.callback_query(F.data == "admin_panel")
async def admin_main(callback: CallbackQuery):
    if str(callback.from_user.id) != str(ADMIN_ID): return
    
    # Ambil Statistik Singkat
    if supabase:
        orders = supabase.table("orders").select("id").eq("status", "Menunggu Pembayaran").execute()
        pending = len(orders.data or [])
    else: pending = 0
    
    text = (
        f"⚡ <b>BABA ADMIN COMMAND CENTER</b>\n\n"
        f"Pesanan Pending: <b>{pending} Order</b>\n"
        f"Status Server: 🟢 <b>ONLINE</b>\n\n"
        f"Gunakan menu di bawah untuk mengontrol sistem bot:"
    )
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Broadcast Pesan", callback_data="admin_broadcast")],
        [InlineKeyboardButton(text="📊 Lihat Stok Menipis", callback_data="admin_low_stock")],
        [InlineKeyboardButton(text="🔙 Menu User", callback_data="main_menu")]
    ])
    
    await callback.message.edit_caption(caption=text, reply_markup=kb)

# ==============================================================================
# 7. BACKGROUND TASKS & HEALTH CHECK
# ==============================================================================
async def scheduler_pending_orders():
    """Tugas latar belakang: Ingatkan Admin jika ada order lumutan"""
    await asyncio.sleep(30) # Delay awal
    while True:
        try:
            if supabase and ADMIN_ID:
                res = supabase.table("orders").select("order_number, total_amount").eq("status", "Menunggu Pembayaran").execute()
                orders = res.data or []
                if len(orders) >= 3:
                    msg = (
                        f"⚠️ <b>WAKE UP BOS!</b>\n\n"
                        f"Ada <b>{len(orders)}</b> pesanan yang belum lu konversi di Web.\n"
                        f"Duitnya lumutan tuh, buruan diproses!"
                    )
                    await bot.send_message(chat_id=ADMIN_ID, text=msg)
        except Exception as e:
            logger.error(f"Scheduler Error: {e}")
        await asyncio.sleep(1800) # Cek tiap 30 menit

# ==============================================================================
# 8. MAIN ENTRY POINT
# ==============================================================================
async def main():
    # Set Menu Command
    await bot.set_my_commands([
        BotCommand(command="start", description="Menu Utama BABA"),
        BotCommand(command="help", description="Bantuan & CS"),
    ])
    
    dp.include_router(router)
    
    # Jalankan scheduler di background
    asyncio.create_task(scheduler_pending_orders())
    
    logger.info("🚀 BABA Enterprise Bot is Starting...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("👋 Bot Stopped.")
