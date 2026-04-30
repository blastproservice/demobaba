from typing import Optional
from datetime import datetime
import calendar
import uuid, base64, asyncio
import google.genai
from fastapi import APIRouter, Request, Depends, HTTPException, status, Form
from fastapi.responses import HTMLResponse, RedirectResponse

from routers.common import supabase, logger, render_admin_template, require_admin_roles, api_success, api_error
from routers.schemas import ManualTransactionPayload, TransferPayload
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
# JALUR HALAMAN HTML
# ==============================================================================
@router.get("/aset", response_class=HTMLResponse, tags=["Admin Finance"], dependencies=[require_admin_roles("super_admin", "oprasional")])
async def admin_finance_aset(request: Request):
    """Menampilkan Dashboard Aset & Dompet (Mobile Banking Style)"""
    accounts = []
    total_liquid = 0.0
    total_inventory = 0.0
    recent_mutations = []
    categories_in = []
    categories_out = []

    if supabase:
        try:
            # 1. Tarik Data Rekening Bank
            res_acc = supabase.table("finance_accounts").select("*").eq("is_active", True).order("id").execute()
            accounts = res_acc.data or []
            total_liquid = sum(float(acc.get("current_balance", 0)) for acc in accounts)

            # 2. Hitung Nilai Aset Barang Fisik (Stok * Harga Modal/Jual)
            res_prod = supabase.table("products").select("stock_quantity, original_price").eq("is_active", True).execute()
            for p in (res_prod.data or []):
                total_inventory += float(p.get("stock_quantity", 0)) * float(p.get("original_price", 0))

            # 3. Tarik Riwayat Mutasi Terakhir
            res_mut = supabase.table("finance_mutations").select(
                "*, finance_accounts(bank_name), finance_categories(category_name)"
            ).order("created_at", desc=True).limit(5).execute()
            recent_mutations = res_mut.data or []

            # 4. Tarik Kategori Transaksi
            res_cat = supabase.table("finance_categories").select("*").execute()
            categories = res_cat.data or []
            categories_in = [c for c in categories if c.get("type") == "INCOME"]
            categories_out = [c for c in categories if c.get("type") == "EXPENSE"]

        except Exception as e:
            logger.error(f"❌ [FINANCE ASET ERROR]: {e}")

    return render_admin_template(
        request, "admin/finance_aset.html",
        accounts=accounts,
        total_liquid=total_liquid,
        total_inventory=total_inventory,
        total_aset=total_liquid + total_inventory,
        recent_mutations=recent_mutations,
        categories_in=categories_in,
        categories_out=categories_out
    )

@router.get("/mutasi", response_class=HTMLResponse, tags=["Admin Finance"], dependencies=[require_admin_roles("super_admin", "oprasional")])
async def admin_finance_mutasi(request: Request):
    """Menampilkan Ledger / Riwayat Buku Besar Keseluruhan"""
    mutations = []
    accounts = []
    if supabase:
        try:
            res_acc = supabase.table("finance_accounts").select("id, bank_name").execute()
            accounts = res_acc.data or []

            res_mut = supabase.table("finance_mutations").select(
                "*, finance_accounts(bank_name), finance_categories(category_name, type)"
            ).order("created_at", desc=True).limit(500).execute() # Limit agar tidak berat
            mutations = res_mut.data or []
        except Exception as e:
            logger.error(f"❌ [FINANCE MUTASI ERROR]: {e}")

    return render_admin_template(
        request, "admin/finance_mutasi.html", 
        mutations=mutations, accounts=accounts
    )

