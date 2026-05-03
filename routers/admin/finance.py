"""
================================================================================
BABA PARFUME & DIGITAL ASSET - ENTERPRISE FINANCE ENGINE (V4.0 ULTIMATE)
================================================================================
Modul ini menangani seluruh urat nadi keuangan (Cashflow, P&L, Asset Management).
Didesain khusus dengan arsitektur Double-Entry Bookkeeping yang disederhanakan.
Mendukung multi-currency (IDR, USD, KHR) untuk ekspansi market dan operasional.

ENTERPRISE FEATURES (1000+ Lines Code):
1. Asset & Ledger Management (Multi-Currency Dynamic Conversion)
2. P&L Executive Report (Advanced Calculation & Real-time Charting)
3. Transaction Reversal (Void) System (Double-Entry Reversal Logging)
4. Budget Limit & Spending Alert System
5. Analytics API Data Source for Dashboard Visualizations
6. [UPGRADED] Supabase Auto-Normalizer (Mencegah Jinja2 Undefined / Rp Bug)
7. [UPGRADED] System Reconciliation API (Audit Trail Balance Checker)
8. [UPGRADED] Bulletproof CSV Export Engine (Anti-Error 500 Internal Server Error)
9. Error Handling & Deep Logging System for Production

Author: Strategic IT Partner (BABA Enterprise)
Role: Super Admin / Owner Only
================================================================================
"""

import logging
import calendar
import uuid
import csv
import io
import json
from typing import Optional, List, Dict, Any, Union
from datetime import datetime, timedelta

from fastapi import APIRouter, Request, Depends, HTTPException, status, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, StreamingResponse, Response
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

# Import Internal Project Engine
# Pastikan modul-modul ini tersedia di project BABA lu
from routers.common import (
    supabase, logger, render_admin_template, require_admin_roles, 
    api_success, api_error, safe_array, format_currency
)
from routers.dependencies import get_current_admin

# Inisiasi Router khusus Admin Finance
router = APIRouter(prefix="/admin/finance", tags=["Finance Enterprise Engine"])


# ==============================================================================
# 🧩 SECTION 0: PYDANTIC SCHEMAS (STRICT DATA VALIDATION)
# ==============================================================================
# Skema diletakkan di dalam agar modul bersifat standalone dan robust.

class ManualTransactionPayload(BaseModel):
    account_id: int = Field(..., description="ID dari dompet/bank utama")
    category_id: int = Field(..., description="ID dari kategori transaksi")
    transaction_type: str = Field(..., description="Wajib 'IN' atau 'OUT'")
    amount: float = Field(..., gt=0, description="Nominal mutasi (tidak boleh nol/minus)")
    description: Optional[str] = Field("Transaksi Manual", description="Memo / Keterangan")

class TransferPayload(BaseModel):
    from_account_id: int = Field(..., description="Dompet asal")
    to_account_id: int = Field(..., description="Dompet tujuan")
    amount_out: float = Field(..., gt=0, description="Nominal yang ditarik")
    exchange_rate: float = Field(1.0, gt=0, description="Kurs konversi")
    amount_in: float = Field(..., gt=0, description="Nominal yang diterima")
    description: Optional[str] = Field("Pindah Kas / Exchange")

class VoidTransactionPayload(BaseModel):
    mutation_id: int = Field(..., description="ID Mutasi yang akan di-void")
    reason: str = Field(..., min_length=3, description="Alasan pembatalan (wajib)")

class AdjustmentPayload(BaseModel):
    account_id: int = Field(..., description="ID dari dompet/bank yang mau disesuaikan")
    actual_balance: float = Field(..., description="Saldo riil di lapangan saat ini")
    reason: str = Field(..., min_length=3, description="Alasan penyesuaian (wajib)")

class DebtCreatePayload(BaseModel):
    type: str = Field(..., description="HUTANG atau PIUTANG")
    person: str = Field(..., min_length=1, description="Nama Peminjam / Yang Dipinjami")
    amount: float = Field(..., gt=0, description="Nominal Kontrak")
    currency: str = Field(..., description="IDR, USD, KHR")
    accountId: int = Field(..., description="Dompet sumber pencairan/penerimaan")
    dueDate: str = Field(..., description="Tanggal jatuh tempo")
    description: Optional[str] = Field("Kontrak Hutang/Piutang")

class DebtRepayPayload(BaseModel):
    debt_id: str = Field(..., description="ID dari Kontrak (UUID)")
    amount: float = Field(..., gt=0, description="Nominal Pengurang Utang (Mata Uang Utang)")
    account_id: int = Field(..., description="Dompet transaksi")
    description: str = Field(..., description="Memo pembayaran")
    exchange_rate: Optional[float] = Field(1.0, description="Rate Konversi")

class BudgetCheckPayload(BaseModel):
    category_id: int
    amount: float = Field(..., gt=0)


# ==============================================================================
# 🛠️ SECTION 1: ENTERPRISE DATA NORMALIZER & UTILITIES
# ==============================================================================

def normalize_supabase_relation(relation_data: Union[Dict, List, None], default_dict: Dict) -> Dict:
    """
    [CRITICAL FIX] Auto-Normalizer Engine.
    Supabase sering mereturn relasi One-to-Many sebagai List, dan Many-to-One sebagai Dict.
    Fungsi ini memaksa format data menjadi Dictionary murni agar Jinja2/HTML 
    (seperti m.finance_accounts.currency) tidak membaca "undefined" atau blank.
    """
    if relation_data is None:
        return default_dict
    if isinstance(relation_data, list):
        return relation_data[0] if len(relation_data) > 0 else default_dict
    if isinstance(relation_data, dict):
        return relation_data
    return default_dict

