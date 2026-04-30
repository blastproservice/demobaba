import os
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

# ==============================================================================
# 1. IMPORT MESIN BOT AIOGRAM
# ==============================================================================
try:
    from bot import bot, dp, router as bot_router, alarm_pesanan_pending
    BOT_AVAILABLE = True
    print("✅ [SYSTEM] Modul Bot berhasil di-load!")
except Exception as e:
    print(f"❌ [SYSTEM] Gagal import bot.py: {e}")
    BOT_AVAILABLE = False

# ==============================================================================
# 2. IMPORT SEMUA ROUTER MODULAR (Arsitektur Baru)
# ==============================================================================
# Ini adalah kabel-kabel yang menghubungkan semua modul yang udah kita rakit
from routers.customer import store
from routers.admin import dashboard, stock, finance, orders, customers, settings, cs

# ==============================================================================
# 3. LIFESPAN JANTUNG INTEGRASI (Sihir Telegram & FastAPI)
# ==============================================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    print("🚀 [LIFESPAN] BABA Enterprise Engine Starting...")
    
    bot_task = None
    if BOT_AVAILABLE:
        try:
            dp.include_router(bot_router)
            await bot.delete_webhook(drop_pending_updates=True)
            
            # Jalanin Polling & Alarm di Background tanpa ngeblok server web
            asyncio.create_task(alarm_pesanan_pending(bot))
            bot_task = asyncio.create_task(dp.start_polling(bot, handle_signals=False))
            
            print("✅ [LIFESPAN] Bot Telegram Standby & Siap Tempur!")
        except Exception as e:
            print(f"❌ [LIFESPAN] Error nyalain bot: {e}")

    yield # Di sini aplikasi Web lu running dan ngelayanin customer

    print("🛑 [LIFESPAN] Shutting down...")
    if bot_task:
        bot_task.cancel()
    if BOT_AVAILABLE:
        await bot.session.close()

# ==============================================================================
# 4. INISIALISASI FASTAPI CORE
# ==============================================================================
app = FastAPI(
    title="BABA Parfume Enterprise Engine",
    description="Modular & Scalable Backend by Andika",
    version="5.0.0",
    lifespan=lifespan # Inject jantungnya ke sini
)

# Pasang Tameng CORS biar API lu aman dipanggil dari web mana aja
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Wajib buat load CSS, JS, Gambar logo BABA
app.mount("/static", StaticFiles(directory="static"), name="static")

# ==============================================================================
# 5. PEMASANGAN KABEL ROUTER (The Gatekeeper)
# ==============================================================================
# Frontend Customer
app.include_router(store.router)

# Backend Admin Terpisah
app.include_router(dashboard.router)
app.include_router(stock.router)
app.include_router(finance.router)
app.include_router(orders.router)
app.include_router(customers.router)
app.include_router(settings.router)
app.include_router(cs.router)

# ==============================================================================
# EKSEKUSI SERVER LOCAL (Buat Testing)
# ==============================================================================
if __name__ == "__main__":
    print("\n" + "=".center(60, "="))
    print("🚀 BABA PARFUME ENTERPRISE ENGINE (MODULAR)".center(60))
    print("=".center(60, "="))
    print("🌐 Web Pelanggan   : http://localhost:8000/")
    print("🛠️  Panel Admin     : http://localhost:8000/admin")
    print("=".center(60, "=") + "\n")
    
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)