@router.get("/report", response_class=HTMLResponse, tags=["Admin Finance"], dependencies=[require_admin_roles("super_admin")])
async def admin_finance_report(request: Request, month: Optional[str] = None, year: Optional[str] = None):
    """
    Generate Profit & Loss (P&L) Statement Terlengkap.
    (FIXED: Menggunakan .gte() dan .lte() untuk memfilter tipe data Timestamp di PostgreSQL)
    """
    
    report_data = {
        "total_revenue": 0.0,
        "total_hpp": 0.0,
        "total_opex": 0.0,
        "gross_profit": 0.0,
        "net_profit": 0.0,
        "margin": 0.0,
        "total_trx_in": 0,
        "total_trx_out": 0,
        "avg_revenue_per_day": 0.0,
        "biggest_expense_cat": "",
        "biggest_expense_amt": 0.0
    }
    
    categories_breakdown = {
        "income": {},
        "hpp": {},
        "opex": {}
    }
    daily_trends = {}
    raw_mutations = []
    
    if supabase:
        try:
            # 1. Tentukan Periode Tanggal
            now = datetime.now()
            target_month = int(month) if month else now.month
            target_year = int(year) if year else now.year

            # Cari tau tanggal terakhir di bulan tersebut (Misal: 28, 30, atau 31)
            last_day = calendar.monthrange(target_year, target_month)[1]

            # Format ke bentuk rentang waktu (Awal bulan sampai Akhir bulan)
            start_date = f"{target_year}-{target_month:02d}-01T00:00:00"
            end_date = f"{target_year}-{target_month:02d}-{last_day}T23:59:59"

            # 2. Tarik Data menggunakan GTE (>=) dan LTE (<=) agar PostgreSQL tidak error
            res_mut = supabase.table("finance_mutations").select(
                "id, amount, transaction_type, created_at, description, finance_categories(category_name, type), finance_accounts(bank_name)"
            ).gte("created_at", start_date).lte("created_at", end_date).order("created_at", desc=False).execute()
            
            raw_mutations = res_mut.data or []
            
            # 3. PROSES KALKULASI
            for m in raw_mutations:
                cat_info = m.get("finance_categories") or {}
                raw_cat_name = cat_info.get("category_name", "Tanpa Kategori")
                cat_name = str(raw_cat_name).lower()
                
                amt = float(m.get("amount", 0))
                trx_date = m.get("created_at", "").split("T")[0] # Ambil YYYY-MM-DD
                
                if trx_date not in daily_trends:
                    daily_trends[trx_date] = {"in": 0.0, "out": 0.0}
                
                if m.get("transaction_type") == "IN":
                    report_data["total_revenue"] += amt
                    report_data["total_trx_in"] += 1
                    daily_trends[trx_date]["in"] += amt
                    categories_breakdown["income"][raw_cat_name] = categories_breakdown["income"].get(raw_cat_name, 0) + amt

                elif m.get("transaction_type") == "OUT":
                    report_data["total_trx_out"] += 1
                    daily_trends[trx_date]["out"] += amt
                    
                    # Identifikasi HPP (Logic Original Lu)
                    is_hpp = any(keyword in cat_name for keyword in ["stok", "belanja", "jastip", "ongkir", "biang", "botol", "lakban"])
                    
                    if is_hpp:
                        report_data["total_hpp"] += amt
                        categories_breakdown["hpp"][raw_cat_name] = categories_breakdown["hpp"].get(raw_cat_name, 0) + amt
                    else:
                        report_data["total_opex"] += amt
                        categories_breakdown["opex"][raw_cat_name] = categories_breakdown["opex"].get(raw_cat_name, 0) + amt
                        
                        # Deteksi Beban Operasional Terbesar
                        if categories_breakdown["opex"][raw_cat_name] > report_data["biggest_expense_amt"]:
                            report_data["biggest_expense_amt"] = categories_breakdown["opex"][raw_cat_name]
                            report_data["biggest_expense_cat"] = raw_cat_name

            # 4. FINALISASI DATA
            report_data["gross_profit"] = report_data["total_revenue"] - report_data["total_hpp"]
            report_data["net_profit"] = report_data["gross_profit"] - report_data["total_opex"]
            
            if report_data["total_revenue"] > 0:
                report_data["margin"] = round((report_data["net_profit"] / report_data["total_revenue"]) * 100, 2)
            
            active_days = len(daily_trends) if len(daily_trends) > 0 else 1
            report_data["avg_revenue_per_day"] = round(report_data["total_revenue"] / active_days, 2)

            logger.info(f"📊 [FINANCE REPORT] Kalkulasi sukses! Omset: {report_data['total_revenue']}")

        except Exception as e:
            logger.error(f"❌ [FINANCE REPORT ERROR]: {e}")

    return render_admin_template(
        request, 
        "admin/finance_report.html", 
        report=report_data,
        breakdown=categories_breakdown,
        daily_trends=daily_trends,
        mutations=raw_mutations,
        period_text=f"{target_month:02d}/{target_year}"
    )