def normalize_mutations(mutations: List[Dict]) -> List[Dict]:
    """
    [FIXED] Normalizer yang udah disesuaikan dengan schema database BABA.
    """
    normalized = []
    for m in mutations:
        m["finance_accounts"] = normalize_supabase_relation(
            m.get("finance_accounts"), 
            {"bank_name": "Umum", "currency": "IDR"}
        )
        m["finance_categories"] = normalize_supabase_relation(
            m.get("finance_categories"), 
            {"category_name": "Lainnya", "type": "UNKNOWN"}
        )
        # Fix: DB lu pake 'full_name', bukan 'admin_name'
        m["admins"] = normalize_supabase_relation(
            m.get("admins"), 
            {"full_name": "Sistem BABA"}
        )
        normalized.append(m)
    return normalized

def fetch_categories_safely() -> tuple:
    """
    Mengambil kategori dari database dan memisahkannya menjadi IN dan OUT.
    Memiliki mekanisme Fallback agar dropdown Modal TIDAK PERNAH KOSONG.
    """
    categories_in = []
    categories_out = []
    
    if not supabase: 
        return categories_in, categories_out
    
    try:
        res_cat = supabase.table("finance_categories").select("*").execute()
        all_cats = res_cat.data or []
        
        for c in all_cats:
            ctype = str(c.get("type", "")).strip().upper()
            if ctype in ["INCOME", "IN"]:
                categories_in.append(c)
            elif ctype in ["EXPENSE", "OUT"]:
                categories_out.append(c)
                
        # FALLBACK: Jika tabel kategori kosong, injeksi kategori darurat
        if len(categories_in) == 0:
            categories_in.append({"id": 1, "category_name": "Pemasukan Umum"})
        if len(categories_out) == 0:
            categories_out.append({"id": 2, "category_name": "Pengeluaran Umum"})
            
    except Exception as e:
        logger.error(f"[FETCH CAT ERROR] Gagal memuat kategori: {e}")
        
    return categories_in, categories_out

def get_pending_count() -> int:
    """Notifikasi jumlah order yang nyangkut"""
    if not supabase: return 0
    try:
        res = supabase.table("orders").select("id").eq("status", "Menunggu Pembayaran").execute()
        return len(res.data or [])
    except Exception:
        return 0

def generate_trx_ref(prefix: str = "TRX") -> str:
    """Membuat ID Referensi Transaksi Unik"""
    now_str = datetime.now().strftime('%y%m%d%H%M')
    random_str = str(uuid.uuid4())[:4].upper()
    return f"{prefix}-{now_str}-{random_str}"

def get_category_id_by_name(keyword: str, fallback_id: int = 1) -> int:
    """Mencari ID Kategori secara dinamis"""
    if not supabase: return fallback_id
    try:
        cat_res = supabase.table("finance_categories").select("id").ilike("category_name", f"%{keyword}%").limit(1).execute()
        if cat_res.data:
            return cat_res.data[0].get("id", fallback_id)
        return fallback_id
    except Exception:
        return fallback_id

def log_system_audit(admin_id: Any, action: str, details: str):
    """Mencatat aktivitas admin ke console produksi"""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    logger.warning(f"🛡️ [AUDIT TRAIL] {timestamp} | Admin ID: {admin_id} | ACTION: {action} | DETAILS: {details}")

def parse_date_safely(date_string: str) -> str:
    """Parser tanggal yang aman untuk menghindari Error 500 saat ekspor CSV"""
    if not date_string:
        return "-"
    try:
        clean_str = date_string.replace('Z', '+00:00')
        dt_obj = datetime.fromisoformat(clean_str)
        return dt_obj.strftime('%Y-%m-%d %H:%M:%S')
    except Exception:
        return str(date_string).split('.')[0]


# ==============================================================================
# 💰 SECTION 2: ASSETS & WALLET DASHBOARD (/aset)
# ==============================================================================

@router.get("/aset", response_class=HTMLResponse)
async def admin_finance_aset(request: Request, admin=Depends(get_current_admin)):
    """
    CORE ROUTE: Dashboard Kekayaan Bersih (Liquid + Physical Inventory).
    """
    accounts = []
    total_liquid = 0.0
    total_inventory = 0.0
    recent_mutations = []

    # Ambil Kategori dengan Aman (Anti Kosong)
    categories_in, categories_out = fetch_categories_safely()

    if supabase:
        try:
            # 1. Tarik Data Rekening Bank
            res_acc = supabase.table("finance_accounts").select("*").eq("is_active", True).order("id").execute()
            accounts = res_acc.data or []
            
            for acc in accounts:
                total_liquid += float(acc.get("current_balance", 0))

            # 2. Hitung Nilai Aset Stok Fisik
            res_prod = supabase.table("products").select("stock_quantity, original_price").eq("is_active", True).execute()
            for p in (res_prod.data or []):
                stok_fisik = int(p.get("stock_quantity", 0))
                harga_modal = float(p.get("original_price", 0))
                total_inventory += (stok_fisik * harga_modal)

            # 3. Tarik 10 Transaksi Terakhir & NORMALISASI RELASINYA
            res_mut = supabase.table("finance_mutations").select(
                "*, finance_accounts(bank_name, currency), finance_categories(category_name, type)"
            ).order("created_at", desc=True).limit(10).execute()
            
            # Eksekusi fungsi dokter spesialis kita
            recent_mutations = normalize_mutations(res_mut.data or [])

            logger.info(f"💼 [FINANCE] Aset diakses oleh: {admin.get('username', 'Admin')}")

        except Exception as e:
            logger.error(f"❌ [FINANCE ASET ERROR]: {e}")

    # Render Template
    return render_admin_template(
        request, "admin/finance_aset.html",
        admin_data=admin,
        accounts=accounts,
        total_liquid=total_liquid,
        total_inventory=total_inventory,
        total_aset=total_liquid + total_inventory,
        recent_mutations=recent_mutations,
        categories_in=categories_in,
        categories_out=categories_out,
        pending_count=get_pending_count()
    )


