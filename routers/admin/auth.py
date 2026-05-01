from fastapi import APIRouter, Request, Form, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse
from passlib.context import CryptContext

from routers.common import templates, logger
try:
    from database import supabase
except ImportError:
    supabase = None

# Setup alat pengecek password hash (Bcrypt)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

router = APIRouter(prefix="/admin", tags=["Authentication"])

@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("admin/login.html", {"request": request})

@router.post("/login")
async def process_login(request: Request, username: str = Form(...), password: str = Form(...)):
    if not supabase:
        return templates.TemplateResponse("admin/login.html", {"request": request, "error": "Koneksi database terputus!"})

    try:
        # 1. Cari admin berdasarkan username di Supabase
        res = supabase.table("admins").select("*").eq("username", username).execute()
        admin_data = res.data

        if not admin_data:
            return templates.TemplateResponse("admin/login.html", {"request": request, "error": "Username tidak ditemukan!"})

        admin = admin_data[0]

        # 2. Cocokkan Password
        # CATATAN: Kalo di DB lu masih nyimpen password pake teks biasa (belum di-hash),
        # hapus tanda pagar di baris bawah ini dan comment baris pwd_context.verify
        # valid_pass = (password == admin["password_hash"])
        
        valid_pass = pwd_context.verify(password, admin["password_hash"])

        if not valid_pass:
            return templates.TemplateResponse("admin/login.html", {"request": request, "error": "Password salah bro!"})

        # 3. Kalo Valid, Beri Karcis Masuk (Cookie)
        response = RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)
        
        # Simpan ID Admin ke dalam cookie selama 1 hari (86400 detik)
        response.set_cookie(
            key="baba_admin_session", 
            value=str(admin["id"]), 
            httponly=True, 
            max_age=86400 
        )
        
        logger.info(f"Admin {username} berhasil login.")
        return response

    except Exception as e:
        logger.error(f"Error Login: {e}")
        return templates.TemplateResponse("admin/login.html", {"request": request, "error": "Terjadi kesalahan sistem."})

@router.get("/logout")
async def logout():
    response = RedirectResponse(url="/admin/login", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie("baba_admin_session") # Hapus Karcis
    return response