@router.get("/api/v1/finance/transaction", response_class=HTMLResponse, tags=["Admin Finance"], dependencies=[require_admin_roles("super_admin", "oprasional")])
async def api_manual_transaction(request: Request, payload: ManualTransactionPayload):
    """Mencatat Pemasukan/Pengeluaran manual (Suntikan modal, bayar listrik, dll)"""
    if not supabase: return api_error("Database offline", 503)
    
    admin_id = None # Idealnya ditarik dari request.state jika id admin dilacak
    
    try:
        # 1. Cek saldo akun saat ini
        res_acc = supabase.table("finance_accounts").select("current_balance").eq("id", payload.account_id).single().execute()
        if not res_acc.data:
            return api_error("Rekening tidak ditemukan")
        
        current_balance = float(res_acc.data.get("current_balance", 0))
        amount = float(payload.amount)

        # 2. Hitung saldo baru
        if payload.transaction_type == "IN":
            new_balance = current_balance + amount
        else:
            if current_balance < amount:
                return api_error("Saldo tidak cukup untuk pengeluaran ini!", 400)
            new_balance = current_balance - amount

        # 3. Update Saldo Rekening
        supabase.table("finance_accounts").update({"current_balance": new_balance}).eq("id", payload.account_id).execute()

        # 4. Catat ke Buku Besar (Mutasi)
        supabase.table("finance_mutations").insert({
            "account_id": payload.account_id,
            "category_id": payload.category_id,
            "transaction_type": payload.transaction_type,
            "amount": amount,
            "balance_after": new_balance,
            "description": payload.description
        }).execute()

        logger.info(f"💸 [FINANCE] Transaksi {payload.transaction_type} senilai {amount} berhasil di akun {payload.account_id}")
        return api_success(message="Transaksi berhasil dicatat", new_balance=new_balance)

    except Exception as e:
        logger.error(f"❌ [API TRX ERROR]: {e}")
        return api_error("Gagal mencatat transaksi", 500)