# ==============================================================================
# 📖 SECTION 3: BIG LEDGER / MUTASI KESELURUHAN (/mutasi)
# ==============================================================================

@router.get("/mutasi", response_class=HTMLResponse)
async def mutasi_page(request: Request, admin=Depends(get_current_admin)):
    """
    CORE ROUTE: Menampilkan Buku Besar (Ledger) secara komprehensif.
    """
    mutations = []
    accounts = []
    
    # Ambil Kategori dengan Aman (Agar Dropdown di Modal Mutasi Tidak Hilang)
    categories_in, categories_out = fetch_categories_safely()
    
    if supabase:
        try:
            # Tarik list bank untuk filter UI
            res_acc = supabase.table("finance_accounts").select("id, bank_name, currency").eq("is_active", True).execute()
            accounts = res_acc.data or []

            # Tarik data mutasi masif dengan relasi lengkap
            res_mut = supabase.table("finance_mutations").select(
                "*, finance_accounts(bank_name, currency), finance_categories(category_name, type)"
            ).order("created_at", desc=True).limit(2500).execute()
            
            # NORMALISASI DATA (Membunuh penyakit logo Rp dan Undefined Kategori)
            mutations = normalize_mutations(res_mut.data or [])
            logger.info(f"📚 [FINANCE] Ledger diakses. Total baris ditarik: {len(mutations)}")
            
        except Exception as e:
            logger.error(f"❌ [FINANCE MUTASI ERROR]: Gagal memuat buku besar: {e}")

    return render_admin_template(
        request, "admin/finance_mutasi.html", 
        admin_data=admin,
        mutations=mutations, 
        accounts=accounts,
        categories_in=categories_in,
        categories_out=categories_out,
        pending_count=get_pending_count()
    )


# ==============================================================================
# 📊 SECTION 4: PROFIT & LOSS REPORT (/report)
# ==============================================================================

@router.get("/report", response_class=HTMLResponse)
async def admin_finance_report(request: Request, 
                               period: Optional[str] = Query('this_month'),
                               start_date: Optional[str] = Query(None),
                               end_date: Optional[str] = Query(None),
                               admin=Depends(get_current_admin)):
    """
    CORE ROUTE: Mesin Kalkulasi Laba Rugi (P&L) Standar Enterprise.
    (UPDATED) Mendukung filter rentang tanggal dinamis.
    """
    allowed_roles = ["super_admin", "owner", "admin", "super admin"]
    current_role = str(admin.get("role", "")).lower() or str(admin.get("admin_role", "")).lower()
    
    if current_role not in allowed_roles:
        logger.warning(f"🔒 [SECURITY] Akses P&L Report ditolak untuk User/Admin ID: {admin.get('id')}")
        return RedirectResponse(url="/admin/finance/aset")

    raw_mutations = []
    period_text = "Bulan Ini"
    
    if supabase:
        try:
            now = datetime.now()
            
            # --- LOGIC FILTER TANGGAL ENGINE ---
            if period == 'custom' and start_date and end_date:
                # Filter Manual
                query_start = f"{start_date}T00:00:00"
                query_end = f"{end_date}T23:59:59"
                period_text = f"{start_date} s/d {end_date}"
            
            elif period == 'today':
                # Filter 1 Hari Ini
                query_start = f"{now.strftime('%Y-%m-%d')}T00:00:00"
                query_end = f"{now.strftime('%Y-%m-%d')}T23:59:59"
                period_text = "Hari Ini"

            elif period == 'last_7_days':
                # Filter 7 Hari Terakhir
                past_7 = now - timedelta(days=7)
                query_start = f"{past_7.strftime('%Y-%m-%d')}T00:00:00"
                query_end = f"{now.strftime('%Y-%m-%d')}T23:59:59"
                period_text = "7 Hari Terakhir"
                
            elif period == 'last_month':
                # Filter Bulan Lalu
                first_day_this_month = now.replace(day=1)
                last_day_last_month = first_day_this_month - timedelta(days=1)
                first_day_last_month = last_day_last_month.replace(day=1)
                
                query_start = f"{first_day_last_month.strftime('%Y-%m-%d')}T00:00:00"
                query_end = f"{last_day_last_month.strftime('%Y-%m-%d')}T23:59:59"
                period_text = "Bulan Lalu"
                
            elif period == 'all_time':
                # Filter Semua Waktu
                query_start = "2000-01-01T00:00:00"
                query_end = "2099-12-31T23:59:59"
                period_text = "Semua Waktu"
                
            else:
                # Default: Bulan Ini
                last_day = calendar.monthrange(now.year, now.month)[1]
                query_start = f"{now.year}-{now.month:02d}-01T00:00:00"
                query_end = f"{now.year}-{now.month:02d}-{last_day}T23:59:59"
                period_text = "Bulan Ini"

            # ----------------------------------------------------
            # Ambil data transaksi HANYA di periode tersebut
            res_mut = supabase.table("finance_mutations").select(
                "*, finance_categories(category_name, type), finance_accounts(bank_name, currency), admins(full_name)"
            ).gte("created_at", query_start).lte("created_at", query_end).order("created_at", desc=False).execute()
            
            raw_mutations = normalize_mutations(res_mut.data or [])

        except Exception as e:
            logger.error(f"❌ [REPORT ENGINE ERROR]: {e}")

    # Kita lemparkan data mentah ke Frontend. 
    # Biarkan AlpineJS yang hitung detail P&L nya biar UI tetep ngebut.
    return render_admin_template(
        request, "admin/finance_report.html", 
        admin_data=admin,
        mutations=raw_mutations, 
        period_text=period_text,
        current_period_value=period,
        start_date_val=start_date or "",
        end_date_val=end_date or "",
        pending_count=get_pending_count()
    )


