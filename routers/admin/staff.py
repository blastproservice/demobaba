import hashlib
import base64
from typing import Optional
from datetime import datetime

from fastapi import APIRouter, Request, Form, HTTPException, status, Query, Depends
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from database import supabase
from routers.common import render_admin_template, require_admin_roles, sanitize_admin_role, ADMIN_USER, SECRET_TOKEN, COOKIE_NAME, logger, ALLOWED_ADMIN_ROLES, api_success, api_error
from routers.dependencies import get_current_admin

# ==============================================================================
# ROUTER ENDPOINTS MANAJEMEN STAFF
# ==============================================================================
router = APIRouter(prefix='/admin', tags=['Admin Staff'])

# --- SCHEMAS PYDANTIC (VALIDASI KETAT API) ---
class StaffAddPayload(BaseModel):
    full_name: str
    username: str
    password: str = Field(..., min_length=6)
    role: str

class StaffUpdatePayload(BaseModel):
    staff_id: int
    full_name: str
    username: str
    role: str

class PasswordResetPayload(BaseModel):
    staff_id: int
    new_password: str = Field(..., min_length=6)


# ==============================================================================
# 1. RENDER HALAMAN UTAMA STAFF
# ==============================================================================
@router.get('/staff', response_class=HTMLResponse, dependencies=[require_admin_roles('super_admin')])
async def admin_staff_page(request: Request, admin=Depends(get_current_admin)):
    """Menampilkan daftar karyawan BABA, khusus Super Admin"""
    staff_list = []
    if supabase:
        try:
            # Tarik data admin, urutkan dari yang terbaru
            res = supabase.table("admins").select("*").order("created_at", desc=True).execute()
            staff_list = res.data or []
        except Exception as e:
            logger.error(f"❌ [STAFF DB ERROR]: {e}")

    return render_admin_template(request, "admin/staff.html", admin_data=admin, staffs=staff_list)


# ==============================================================================
# 2. API: TAMBAH KARYAWAN BARU
# ==============================================================================
@router.post('/staff/api/add', dependencies=[require_admin_roles('super_admin')])
async def api_add_staff(payload: StaffAddPayload):
    if not supabase: return api_error("Database Offline", 503)

    safe_username = payload.username.lower().strip()
    safe_name = payload.full_name.strip()
    
    # Validasi Bentrok dengan .env
    if safe_username == ADMIN_USER.strip().lower():
        return api_error("Gagal! Username ini terlarang karena dipakai Super Admin Utama.")
        
    # Validasi Role
    safe_role = payload.role.strip().lower()
    if safe_role not in ["oprasional", "marketing", "cs", "visitor"]:
        return api_error("Hak akses jabatan tidak valid!")

    # Cek Duplikat Username di Database
    cek_db = supabase.table("admins").select("id").eq("username", safe_username).execute()
    if cek_db.data:
        return api_error("Username sudah dipakai karyawan lain! Silakan gunakan username berbeda.")

    # Enkripsi Password
    hashed_pw = hashlib.sha256(payload.password.encode()).hexdigest()

    try:
        supabase.table("admins").insert({
            "username": safe_username,
            "password_hash": hashed_pw,
            "full_name": safe_name,
            "role": safe_role,
            "last_activity_desc": "Sistem: Akun Baru Diregistrasi"
        }).execute()
        
        logger.info(f"👮 [STAFF] Akun direkrut: {safe_username} sebagai {safe_role}")
        return api_success(message=f"Karyawan {safe_name} sukses direkrut!")
    except Exception as e:
        logger.error(f"❌ [STAFF ADD ERROR]: {e}")
        return api_error(f"Sistem gagal menyimpan data: {str(e)}")


# ==============================================================================
# 3. API: EDIT PROFIL & ROLE KARYAWAN
# ==============================================================================
@router.post('/staff/api/update', dependencies=[require_admin_roles('super_admin')])
async def api_update_staff(payload: StaffUpdatePayload):
    if not supabase: return api_error("Sistem Database Offline.", 503)
    
    safe_role = sanitize_admin_role(payload.role)
    if safe_role in {"", "super_admin"}: return api_error("Role tidak diizinkan.")
    
    safe_username = payload.username.strip().lower()
    
    # Cek apakah username baru nabrak punya orang lain (kecuali punya dia sendiri)
    cek_db = supabase.table("admins").select("id").eq("username", safe_username).execute()
    if cek_db.data and cek_db.data[0].get("id") != payload.staff_id:
        return api_error("Username sudah dipakai oleh karyawan lain!")

    try:
        supabase.table("admins").update({
            "full_name": payload.full_name.strip(),
            "username": safe_username,
            "role": safe_role
        }).eq("id", payload.staff_id).execute()
        
        return api_success(message="Profil dan akses staff berhasil diperbarui.")
    except Exception as e:
        logger.error(f"❌ [STAFF UPDATE ERROR]: {e}")
        return api_error("Gagal mengupdate profil karyawan.")


# ==============================================================================
# 4. API: RESET PASSWORD KARYAWAN
# ==============================================================================
@router.post('/staff/api/reset-password', dependencies=[require_admin_roles('super_admin')])
async def api_reset_password(payload: PasswordResetPayload):
    if not supabase: return api_error("Sistem Database Offline.", 503)
    try:
        hashed_pw = hashlib.sha256(payload.new_password.encode()).hexdigest()
        supabase.table("admins").update({
            "password_hash": hashed_pw,
            "last_activity_desc": "Password Direset Secara Manual oleh Super Admin"
        }).eq("id", payload.staff_id).execute()
        
        return api_success(message="Password staff berhasil diganti secara paksa.")
    except Exception as e:
        logger.error(f"❌ [STAFF RESET PW ERROR]: {e}")
        return api_error("Gagal mereset password karyawan.")


# ==============================================================================
# 5. API: HAPUS (PECAT) KARYAWAN
# ==============================================================================
@router.post('/staff/api/delete', dependencies=[require_admin_roles('super_admin')])
async def api_delete_staff(payload: dict):
    staff_id = payload.get("staff_id")
    if not staff_id or not supabase: return api_error("Permintaan ditolak.")
    
    try:
        supabase.table("admins").delete().eq("id", staff_id).execute()
        return api_success(message="Karyawan resmi dipecat dan dihapus dari sistem.")
    except Exception as e:
        logger.error(f"❌ [STAFF DELETE ERROR]: {e}")
        # Error biasanya karena ada constraint dari tabel lain (misal tabel orders yg nyatet ID admin ini)
        return api_error("Gagal menghapus! Karyawan ini memiliki rekam jejak transaksi di database. Ubah rolenya menjadi Visitor saja.")