@router.get("/api/v1/finance/transfer", response_class=HTMLResponse, tags=["Admin Finance"], dependencies=[require_admin_roles("super_admin", "oprasional")])
async def api_transfer_transaction(request: Request, payload: TransferPayload):
    """Mencatat Pindah Kas / Switch Money Antar Rekening (Mendukung Beda Mata Uang)"""
    if not supabase: return api_error("Database offline", 503)
    
    try:
        # 1. Cek Rekening Sumber (From)
        res_from = supabase.table("finance_accounts").select("current_balance, bank_name, currency").eq("id", payload.from_account_id).single().execute()
        if not res_from.data: return api_error("Rekening sumber tidak ditemukan")
        
        # 2. Cek Rekening Tujuan (To)
        res_to = supabase.table("finance_accounts").select("current_balance, bank_name, currency").eq("id", payload.to_account_id).single().execute()
        if not res_to.data: return api_error("Rekening tujuan tidak ditemukan")

        balance_from = float(res_from.data.get("current_balance", 0))
        balance_to = float(res_to.data.get("current_balance", 0))

        # 3. Validasi Saldo Sumber
        if balance_from < payload.amount_out:
            return api_error(f"Saldo {res_from.data.get('bank_name')} tidak cukup! Saldo: {balance_from}", 400)

        # 4. Hitung Saldo Baru
        new_balance_from = balance_from - payload.amount_out
        new_balance_to = balance_to + payload.amount_in

        # 5. Cari Kategori "Pindah Kas" atau "Transfer"
        # Kalau gak ada, kita pake ID 1 aja sebagai fallback
        cat_res = supabase.table("finance_categories").select("id").ilike("category_name", "%pindah%").limit(1).execute()
        if not cat_res.data:
            cat_res = supabase.table("finance_categories").select("id").ilike("category_name", "%transfer%").limit(1).execute()
        
        cat_id = cat_res.data[0].get("id") if cat_res.data else 1

        # =======================================================
        # EKSEKUSI DATABASE (POTONG -> TAMBAH -> LOG MUTASI)
        # =======================================================
        
        # Bikin UUID unik untuk referensi transaksi ini (biar gampang dilacak)
        transfer_ref = f"TF-{datetime.now().strftime('%y%m%d%H%M')}"
        deskripsi_lengkap = f"[{transfer_ref}] {payload.description} (Rate: {payload.exchange_rate})"

        # A. UPDATE & LOG REKENING SUMBER (KELUAR)
        supabase.table("finance_accounts").update({"current_balance": new_balance_from}).eq("id", payload.from_account_id).execute()
        supabase.table("finance_mutations").insert({
            "account_id": payload.from_account_id,
            "category_id": cat_id,
            "transaction_type": "OUT",
            "amount": payload.amount_out,
            "balance_after": new_balance_from,
            "description": f"Pindah kas keluar ke {res_to.data.get('bank_name')} - {deskripsi_lengkap}"
        }).execute()

        # B. UPDATE & LOG REKENING TUJUAN (MASUK)
        supabase.table("finance_accounts").update({"current_balance": new_balance_to}).eq("id", payload.to_account_id).execute()
        supabase.table("finance_mutations").insert({
            "account_id": payload.to_account_id,
            "category_id": cat_id,
            "transaction_type": "IN",
            "amount": payload.amount_in,
            "balance_after": new_balance_to,
            "description": f"Terima pindah kas dari {res_from.data.get('bank_name')} - {deskripsi_lengkap}"
        }).execute()

        logger.info(f"💱 [FINANCE TRANSFER] {payload.amount_out} {res_from.data.get('currency')} dipindah ke {res_to.data.get('currency')} jadi {payload.amount_in}")
        return api_success(message="Pindah kas berhasil diproses!")

    except Exception as e:
        logger.error(f"❌ [API TRANSFER ERROR]: {e}")
        return api_error("Gagal memproses pindah kas", 500)