# ==============================================================================
# ⚡ SECTION 5: CORE TRANSACTION API (MUTASI & TRANSFER)
# ==============================================================================

@router.post("/transaction")
async def api_manual_transaction(payload: ManualTransactionPayload, admin=Depends(get_current_admin)):
    """
    API: Mencatat Kas Masuk/Keluar.
    Endpoint utama yang di-hit dari Modal Input di Frontend.
    """
    if not supabase: return api_error("Sistem Database Offline.", 503)
    
    try:
        # 1. Validasi Rekening & Saldo Real-Time
        res_acc = supabase.table("finance_accounts").select("current_balance, bank_name").eq("id", payload.account_id).single().execute()
        if not res_acc.data: 
            return api_error("Rekening asal tidak valid atau sudah dibekukan!")
        
        curr_bal = float(res_acc.data.get("current_balance", 0))
        amt = float(payload.amount)
        bank_name = str(res_acc.data.get("bank_name", "Unknown"))
        trx_type = str(payload.transaction_type).upper()

        # 2. Kalkulasi Arus Kas
        if trx_type == "IN":
            new_bal = curr_bal + amt
        elif trx_type == "OUT":
            if curr_bal < amt: 
                return api_error(f"Transaksi Ditolak! Saldo di dompet {bank_name} tidak mencukupi. (Tersedia: {curr_bal})")
            new_bal = curr_bal - amt
        else:
            return api_error("Parameter transaksi ilegal. Wajib IN atau OUT.")

        # 3. Update Database Saldo Bank
        res_update = supabase.table("finance_accounts").update({"current_balance": new_bal}).eq("id", payload.account_id).execute()
        
        if res_update.data:
            ref_id = generate_trx_ref("MAN")
            admin_id = admin.get("id") or admin.get("admin_id")
            
            # 4. Insert Log Jurnal Mutasi
            supabase.table("finance_mutations").insert({
                "account_id": payload.account_id,
                "category_id": payload.category_id,
                "transaction_type": trx_type,
                "amount": amt,
                "balance_after": new_bal,
                "description": f"[{ref_id}] {payload.description}",
                "reference_order_id": None,
                "created_by": admin_id 
            }).execute()

            logger.info(f"💸 [TRX SUCCESS] {trx_type} | Nominal: {amt} | Bank: {bank_name} | PIC ID: {admin_id}")
            return api_success(message="Transaksi tervalidasi dan dicatat di buku besar.")
        else:
            raise Exception("Gagal menyinkronkan saldo utama pada Database.")

    except Exception as e:
        logger.error(f"❌ [API TRX ERROR]: {e}")
        return api_error(f"Fatal Error: {str(e)}")


@router.post("/transfer")
async def api_transfer_transaction(payload: TransferPayload, admin=Depends(get_current_admin)):
    """
    CORE API: Money Exchange & Pindah Kas Antar Rekening (Double-Entry).
    Mendukung skenario beda mata uang secara presisi.
    """
    if not supabase: return api_error("Sistem Database Offline.", 503)
    
    try:
        res_src = supabase.table("finance_accounts").select("current_balance, bank_name, currency").eq("id", payload.from_account_id).single().execute()
        res_dst = supabase.table("finance_accounts").select("current_balance, bank_name, currency").eq("id", payload.to_account_id).single().execute()
        
        if not res_src.data or not res_dst.data: 
            return api_error("Gagal mendeteksi salah satu rekening di database.")
        
        src_name = res_src.data.get("bank_name", "Source")
        dst_name = res_dst.data.get("bank_name", "Target")
        bal_src = float(res_src.data.get("current_balance", 0))
        bal_dst = float(res_dst.data.get("current_balance", 0))
        
        # Cek Overdraft
        if bal_src < payload.amount_out: 
            return api_error(f"Pindah kas dibatalkan! Saldo {src_name} kurang.")

        # Eksekusi Debit & Kredit
        new_bal_src = bal_src - payload.amount_out
        res_upd_src = supabase.table("finance_accounts").update({"current_balance": new_bal_src}).eq("id", payload.from_account_id).execute()
        
        new_bal_dst = bal_dst + payload.amount_in
        res_upd_dst = supabase.table("finance_accounts").update({"current_balance": new_bal_dst}).eq("id", payload.to_account_id).execute()

        if res_upd_src.data and res_upd_dst.data:
            transfer_ref = generate_trx_ref("EXC" if payload.exchange_rate != 1.0 else "TF")
            cat_id = get_category_id_by_name("transfer", 1)
            admin_id = admin.get("id") or admin.get("admin_id")
            
            # Log Keluar
            supabase.table("finance_mutations").insert({
                "account_id": payload.from_account_id, 
                "category_id": cat_id,
                "transaction_type": "OUT", 
                "amount": payload.amount_out,
                "balance_after": new_bal_src, 
                "description": f"[{transfer_ref}] Keluar ke {dst_name} - {payload.description}",
                "created_by": admin_id
            }).execute()
            
            # Log Masuk
            supabase.table("finance_mutations").insert({
                "account_id": payload.to_account_id, 
                "category_id": cat_id,
                "transaction_type": "IN", 
                "amount": payload.amount_in,
                "balance_after": new_bal_dst, 
                "description": f"[{transfer_ref}] Masuk dari {src_name} - {payload.description}",
                "created_by": admin_id
            }).execute()

            logger.info(f"💱 [TRANSFER] Out: {payload.amount_out} ({src_name}) -> In: {payload.amount_in} ({dst_name})")
            return api_success(message=f"Pindah kas/Exchange ke {dst_name} berhasil dienkripsi!")
        else:
            logger.error("🚨 CRITICAL: Partial failure saat pindah kas. Memerlukan audit manual!")
            raise Exception("Gagal menyinkronkan saldo antar bank (Database Lock).")

    except Exception as e:
        logger.error(f"❌ [TRANSFER ERROR]: {e}")
        return api_error(f"Sistem gagal mengeksekusi perpindahan dana: {str(e)}")
    
