import os
import json
import logging
import asyncio
from datetime import datetime
from dotenv import load_dotenv

# Aiogram v3
from aiogram import Bot, Dispatcher, F, Router
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, 
    WebAppData, WebAppInfo
)
from aiogram.filters import CommandStart
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

# Import Database
try:
    from database import supabase
except ImportError:
    print("❌ [FATAL ERROR] File database.py tidak ditemukan!")
    supabase = None

# ==============================================================================
# 1. SETUP & KONFIGURASI
# ==============================================================================
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = os.getenv("ADMIN_ID") 
WEB_APP_URL = os.getenv("WEB_APP_URL") or "http://127.0.0.1:8000"

if not BOT_TOKEN:
    raise ValueError("❌ [ERROR] BOT_TOKEN belum diisi di file .env!")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("BabaBotEngine")

# INI DIA YANG DICARI SAMA main.py (Variabel 'bot', 'dp', 'router')
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
router = Router()

__all__ = ['bot', 'dp', 'router', 'alarm_pesanan_pending']

# ==============================================================================
# 2. SISTEM DATABASE HELPER
# ==============================================================================
async def sync_user_to_db(user):
    if not supabase: return
    try:
        res = supabase.table("customers").select("*").eq("telegram_id", user.id).execute()
        payload = {
            "telegram_id": user.id,
            "username": user.username or "",
            "full_name": user.full_name or "User BABA"
        }
        if not res.data:
            supabase.table("customers").insert(payload).execute()
        else:
            supabase.table("customers").update(payload).eq("telegram_id", user.id).execute()
    except Exception as e:
        logger.error(f"❌ [DB SYNC ERROR] {e}")

# ==============================================================================
# 3. UI/UX KEYBOARD BUILDER
# ==============================================================================
def kb_main_menu() -> InlineKeyboardMarkup:
    web_app_belanja = WebAppInfo(url=WEB_APP_URL)
    web_app_ai = WebAppInfo(url=f"{WEB_APP_URL}/ai-chat")
    
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛍️ PESEN DI SINI (KLIK)", web_app=web_app_belanja)],
        [InlineKeyboardButton(text="🤖 Tanya Ahli Parfum (AI)", web_app=web_app_ai)],
        [
            InlineKeyboardButton(text="👥 Lihat Grup", url="https://t.me/GrupBabaParfume"),
            InlineKeyboardButton(text="💬 Hubungi Admin BABA", callback_data="menu_admin")
        ],
        [InlineKeyboardButton(text="💰 Tanya Harga", callback_data="menu_harga")]
    ])

def kb_admin_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📱 Admin Telegram", url="https://t.me/AndikaKot"),
            InlineKeyboardButton(text="🟢 Admin WhatsApp", url="https://wa.me/6281234567890")
        ],
        [InlineKeyboardButton(text="🔙 Kembali ke Menu Utama", callback_data="menu_utama")]
    ])

def kb_harga_menu() -> InlineKeyboardMarkup:
    web_app_belanja = WebAppInfo(url=WEB_APP_URL)
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔥 Mulai dari 10$ Aja! (Cek Katalog)", web_app=web_app_belanja)],
        [InlineKeyboardButton(text="🔙 Kembali", callback_data="menu_utama")]
    ])

# ==============================================================================
# 4. HANDLERS UTAMA
# ==============================================================================
@router.message(CommandStart())
async def command_start_handler(message: Message) -> None:
    await sync_user_to_db(message.from_user)
    welcome_text = (
        f"Halo kak <b>{message.from_user.first_name}</b>! ✨ Selamat datang di BABA Parfume Official Bot.\n\n"
        f"Mencari wangi yang <i>'kamu banget'</i>? Kamu udah ada di tempat yang tepat!\n"
        f"BABA Parfume diracik dengan bibit Import Paris, 100% Halal, BPOM, dan pastinya Tahan Lama seharian.\n\n"
        f"👇 <b>Silakan pilih menu di bawah ini ya kak:</b>"
    )
    await message.reply(welcome_text, reply_markup=kb_main_menu())

@router.callback_query(F.data == "menu_admin")
async def callback_menu_admin(callback: CallbackQuery):
    text = "👨‍💼 <b>Layanan Pelanggan BABA Parfume</b>\n\nSilakan pilih jalur komunikasi yang nyaman buat kamu:"
    await callback.message.edit_text(text, reply_markup=kb_admin_menu())
    await callback.answer()

@router.callback_query(F.data == "menu_harga")
async def callback_menu_harga(callback: CallbackQuery):
    text = "💸 <b>Pricelist BABA Parfume</b>\n\nHarga varian premium kita <b>Mulai dari $10 aja!</b> 👇"
    await callback.message.edit_text(text, reply_markup=kb_harga_menu())
    await callback.answer()

