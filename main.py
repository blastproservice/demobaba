import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

# ==============================================================================
# IMPORT SEMUA KOMANDAN (ROUTERS)
# ==============================================================================
from routers.admin import (
    auth, cs_management, dashboard, stock, finance, orders, 
    customers, settings, staff, profile
)
from routers.customer import store

# Setup Logger (Biar gampang pantau error di VPS)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("baba.engine")

# ==============================================================================
# LIFESPAN MANAGER (Jantung Background Tasks & Bot Telegram)
# ==============================================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("[SYSTEM] BABA Enterprise Engine Starting...")
    
    # TODO: Nanti kita nyalain logic Aiogram Bot Telegram lu di sini
    # bot_task = asyncio.create_task(start_bot())
    # logger.info("[SYSTEM] Telegram Bot Standby!")
    
    yield # Di titik ini, web lu jalan ngelayanin customer
    
    logger.info("[SYSTEM] Shutting down...")
    # if bot_task:
    #     bot_task.cancel()

# ==============================================================================
# INISIASI APLIKASI UTAMA (SANG JENDERAL)
# ==============================================================================
app = FastAPI(
    title="BABA Parfume Enterprise",
    description="Core Engine for BABA Parfume Management & Bot",
    version="2.0.0",
    lifespan=lifespan,
    docs_url=None, # Matiin docs bawaan buat security
    redoc_url=None
)

# ==============================================================================
# TAMENG KEAMANAN & MIDDLEWARE (CORS)
# ==============================================================================
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # Nanti ganti pake domain asli lu pas naik VPS
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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

# 2. Router Customer Zone (Web Store BABA)
app.include_router(store.router)

# ==============================================================================
# ENGINE RUNNER (Buat testing lokal)
# ==============================================================================
if __name__ == "__main__":
    import uvicorn
    # Jalankan ini pake command: python main.py
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