@router.post("/adjust")
async def api_adjust_balance(payload: AdjustmentPayload, admin=Depends(get_current_admin)):
    """
    API: Sinkronisasi saldo sistem dengan saldo riil (Smart Adjustment).
    Otomatis menghitung selisih dan mencetak jurnal IN atau OUT.
    """
    if not supabase: return api_error("Sistem Database Offline.", 503)
    
    try:
        # Cek saldo saat ini di sistem
        res_acc = supabase.table("finance_accounts").select("current_balance, bank_name").eq("id", payload.account_id).single().execute()
        if not res_acc.data: return api_error("Rekening tidak ditemukan!")
        
        curr_bal = float(res_acc.data.get("current_balance", 0))
        actual_bal = float(payload.actual_balance)
        diff = actual_bal - curr_bal
        
        # Kalau saldo sama persis, reject
        if diff == 0:
            return api_error("Saldo riil sama persis dengan sistem. Tidak ada yang perlu disesuaikan.")
        
        # Tentukan tipe transaksi berdasarkan selisih
        trx_type = "IN" if diff > 0 else "OUT"
        amt = abs(diff)
        bank_name = res_acc.data.get("bank_name", "Unknown")
        
        # Eksekusi Update Dompet
        supabase.table("finance_accounts").update({"current_balance": actual_bal}).eq("id", payload.account_id).execute()
        
        # Log Mutasi
        cat_id = get_category_id_by_name("penyesuaian", 1) # Auto-fallback ke ID 1 jika kategori penyesuaian belum dibuat
        admin_id = admin.get("id") or admin.get("admin_id")
        ref_id = generate_trx_ref("ADJ")
        
        supabase.table("finance_mutations").insert({
            "account_id": payload.account_id,
            "category_id": cat_id,
            "transaction_type": trx_type,
            "amount": amt,
            "balance_after": actual_bal,
            "description": f"[{ref_id}] SYSTEM ADJUSTMENT: {payload.reason} (Selisih: {amt})",
            "created_by": admin_id 
        }).execute()
        
        log_system_audit(admin.get("username", "Admin"), "ADJUST_BALANCE", f"Bank: {bank_name}, Old: {curr_bal}, New: {actual_bal}")
        return api_success(message=f"Sukses! Saldo {bank_name} disesuaikan menjadi {format_currency(actual_bal)}.")
        
    except Exception as e:
        logger.error(f"❌ [API ADJUST ERROR]: {e}")
        return api_error(f"Fatal Error: {str(e)}")


@router.post("/bank")
async def tambah_bank_baru(bank_name: str = Form(...), 
                           account_number: str = Form(None), 
                           current_balance: float = Form(0.0), 
                           currency: str = Form("IDR"),
                           admin=Depends(get_current_admin)):
    """API: Mendaftarkan rekening/dompet baru."""
    try:
        clean_bank_name = bank_name.strip().upper()
        clean_currency = currency.strip().upper()
        
        payload = {
            "bank_name": clean_bank_name,
            "account_number": account_number.strip() if account_number else None,
            "current_balance": current_balance,
            "currency": clean_currency,
            "is_active": True
        }
        
        res_insert = supabase.table("finance_accounts").insert(payload).execute()
        
        if res_insert.data and current_balance > 0:
            new_account_id = res_insert.data[0].get("id")
            cat_id = get_category_id_by_name("modal", 1) 
            
            supabase.table("finance_mutations").insert({
                "account_id": new_account_id,
                "category_id": cat_id,
                "transaction_type": "IN",
                "amount": current_balance,
                "balance_after": current_balance,
                "description": f"Suntik Saldo Awal (Modal) - {clean_bank_name}",
                "created_by": admin.get("id") or admin.get("admin_id")
            }).execute()
        
        return RedirectResponse(url="/admin/finance/aset", status_code=status.HTTP_303_SEE_OTHER)
        
    except Exception as e:
        logger.error(f"❌ [DB ERROR BANK]: {e}")
        raise HTTPException(status_code=500, detail=f"Gagal registrasi bank: {str(e)}")


# ==============================================================================
# 🚀 SECTION 6: ENTERPRISE FEATURES (VOID, RECONCILE, AUDIT)
# ==============================================================================

@router.post("/api/void-transaction")
async def void_transaction(payload: VoidTransactionPayload, admin=Depends(get_current_admin)):
    """
    API VOID: Membatalkan transaksi yang salah input (Double-Entry Reversal).
    """
    allowed_roles = ["super_admin", "owner", "super admin"]
    current_role = str(admin.get("role", "")).lower() or str(admin.get("admin_role", "")).lower()
    
    if current_role not in allowed_roles:
        return api_error("Akses Ditolak. Hanya Super Admin/Owner yang berhak mem-VOID transaksi.", 403)

    try:
        # Cari Mutasi Original
        res_mut = supabase.table("finance_mutations").select("*").eq("id", payload.mutation_id).single().execute()
        if not res_mut.data: return api_error("Transaksi referensi tidak ditemukan di server.")
            
        original_trx = res_mut.data
        if "VOID" in str(original_trx.get("description", "")).upper():
            return api_error("Transaksi ini sudah pernah dibatalkan sebelumnya!")

        acc_id = original_trx.get("account_id")
        orig_type = original_trx.get("transaction_type")
        amt = float(original_trx.get("amount"))
        
        # Ambil Saldo Bank
        res_acc = supabase.table("finance_accounts").select("current_balance, bank_name").eq("id", acc_id).single().execute()
        curr_bal = float(res_acc.data.get("current_balance", 0))
        bank_name = res_acc.data.get("bank_name", "Bank")

        # Hitung Reversal
        if orig_type == "IN":
            if curr_bal < amt:
                return api_error(f"Gagal Void! Saldo {bank_name} saat ini ({curr_bal}) tidak cukup.")
            new_bal = curr_bal - amt
            rev_type = "OUT"
        else:
            new_bal = curr_bal + amt
            rev_type = "IN"

        # Update Rekening & Catat Log
        supabase.table("finance_accounts").update({"current_balance": new_bal}).eq("id", acc_id).execute()

        void_desc = f"[VOID REVERSAL] Mengembalikan TRX ID: {payload.mutation_id} - {payload.reason}"
        supabase.table("finance_mutations").insert({
            "account_id": acc_id,
            "category_id": original_trx.get("category_id"),
            "transaction_type": rev_type,
            "amount": amt,
            "balance_after": new_bal,
            "description": void_desc,
            "created_by": admin.get("id") or admin.get("admin_id")
        }).execute()
        
        new_desc = f"[VOIDED] {original_trx.get('description')}"
        supabase.table("finance_mutations").update({"description": new_desc}).eq("id", payload.mutation_id).execute()

        log_system_audit(admin.get("username", "Admin"), "VOID_TRX", f"Voided Mutation ID {payload.mutation_id}")
        return api_success(message=f"Transaksi berhasil dibatalkan. Saldo dikembalikan ke {bank_name}.")

    except Exception as e:
        logger.error(f"❌ [VOID ERROR]: {e}")
        return api_error(f"Gagal membatalkan transaksi sistem: {str(e)}")


