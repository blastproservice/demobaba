from fastapi import APIRouter, Request, Form, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

# Import koneksi Supabase murni dari root
try:
    from database import supabase
except ImportError:
    print("❌ [SYSTEM] File database.py tidak ditemukan!")
    supabase = None

# Inisiasi Router khusus Admin Finance
# Pake prefix /admin/finance biar URL-nya otomatis rapi
router = APIRouter(prefix="/admin/finance", tags=["Admin Finance"])
templates = Jinja2Templates(directory="templates")

# ==============================================================================
# HELPER FUNCTIONS
# ==============================================================================
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
@router.get("/aset", response_class=HTMLResponse)
async def admin_finance_aset(request: Request):
    accounts = []
    total_liquid = 0.0
    if supabase:
        try:
            # Tarik data dompet/bank dari tabel 'wallets'
            res = supabase.table("wallets").select("*").execute()
            accounts = res.data or []
            total_liquid = sum(float(a.get('saldo_aktif', 0)) for a in accounts)
        except Exception as e:
            print(f"❌ [ERROR FINANCE ASET]: {e}")

    return templates.TemplateResponse("admin/finance_aset.html", {
        "request": request,
        "accounts": accounts,
        "total_liquid": total_liquid,
        "pending_count": get_pending_count()
    })

@router.get("/mutasi", response_class=HTMLResponse)
async def admin_finance_mutasi(request: Request):
    # Nanti logic tarik data mutasi dari Supabase masuk sini
    return templates.TemplateResponse("admin/finance_mutasi.html", {
        "request": request,
        "pending_count": get_pending_count()
    })

@router.get("/report", response_class=HTMLResponse)
async def admin_finance_report(request: Request):
    return templates.TemplateResponse("admin/finance_report.html", {
        "request": request,
        "pending_count": get_pending_count()
    })

# ==============================================================================
# JALUR API / LOGIKA BISNIS (CRUD)
# ==============================================================================
# Ini eksekusi buat tombol "+ Bank Baru" di HTML lu
@router.post("/bank")
async def tambah_bank_baru(
    nama_bank: str = Form(...),
    nomor_rekening: str = Form(...),
    saldo_awal: float = Form(...)
):
    try:
        data_bank = {
            "nama_bank": nama_bank,
            "nomor_rekening": nomor_rekening,
            "saldo_aktif": saldo_awal,
            "currency": "IDR" # Siap di-scale buat USD di market Kamboja
        }
        
        # Insert ke tabel 'wallets' di Supabase
        supabase.table("wallets").insert(data_bank).execute()
        
        # Balik lagi ke halaman aset setelah sukses
        return RedirectResponse(url="/admin/finance/aset", status_code=status.HTTP_303_SEE_OTHER)
        
    except Exception as e:
        print(f"❌ [ERROR TAMBAH BANK]: {e}")
        raise HTTPException(status_code=500, detail=str(e))