from fastapi import APIRouter, Request, Form, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

# Import koneksi Supabase murni
try:
    from database import supabase
except ImportError:
    print("❌ [SYSTEM] File database.py tidak ditemukan!")
    supabase = None

# Inisiasi Router khusus Admin Settings
router = APIRouter(prefix="/admin", tags=["Admin Settings"])
templates = Jinja2Templates(directory="templates")

# Helper buat notif lonceng merah
def get_pending_count() -> int:
    if not supabase: return 0
    try:
        res = supabase.table("orders").select("id").eq("status", "Menunggu Pembayaran").execute()
        return len(res.data or [])
    except:
        return 0

# ==============================================================================
# JALUR RENDER HALAMAN HTML
# ==============================================================================
@router.get("/settings", response_class=HTMLResponse, tags=["Admin Settings"], dependencies=[require_admin_roles("super_admin")])
async def admin_settings(request: Request):
    # Default fallback kalau database kosong
    settings_data = {
        "store_name": "BABA Parfume", 
        "admin_whatsapp": "", 
        "checkout_message": "Halo BABA Parfume, saya mau pesan...",
        "is_bot_active": True
    }
    
    if supabase:
        try:
            # Tarik data setting dengan ID 1 (Single Source of Truth)
            res = supabase.table("store_settings").select("*").eq("id", 1).single().execute()
            if res.data: 
                settings_data = res.data
        except Exception as e:
            print(f"⚠️ [INFO SETTING]: Belum ada data setting di DB, pakai sistem default. Detail: {e}")
            
    return templates.TemplateResponse("admin/settings.html", {
        "request": request, 
        "settings": settings_data, 
        "pending_count": get_pending_count()
    })

# ==============================================================================
# JALUR API / LOGIKA BISNIS (UPDATE ENGINE)
# ==============================================================================
@router.post("/settings/update")
async def update_settings(
    store_name: str = Form(...),
    admin_whatsapp: str = Form(""),
    checkout_message: str = Form(""),
    # Kita set default "false" biar kalau checkbox di HTML nggak dicentang, API nggak crash
    is_bot_active: str = Form("false") 
):
    try:
        # PENGAMANAN FRONTEND: Konversi string dari form HTML jadi Boolean murni buat Supabase
        bot_status = True if str(is_bot_active).lower() in ['true', 'on', '1', 'yes'] else False
        
        payload = {
            "store_name": store_name,
            "admin_whatsapp": admin_whatsapp,
            "checkout_message": checkout_message,
            "is_bot_active": bot_status
        }
        
        if supabase:
            # Pake UPSERT: Kalau data ID 1 belum ada, dia bikin baru. Kalau udah ada, dia tindih (update).
            supabase.table("store_settings").upsert({**payload, "id": 1}).execute()
            print("✅ [SUKSES] Engine Settings berhasil di-update!")
            
        return RedirectResponse(url="/admin/settings", status_code=status.HTTP_303_SEE_OTHER)
        
    except Exception as e:
        print(f"❌ [ERROR SETTING]: {e}")
        raise HTTPException(status_code=500, detail="Gagal menyimpan pengaturan sistem.")