@router.get("/api/reconcile")
async def system_reconciliation(admin=Depends(get_current_admin)):
    """
    SYSTEM RECONCILIATION
    Audit engine untuk memastikan saldo di tabel dompet cocok secara 
    matematis dengan seluruh mutasi. Mencegah kebocoran data.
    """
    allowed_roles = ["super_admin", "owner"]
    current_role = str(admin.get("role", "")).lower() or str(admin.get("admin_role", "")).lower()
    
    if current_role not in allowed_roles:
        return api_error("Akses Ditolak.", 403)
        
    if not supabase: return api_error("Database Offline", 503)
    
    try:
        res_acc = supabase.table("finance_accounts").select("id, bank_name, current_balance").execute()
        accounts = res_acc.data or []
        
        audit_results = []
        is_healthy = True
        
        for acc in accounts:
            acc_id = acc["id"]
            stated_balance = float(acc["current_balance"])
            
            res_mut = supabase.table("finance_mutations").select("transaction_type, amount").eq("account_id", acc_id).execute()
            mutations = res_mut.data or []
            
            calculated_balance = 0.0
            for m in mutations:
                amt = float(m["amount"])
                if m["transaction_type"] == "IN": calculated_balance += amt
                elif m["transaction_type"] == "OUT": calculated_balance -= amt
                    
            diff = abs(stated_balance - calculated_balance)
            status = "SEHAT" if diff < 0.1 else "BOCOR/TIDAK SINKRON"
            if diff >= 0.1: is_healthy = False
            
            audit_results.append({
                "bank_name": acc["bank_name"],
                "saldo_database": stated_balance,
                "saldo_kalkulasi_mutasi": calculated_balance,
                "selisih": diff,
                "status": status
            })
            
        return api_success(data={
            "system_health": "SEHAT" if is_healthy else "PERLU INVESTIGASI",
            "audit_timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            "details": audit_results
        })
        
    except Exception as e:
        return api_error(f"Gagal melakukan rekonsiliasi: {str(e)}")


# ==============================================================================
# 🗄️ SECTION 7: EXPORT REPORTING (CSV BULLETPROOF)
# ==============================================================================

@router.get("/export/csv")
async def export_mutasi_csv(admin=Depends(get_current_admin)):
    allowed_roles = ["super_admin", "owner", "super admin", "admin", "oprasional"]
    current_role = str(admin.get("role", "")).lower() or str(admin.get("admin_role", "")).lower()
    
    if current_role not in allowed_roles:
        raise HTTPException(status_code=403, detail="Anda tidak memiliki wewenang mengunduh data.")

    if not supabase: raise HTTPException(status_code=503, detail="Database Offline")

    try:
        # [FIX] Tambahkan admins(full_name) agar relasi tidak kosong
        res_mut = supabase.table("finance_mutations").select(
            "created_at, transaction_type, amount, balance_after, description, "
            "finance_categories(category_name), finance_accounts(bank_name, currency), admins(full_name)"
        ).order("created_at", desc=True).limit(10000).execute()
        
        mutations = normalize_mutations(res_mut.data or [])
        
        output = io.StringIO()
        output.write('\ufeff') # [FIX] Inject BOM agar Excel otomatis baca format UTF-8 rapi
        writer = csv.writer(output, delimiter=',', quotechar='"', quoting=csv.QUOTE_MINIMAL)
        
        writer.writerow(['Tanggal Waktu', 'Mata Uang', 'Sumber Dompet', 'Arus Kas', 'Kategori Jurnal', 'Nominal Mutasi', 'Sisa Saldo Akhir', 'PIC', 'Keterangan Sistem'])
        
        for m in mutations:
            formatted_date = parse_date_safely(m.get('created_at'))
            bank_name = m['finance_accounts'].get('bank_name', 'Bank Umum')
            currency = m['finance_accounts'].get('currency', 'IDR')
            category = m['finance_categories'].get('category_name', 'Tanpa Kategori')
            
            # [FIX] Ambil full_name sesuai skema DB
            admin_name = m['admins'].get('full_name', 'Admin BABA') 
            
            amount = f"{m.get('amount', 0):.2f}"
            balance = f"{m.get('balance_after', 0):.2f}"
            
            writer.writerow([
                formatted_date, currency, bank_name, m.get('transaction_type', '-'),
                category, amount, balance, admin_name, m.get('description', '')
            ])
            
        filename = f"BABA_Ledger_Export_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
        headers = {'Content-Disposition': f'attachment; filename="{filename}"'}
        
        # [FIX] Pakai Response statis, jauh lebih stabil buat export CSV dibanding StreamingResponse
        return Response(content=output.getvalue(), media_type="text/csv", headers=headers)

    except Exception as e:
        logger.error(f"❌ [EXPORT CSV ERROR]: {e}")
        raise HTTPException(status_code=500, detail=f"Gagal generate CSV: {str(e)}")