@router.get("/report-legacy", response_class=HTMLResponse, tags=["Admin Finance"], dependencies=[require_admin_roles("super_admin")])
async def admin_finance_report(request: Request, month: Optional[str] = None, year: Optional[str] = None):
    """
    Generate Profit & Loss (P&L) Statement Terlengkap.
    (FIXED: Menggunakan .gte() dan .lte() untuk memfilter tipe data Timestamp di PostgreSQL)
    """
    
    report_data = {
        "total_revenue": 0.0,
        "total_hpp": 0.0,
        "total_opex": 0.0,
        "gross_profit": 0.0,
        "net_profit": 0.0,
        "margin": 0.0,
        "total_trx_in": 0,
        "total_trx_out": 0,
        "avg_revenue_per_day": 0.0,
        "biggest_expense_cat": "",
        "biggest_expense_amt": 0.0
    }
    
    categories_breakdown = {
        "income": {},
        "hpp": {},
        "opex": {}
    }
    daily_trends = {}
    raw_mutations = []
    
    if supabase:
        try:
            # 1. Tentukan Periode Tanggal
            now = datetime.now()
            target_month = int(month) if month else now.month
            target_year = int(year) if year else now.year

            # Cari tau tanggal terakhir di bulan tersebut (Misal: 28, 30, atau 31)
            last_day = calendar.monthrange(target_year, target_month)[1]

            # Format ke bentuk rentang waktu (Awal bulan sampai Akhir bulan)
            start_date = f"{target_year}-{target_month:02d}-01T00:00:00"
            end_date = f"{target_year}-{target_month:02d}-{last_day}T23:59:59"

            # 2. Tarik Data menggunakan GTE (>=) dan LTE (<=) agar PostgreSQL tidak error
            res_mut = supabase.table("finance_mutations").select(
                "id, amount, transaction_type, created_at, description, finance_categories(category_name, type), finance_accounts(bank_name)"
            ).gte("created_at", start_date).lte("created_at", end_date).order("created_at", desc=False).execute()
            
            raw_mutations = res_mut.data or []
            
            # 3. PROSES KALKULASI
            for m in raw_mutations:
                cat_info = m.get("finance_categories") or {}
                raw_cat_name = cat_info.get("category_name", "Tanpa Kategori")
                cat_name = str(raw_cat_name).lower()
                
                amt = float(m.get("amount", 0))
                trx_date = m.get("created_at", "").split("T")[0] # Ambil YYYY-MM-DD
                
                if trx_date not in daily_trends:
                    daily_trends[trx_date] = {"in": 0.0, "out": 0.0}
                
                if m.get("transaction_type") == "IN":
                    report_data["total_revenue"] += amt
                    report_data["total_trx_in"] += 1
                    daily_trends[trx_date]["in"] += amt
                    categories_breakdown["income"][raw_cat_name] = categories_breakdown["income"].get(raw_cat_name, 0) + amt

                elif m.get("transaction_type") == "OUT":
                    report_data["total_trx_out"] += 1
                    daily_trends[trx_date]["out"] += amt
                    
                    # Identifikasi HPP (Logic Original Lu)
                    is_hpp = any(keyword in cat_name for keyword in ["stok", "belanja", "jastip", "ongkir", "biang", "botol", "lakban"])
                    
                    if is_hpp:
                        report_data["total_hpp"] += amt
                        categories_breakdown["hpp"][raw_cat_name] = categories_breakdown["hpp"].get(raw_cat_name, 0) + amt
                    else:
                        report_data["total_opex"] += amt
                        categories_breakdown["opex"][raw_cat_name] = categories_breakdown["opex"].get(raw_cat_name, 0) + amt
                        
                        # Deteksi Beban Operasional Terbesar
                        if categories_breakdown["opex"][raw_cat_name] > report_data["biggest_expense_amt"]:
                            report_data["biggest_expense_amt"] = categories_breakdown["opex"][raw_cat_name]
                            report_data["biggest_expense_cat"] = raw_cat_name

            # 4. FINALISASI DATA
            report_data["gross_profit"] = report_data["total_revenue"] - report_data["total_hpp"]
            report_data["net_profit"] = report_data["gross_profit"] - report_data["total_opex"]
            
            if report_data["total_revenue"] > 0:
                report_data["margin"] = round((report_data["net_profit"] / report_data["total_revenue"]) * 100, 2)
            
            active_days = len(daily_trends) if len(daily_trends) > 0 else 1
            report_data["avg_revenue_per_day"] = round(report_data["total_revenue"] / active_days, 2)

            logger.info(f"📊 [FINANCE REPORT] Kalkulasi sukses! Omset: {report_data['total_revenue']}")

        except Exception as e:
            logger.error(f"❌ [FINANCE REPORT ERROR]: {e}")

    return render_admin_template(
        request, 
        "admin/finance_report.html", 
        report=report_data,
        breakdown=categories_breakdown,
        daily_trends=daily_trends,
        mutations=raw_mutations,
        period_text=f"{target_month:02d}/{target_year}"
    )
    
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