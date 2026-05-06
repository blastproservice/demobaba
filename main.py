import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

# ==============================================================================
# IMPORT SISTEM KEAMANAN & ENGINE BOT
# ==============================================================================
from security import apply_enterprise_security
from bot import main as start_telegram_bot

# ==============================================================================
# IMPORT SEMUA KOMANDAN (ROUTERS)
# ==============================================================================
from routers.admin import (
    auth, cs_management, dashboard, stock, finance, orders, 
    customers, settings, staff, profile
)
from routers.customer import cs, store, profile as cust_profile

# IMPORT ROUTER CRM & AUTOMATION
from routers.crm import (
    dashboard as crm_dashboard,
    sessions,
    templates,
    auto_reply,
    broadcast
)

# Setup Logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("baba.engine")

# ==============================================================================
# LIFESPAN MANAGER (Jantung Background Tasks & Bot Telegram)
# ==============================================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("[SYSTEM] BABA Enterprise Engine Starting...")
    
    # Nyalain logic Aiogram Bot Telegram jadi satu komando sama Web FastAPI
    bot_task = asyncio.create_task(start_telegram_bot())
    logger.info("[SYSTEM] Telegram Bot Standby & Polling Aktif!")
    
    yield # Di titik ini, web lu jalan ngelayanin customer
    
    logger.info("[SYSTEM] Shutting down...")
    if bot_task:
        logger.info("[SYSTEM] Mematikan Bot Telegram...")
        bot_task.cancel()

# ==============================================================================
# INISIASI APLIKASI UTAMA (SANG JENDERAL)
# ==============================================================================
app = FastAPI(
    title="BABA Parfume Enterprise",
    description="Core Engine for BABA Parfume Management, CRM, & Bot",
    version="2.0.0",
    lifespan=lifespan,
    docs_url=None, # Matiin docs bawaan buat security
    redoc_url=None
)

# ==============================================================================
# TAMENG KEAMANAN (ENTERPRISE SHIELD)
# ==============================================================================
# Menggantikan CORS bawaan dengan pengamanan 3 Lapis dari security.py
apply_enterprise_security(app)

# ==============================================================================
# MOUNT FOLDER STATIC (CSS, JS, GAMBAR)
# ==============================================================================
app.mount("/static", StaticFiles(directory="static"), name="static")

# ==============================================================================
# SISTEM TENDANGAN OTOMATIS (EXCEPTION HANDLERS)
# ==============================================================================
@app.exception_handler(StarletteHTTPException)
async def custom_http_exception_handler(request: Request, exc: StarletteHTTPException):
    # Kalau ketahuan gak punya karcis/cookie (401), lempar ke halaman Login
    if exc.status_code == 401:
        return RedirectResponse(url="/admin/login", status_code=303)
    
    # Kalau URL ngaco (404 Not Found), bisa kita arahin ke halaman custom 404 nanti
    if exc.status_code == 404:
        return HTMLResponse(content="<h1>404 - Halaman Tidak Ditemukan</h1>", status_code=404)
        
    return HTMLResponse(content=f"Error {exc.status_code}: {exc.detail}", status_code=exc.status_code)

# ==============================================================================
# COLOKIN KABEL ROUTER (PEMBAGIAN TUGAS)
# ==============================================================================
# 1. Router Admin Zone
app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(stock.router)
app.include_router(finance.router)
app.include_router(orders.router)
app.include_router(customers.router)
app.include_router(settings.router)
app.include_router(staff.router)
app.include_router(cs_management.router)
app.include_router(profile.router)
app.include_router(cs.router)

# 2. Router Customer Zone (Web Store BABA)
app.include_router(store.router)
app.include_router(cust_profile.router)

# 3. Router CRM & Automation Zone
app.include_router(crm_dashboard.router)
app.include_router(sessions.router)
app.include_router(templates.router)
app.include_router(auto_reply.router)
app.include_router(broadcast.router)

# ==============================================================================
# ENGINE RUNNER (Buat testing lokal)
# ==============================================================================
if __name__ == "__main__":
    import uvicorn
    # Jalankan ini pake command: python main.py
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)