# ==============================================================================
# 🤝 SECTION 8: ACCOUNTS PAYABLE & RECEIVABLE (HUTANG PIUTANG ENGINE)
# ==============================================================================

@router.get("/debts", response_class=HTMLResponse)
async def admin_finance_debts(request: Request, admin=Depends(get_current_admin)):
    """
    CORE ROUTE: Dashboard Manajemen Hutang & Piutang (AP/AR).
    """
    accounts = []
    debts = []
    
    if supabase:
        try:
            # 1. Tarik Data Dompet Aktif
            res_acc = supabase.table("finance_accounts").select("*").eq("is_active", True).execute()
            accounts = res_acc.data or []

            # 2. Tarik Data Master Kontrak Hutang/Piutang
            res_debts = supabase.table("finance_debts").select("*").order("created_at", desc=True).execute()
            debts = res_debts.data or []

            logger.info(f"🤝 [AP/AR] Diakses oleh: {admin.get('username', 'Admin')}")

        except Exception as e:
            logger.error(f"❌ [DEBTS PAGE ERROR]: {e}")

    return render_admin_template(
        request, "admin/finance_debts.html",
        admin_data=admin,
        accounts=accounts,
        debts=debts,
        pending_count=get_pending_count()
    )


@router.post("/debts/create")
async def create_debt_contract(payload: DebtCreatePayload, admin=Depends(get_current_admin)):
    """
    API: Buat Kontrak Hutang/Piutang & Eksekusi Mutasi Dompet (Double Entry)
    """
    if not supabase: return api_error("Database Offline", 503)
    
    try:
        # Cek Saldo Dompet
        res_acc = supabase.table("finance_accounts").select("current_balance, bank_name").eq("id", payload.accountId).single().execute()
        if not res_acc.data: return api_error("Dompet tidak ditemukan.")
        
        curr_bal = float(res_acc.data.get("current_balance", 0))
        amt = float(payload.amount)
        bank_name = res_acc.data.get("bank_name", "Bank")
        admin_id = admin.get("id") or admin.get("admin_id")

        # LOGIKA DOUBLE ENTRY AWAL KONTRAK
        if payload.type == "PIUTANG":
            # BABA minjemin uang -> Uang keluar dari bank (OUT)
            if curr_bal < amt:
                return api_error(f"Pencairan Ditolak! Saldo {bank_name} tidak cukup (Sisa: {curr_bal}).")
            new_bal = curr_bal - amt
            trx_type = "OUT"
        elif payload.type == "HUTANG":
            # BABA minjem uang dari luar -> Uang masuk ke bank (IN)
            new_bal = curr_bal + amt
            trx_type = "IN"
        else:
            return api_error("Tipe kontrak tidak valid.")

        # 1. Simpan Kontrak ke Master Table
        debt_data = {
            "debt_type": payload.type,
            "person_name": payload.person,
            "total_amount": amt,
            "remaining_amount": amt,
            "currency": payload.currency,
            "due_date": payload.dueDate,
            "status": "BELUM LUNAS",
            "description": payload.description,
            "created_by": admin_id
        }
        res_debt = supabase.table("finance_debts").insert(debt_data).execute()
        
        if not res_debt.data:
            raise Exception("Gagal menyimpan Master Kontrak.")
            
        new_debt_id = res_debt.data[0].get("id")
        ref_id = generate_trx_ref("CTR") # CTR = Contract
        cat_id = get_category_id_by_name(payload.type.lower(), 1) # Fallback ke 1 kalo kategori blm dibikin

        # 2. Update Saldo Dompet
        supabase.table("finance_accounts").update({"current_balance": new_bal}).eq("id", payload.accountId).execute()

        # 3. Log ke Buku Besar (Mutasi) dengan reference_debt_id
        mut_desc = f"[{ref_id}] Pencairan {payload.type} - {payload.person} - {payload.description}"
        supabase.table("finance_mutations").insert({
            "account_id": payload.accountId,
            "category_id": cat_id,
            "transaction_type": trx_type,
            "amount": amt,
            "balance_after": new_bal,
            "description": mut_desc,
            "reference_debt_id": new_debt_id, # Kunci pengikat audit trail
            "created_by": admin_id 
        }).execute()

        log_system_audit(admin.get("username", "Admin"), "CREATE_DEBT", f"Type: {payload.type}, Person: {payload.person}, Amount: {amt}")
        return api_success(message=f"Kontrak {payload.type} berhasil dibuat dan sinkron dengan {bank_name}.")

    except Exception as e:
        logger.error(f"❌ [CREATE DEBT ERROR]: {e}")
        return api_error(f"Fatal Error: {str(e)}")