@router.callback_query(F.data == "menu_utama")
async def callback_menu_utama(callback: CallbackQuery):
    text = f"Mencari wangi yang <i>'kamu banget'</i>? Kamu udah ada di tempat yang tepat!\n\n👇 <b>Silakan pilih menu di bawah:</b>"
    await callback.message.edit_text(text, reply_markup=kb_main_menu())
    await callback.answer()

# ==============================================================================
# 5. THE BRIDGE: NANGKEP DATA DARI MINI APPS
# ==============================================================================
@router.message(F.web_app_data)
async def handle_web_app_data(message: Message):
    try:
        data = json.loads(message.web_app_data.data)
        if data.get("action") != "checkout": return

        cust_info = data.get("customer", {})
        items = data.get("items", [])
        total_amount = data.get("total_amount", 0)
        payment_method = data.get("payment_method", "Tidak Diketahui")
        address = cust_info.get("address", "")
        
        order_number = f"ORD-{datetime.now().strftime('%y%m%d')}-{str(message.from_user.id)[-4:]}"

        if supabase:
            supabase.table("customers").update({
                "default_address": address,
                "full_name": cust_info.get('full_name', message.from_user.full_name)
            }).eq("telegram_id", message.from_user.id).execute()
            
            cust_db = supabase.table("customers").select("id").eq("telegram_id", message.from_user.id).single().execute()
            cust_uuid = cust_db.data.get("id")

            order_payload = {
                "order_number": order_number,
                "customer_id": cust_uuid,
                "shipping_address": address,
                "total_amount": total_amount,
                "status": "Menunggu Pembayaran",
                "order_source": "Telegram Bot Mini App"
            }
            order_res = supabase.table("orders").insert(order_payload).execute()
            order_uuid = order_res.data[0].get("id")

            for item in items:
                supabase.table("order_items").insert({
                    "order_id": order_uuid,
                    "product_id": item['id'],
                    "quantity": item['qty'],
                    "price_at_time": item['price']
                }).execute()

                prod_data = supabase.table("products").select("stock_quantity").eq("id", item['id']).single().execute()
                new_stock = max(0, prod_data.data.get("stock_quantity", 0) - item['qty'])
                supabase.table("products").update({"stock_quantity": new_stock}).eq("id", item['id']).execute()

        struk_belanja = (
            f"✅ <b>YAY! PESANAN BERHASIL DIBUAT!</b>\n\n"
            f"Terima kasih kak <b>{cust_info.get('full_name')}</b>!\n"
            f"Nomor Pesanan: <code>{order_number}</code>\n"
            f"Total Tagihan: <b>${total_amount:.2f}</b>\n"
            f"Metode Bayar: <b>{payment_method}</b>\n\n"
            f"<i>Silakan tunggu sebentar ya, tim Admin BABA akan segera menghubungi kakak.</i> 🚀"
        )
        await message.reply(struk_belanja)

        if ADMIN_ID:
            alert_admin = (
                f"🚨 <b>BOS ADA ORDERAN BARU MASUK!</b> 🚨\n\n"
                f"Dari: {cust_info.get('full_name')} (@{cust_info.get('username')})\n"
                f"Nilai Order: ${total_amount:.2f}\n"
                f"Alamat: {address}\n\n"
                f"Cek Dashboard Web sekarang buat diproses!"
            )
            await bot.send_message(chat_id=ADMIN_ID, text=alert_admin)

    except Exception as e:
        logger.error(f"❌ [WEB APP DATA ERROR]: {e}")
        await message.reply("Waduh kak, sistem kita lagi sibuk nih. Coba pesan manual ke admin ya.")

@router.message(F.text)
async def catch_all_messages(message: Message):
    if message.text.startswith("/"): return
    await message.reply("Kak <b>/start</b> dulu ya nanti tinggal klik klik aja di menunya, jangan cape cape ngetik hehe 😊✨")

# ==============================================================================
# 6. BACKGROUND TASK: AUTO-SPAM ADMIN
# ==============================================================================
async def alarm_pesanan_pending(bot_instance: Bot):
    await asyncio.sleep(60)
    while True:
        try:
            if supabase and ADMIN_ID:
                res = supabase.table("orders").select("id").eq("status", "Menunggu Pembayaran").execute()
                pending_orders = res.data or []
                if len(pending_orders) > 0:
                    pesan_spam = (
                        f"⚠️ <b>WAKE UP BOS! ADA {len(pending_orders)} PESANAN PENDING!</b> ⚠️\n\n"
                        f"Customer nungguin tuh, buruan diproses di Dashboard Web biar duitnya cepet cair!\n"
                    )
                    await bot_instance.send_message(chat_id=ADMIN_ID, text=pesan_spam)
        except Exception as e:
            logger.error(f"Error Background Task: {e}")
        await asyncio.sleep(300)