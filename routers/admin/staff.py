import hashlib
from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi import status
from routers.common import supabase, render_admin_template, require_admin_roles, sanitize_admin_role, ADMIN_USER

def sanitize_admin_role(role: Optional[str]) -> str:
    normalized_role = (role or "").strip().lower()
    return normalized_role if normalized_role in ALLOWED_ADMIN_ROLES else ""


def decode_admin_cookie(token: str) -> tuple[str, str, str]:
    raw_decoded = base64.b64decode(token).decode()
    username, role, name, signature = raw_decoded.split("|")
    expected_sig = hashlib.sha256(f"{username}|{role}|{name}|{SECRET_TOKEN}".encode()).hexdigest()
    if signature != expected_sig:
        raise ValueError("Signature Cookie Dipalsukan!")
    role = sanitize_admin_role(role)
    if not role:
        raise ValueError("Role admin tidak dikenal.")
    return username.strip(), role, name.strip()

def create_secure_cookie(username: str, role: str, name: str) -> str:
    """Bikin tiket cookie yang dienkripsi biar ga bisa dipalsuin hacker"""
    safe_username = username.strip().lower()
    safe_role = sanitize_admin_role(role)
    if not safe_role:
        raise ValueError("Role admin tidak valid.")
    safe_name = name.strip()
    raw_data = f"{safe_username}|{safe_role}|{safe_name}|{SECRET_TOKEN}"
    signature = hashlib.sha256(raw_data.encode()).hexdigest()
    # Gabungin data asli sama tanda tangannya (signature), lalu ubah ke Base64
    cookie_value = base64.b64encode(f"{safe_username}|{safe_role}|{safe_name}|{signature}".encode()).decode()
    return cookie_value

async def verify_admin(request: Request):
    """Dependency: Mengamankan HTML Admin & Ngebaca Jabatan (Role)"""
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=status.HTTP_303_SEE_OTHER, headers={"Location": "/admin/login"})
    
    try:
        username, role, name = decode_admin_cookie(token)

        if role == "super_admin":
            if username != ADMIN_USER.strip().lower():
                raise ValueError("Username super admin tidak cocok dengan .env.")
            current_name = "Dewa BABA (Super Admin)"
        else:
            if not supabase:
                raise ValueError("Database admin tidak tersedia.")

            admin_res = (
                supabase.table("admins")
                .select("username, full_name, role")
                .eq("username", username)
                .limit(1)
                .execute()
            )
            if not admin_res.data:
                raise ValueError("Akun admin tidak ditemukan lagi.")

            admin_data = admin_res.data[0]
            db_role = sanitize_admin_role(admin_data.get("role"))
            if db_role != role:
                raise ValueError("Role admin sudah berubah atau tidak valid.")
            current_name = admin_data.get("full_name") or name or username

        # Simpan data profil ke 'state' biar bisa dibaca sama Jinja2 HTML
        request.state.admin_user = username
        request.state.admin_role = role
        request.state.admin_name = current_name
        return True
    except Exception as e:
        logger.warning(f"🔒 [AUTH HACK ATTEMPT] Cookie gak valid: {e}")
        raise HTTPException(status_code=status.HTTP_303_SEE_OTHER, headers={"Location": "/admin/login"})

async def verify_admin_api(request: Request):
    """Dependency: Mengamankan API Admin"""
    await verify_admin(request) # Pake logika yang sama aja
    return True


def require_admin_roles(*allowed_roles: str):
    normalized_roles = {sanitize_admin_role(role) for role in allowed_roles}
    normalized_roles.discard("")

    async def dependency(request: Request):
        await verify_admin(request)
        current_role = getattr(request.state, "admin_role", "")
        if normalized_roles and current_role not in normalized_roles:
            raise HTTPException(status_code=403, detail="Akses admin ditolak untuk halaman ini.")
        return True

    return Depends(dependency)

router=APIRouter(prefix='/admin', tags=['Admin Staff'])

@router.get('/staff', response_class=HTMLResponse, dependencies=[require_admin_roles('super_admin')])
async def admin_staff_page(request: Request):
    """Menampilkan daftar karyawan BABA, khusus Super Admin"""
    staff_list = []
    if supabase:
        try:
            res = supabase.table("admins").select("*").order("created_at", desc=True).execute()
            staff_list = res.data or []
        except Exception as e:
            logger.error(f"❌ [STAFF DB ERROR]: {e}")

    return render_admin_template(request, "admin/staff.html", staffs=staff_list)

@router.post('/staff/add', dependencies=[require_admin_roles('super_admin')])
async def add_new_staff(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    full_name: str = Form(...),
    role: str = Form(...)
):
    # Enkripsi password sebelum masuk DB
    import hashlib
    hashed_pw = hashlib.sha256(password.encode()).hexdigest()
    safe_role = sanitize_admin_role(role)
    safe_username = username.lower().strip()
    safe_name = full_name.strip()

    if safe_role in {"", "super_admin"}:
        raise HTTPException(status_code=400, detail="Role staff tidak valid.")
    if safe_username == ADMIN_USER.strip().lower():
        raise HTTPException(status_code=400, detail="Username bentrok dengan super admin dari .env.")
    if not supabase:
        raise HTTPException(status_code=503, detail="Database admin tidak tersedia.")

    try:
        supabase.table("admins").insert({
            "username": safe_username,
            "password_hash": hashed_pw,
            "full_name": safe_name,
            "role": safe_role
        }).execute()
        logger.info(f"👮 [STAFF] Akun baru dibuat: {safe_username} sebagai {safe_role}")
        return RedirectResponse(url="/admin/staff", status_code=status.HTTP_303_SEE_OTHER)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post('/staff/delete/{admin_id}', dependencies=[require_admin_roles('super_admin')])
async def delete_staff(request: Request, admin_id: int):
    if not supabase:
        raise HTTPException(status_code=503, detail="Database admin tidak tersedia.")
    try:
        supabase.table("admins").delete().eq("id", admin_id).execute()
        return RedirectResponse(url="/admin/staff", status_code=status.HTTP_303_SEE_OTHER)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