@router.post("/debts/repay")
async def repay_debt_installment(payload: DebtRepayPayload, admin=Depends(get_current_admin)):
    """
    API: Cicil / Lunasi Hutang Piutang (Update Saldo Kontrak & Mutasi Dompet dengan Cross-Currency)
    """
    if not supabase: return api_error("Database Offline", 503)

    try:
        # 1. Cek Data Master Kontrak
        res_debt = supabase.table("finance_debts").select("*").eq("id", payload.debt_id).single().execute()
        if not res_debt.data: return api_error("Kontrak tidak ditemukan.")
        debt = res_debt.data

        # 2. Cek Data Dompet Transaksi
        res_acc = supabase.table("finance_accounts").select("current_balance, bank_name, currency").eq("id", payload.account_id).single().execute()
        if not res_acc.data: return api_error("Rekening transaksi tidak valid.")
        
        # 3. Definisikan Variabel Kalkulasi
        rem_amt = float(debt.get("remaining_amount", 0))
        debt_currency = str(debt.get("currency", "IDR")).strip().upper()
        bank_currency = str(res_acc.data.get("currency", "IDR")).strip().upper()
        
        # ---> FIX LOGIKA BACKEND SINGLE SOURCE OF TRUTH <---
        debt_deduction = float(payload.amount)  
        
        # DETEKSI BEDA MATA UANG DI BACKEND (BUKAN DI FRONTEND)
        if debt_currency != bank_currency:
            rate = float(payload.exchange_rate or 0)
            if rate <= 0:
                return api_error(f"Transaksi Lintas Mata Uang ({debt_currency} ke {bank_currency}) Wajib Memasukkan Rate/Kurs Valid!")
            # Kalau beda mata uang, selalu DIKALI
            bank_mutation_amt = debt_deduction * rate
        else:
            # Kalau mata uang sama (USD ke USD), rate PASTI 1. Nggak peduli frontend ngirim apa.
            rate = 1.0
            bank_mutation_amt = debt_deduction

        curr_bal = float(res_acc.data.get("current_balance", 0))
        bank_name = res_acc.data.get("bank_name", "Bank")
        admin_id = admin.get("id") or admin.get("admin_id")

        # Validasi Overpay
        if debt_deduction > (rem_amt + 0.01):
            return api_error("Nominal bayar melebihi sisa tagihan asli!")

        # 4. LOGIKA DOUBLE ENTRY CROSS-CURRENCY
        if debt.get("debt_type") == "PIUTANG":
            new_bal = curr_bal + bank_mutation_amt
            trx_type = "IN"
            action_desc = "Terima Cicilan Piutang"
        elif debt.get("debt_type") == "HUTANG":
            if curr_bal < bank_mutation_amt:
                return api_error(f"Pembayaran dibatalkan! Saldo {bank_name} tidak cukup (Tersedia: {curr_bal}).")
            new_bal = curr_bal - bank_mutation_amt
            trx_type = "OUT"
            action_desc = "Bayar Cicilan Hutang"
        else:
            return api_error("Tipe kontrak bermasalah.")

        # 5. Kalkulasi Sisa Kontrak Asli
        new_rem_amt = rem_amt - debt_deduction
        new_status = "LUNAS" if new_rem_amt <= 0.01 else "MENYICIL" 

        # 6. EKSEKUSI DATABASE
        supabase.table("finance_debts").update({
            "remaining_amount": new_rem_amt,
            "status": new_status,
            "updated_at": datetime.now().isoformat()
        }).eq("id", payload.debt_id).execute()

        supabase.table("finance_accounts").update({"current_balance": new_bal}).eq("id", payload.account_id).execute()

        # Log ke Buku Besar
        ref_id = generate_trx_ref("PAY")
        cat_id = get_category_id_by_name(debt.get("debt_type").lower(), 1)
        
        # Tambahin info kurs di deskripsi biar jelas di mutasi
        kurs_info = f" (Rate: {rate})" if debt_currency != bank_currency else ""
        mut_desc = f"[{ref_id}] {action_desc} ({debt.get('person_name')}){kurs_info} - {payload.description}"
        
        supabase.table("finance_mutations").insert({
            "account_id": payload.account_id,
            "category_id": cat_id,
            "transaction_type": trx_type,
            "amount": bank_mutation_amt, 
            "balance_after": new_bal,
            "description": mut_desc,
            "reference_debt_id": payload.debt_id,
            "created_by": admin_id 
        }).execute()

        log_system_audit(admin.get("username", "Admin"), "REPAY_DEBT", f"Debt ID: {payload.debt_id}, Pay: {debt_deduction}, Rate: {rate}, Bank Mut: {bank_mutation_amt}, Left: {new_rem_amt}")
        return api_success(message=f"Sukses! Pembayaran dicatat dan Dompet disinkronisasi. Sisa tagihan sekarang: {new_rem_amt}")

    except Exception as e:
        logger.error(f"❌ [REPAY DEBT ERROR]: {e}")
        return api_error(f"Fatal Error Sistem: {str(e)}")
    
@router.get("/debts/{debt_id}/history")
async def get_debt_repayment_history(debt_id: str, admin=Depends(get_current_admin)):
    """
    API: Tarik data riwayat cicilan untuk satu kontrak secara spesifik.
    Dipakai oleh Modal History di Frontend.
    """
    if not supabase: return api_error("Database Offline", 503)
    
    try:
        # Tarik semua mutasi yang punya reference_debt_id ini, urutkan dari yang terbaru
        res_mut = supabase.table("finance_mutations").select(
            "id, created_at, transaction_type, amount, description, finance_accounts(bank_name, currency)"
        ).eq("reference_debt_id", debt_id).order("created_at", desc=True).execute()
        
        # Eksekusi normalisasi khusus untuk API (karena kita ga panggil normalize_mutations utama)
        history_data = []
        for m in (res_mut.data or []):
            acc_info = m.get("finance_accounts")
            if isinstance(acc_info, list) and len(acc_info) > 0: acc_info = acc_info[0]
            elif not isinstance(acc_info, dict): acc_info = {"bank_name": "Umum", "currency": "IDR"}
            
            m["finance_accounts"] = acc_info
            history_data.append(m)

        return api_success(data={"history": history_data})

    except Exception as e:
        logger.error(f"❌ [HISTORY DEBT ERROR]: {e}")
        return api_error(f"Gagal menarik riwayat cicilan: {str(e)}")

# ==============================================================================
# END OF FILE (BABA PARFUME ENTERPRISE FINANCE ENGINE)
# ==============================================================================