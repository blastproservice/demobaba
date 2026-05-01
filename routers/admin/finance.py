"""
================================================================================
BABA PARFUME ENTERPRISE ENGINE - CORE FINANCE MODULE
================================================================================
Modul ini menangani seluruh urat nadi keuangan (Cashflow, P&L, Asset Management).
Didesain khusus dengan arsitektur Double-Entry Bookkeeping yang disederhanakan.
Mendukung multi-currency (IDR, USD, KHR) untuk ekspansi market Kamboja.

Author: BABA Enterprise IT
Role: Super Admin / Oprasional Only
================================================================================
"""

import logging
import calendar
import uuid
import csv
import io
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta

from fastapi import APIRouter, Request, Depends, HTTPException, status, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

# Import Internal Project Engine
from routers.common import (
    supabase, logger, render_admin_template, require_admin_roles, 
    api_success, api_error, safe_array, format_currency
)
from routers.dependencies import get_current_admin
from routers.schemas import ManualTransactionPayload, TransferPayload

# Inisiasi Router khusus Admin Finance
router = APIRouter(prefix="/admin/finance", tags=["Finance Engine"])

# ==============================================================================
# 🛠️ GLOBAL HELPERS & UTILITIES
# ==============================================================================

def get_pending_count() -> int:
    """Mengambil jumlah order yang masih nyangkut di status 'Menunggu Pembayaran'"""
    if not supabase: return 0
    try:
        res = supabase.table("orders").select("id").eq("status", "Menunggu Pembayaran").execute()
        return len(res.data or [])
    except Exception as e:
        logger.error(f"[HELPER] Gagal narik pending count: {e}")
        return 0

def generate_trx_ref(prefix: str = "TRX") -> str:
    """Membuat ID Referensi Transaksi yang Unik (Misal: TRX-260512-AB12)"""
    now_str = datetime.now().strftime('%y%m%d%H%M')
    random_str = str(uuid.uuid4())[:4].upper()
    return f"{prefix}-{now_str}-{random_str}"

def get_category_id_by_name(keyword: str, fallback_id: int = 1) -> int:
    """Fungsi pintar untuk mencari ID Kategori berdasarkan keyword nama"""
    if not supabase: return fallback_id
    try:
        cat_res = supabase.table("finance_categories").select("id").ilike("category_name", f"%{keyword}%").limit(1).execute()
        if cat_res.data:
            return cat_res.data[0].get("id", fallback_id)
        return fallback_id
    except Exception:
        return fallback_id

# ==============================================================================
# 💰 SECTION 1: ASSETS & WALLET (Dashboard Keuangan Utama)
# ==============================================================================

@router.get("/aset", response_class=HTMLResponse)
async def admin_finance_aset(request: Request, admin=Depends(get_current_admin)):
    """
    CORE ROUTE: Menghitung kekayaan bersih BABA (Liquid + Physical Inventory).
    Halaman ini me-load data rekening, saldo real-time, dan formasi transaksi manual.
    """
    accounts = []
    total_liquid = 0.0
    total_inventory = 0.0
    recent_mutations = []
    categories_in = []
    categories_out = []

    if supabase:
        try:
            # 1. Tarik Data Rekening Bank & Hitung Saldo Liquid
            # Kita cuma ambil rekening yang statusnya 'is_active' = True
            res_acc = supabase.table("finance_accounts").select("*").eq("is_active", True).order("id").execute()
            accounts = res_acc.data or []
            
            # Looping untuk menghitung total uang cash/liquid di semua bank
            for acc in accounts:
                total_liquid += float(acc.get("current_balance", 0))

            # 2. Hitung Nilai Aset Stok Fisik (Leverage: Otomatisasi Harga Modal)
            # Ini ngalihin sisa botol di gudang dengan harga original/modal
            res_prod = supabase.table("products").select("stock_quantity, original_price").eq("is_active", True).execute()
            for p in (res_prod.data or []):
                stok_fisik = int(p.get("stock_quantity", 0))
                harga_modal = float(p.get("original_price", 0))
                total_inventory += (stok_fisik * harga_modal)

            # 3. Tarik 10 Transaksi Terakhir untuk preview di tabel bawah
            # Deep join ke tabel accounts dan categories biar namanya muncul
            res_mut = supabase.table("finance_mutations").select(
                "*, finance_accounts(bank_name), finance_categories(category_name)"
            ).order("created_at", desc=True).limit(10).execute()
            recent_mutations = res_mut.data or []

            # 4. Tarik Kategori Transaksi buat pop-up Modal Input Manual
            res_cat = supabase.table("finance_categories").select("*").execute()
            all_cats = res_cat.data or []
            
            # Pisahkan kategori masuk dan keluar biar gampang di UI
            categories_in = [c for c in all_cats if str(c.get("type")).upper() == "INCOME"]
            categories_out = [c for c in all_cats if str(c.get("type")).upper() == "EXPENSE"]

            logger.info(f"💼 [FINANCE] Aset diakses oleh Admin ID: {admin.get('admin_id')}. Liquid: {total_liquid}")

        except Exception as e:
            logger.error(f"❌ [FINANCE ASET ERROR]: Terjadi kesalahan saat memuat data aset: {e}")

    # Render template dengan semua data yang udah dikalkulasi
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
# 📖 SECTION 2: BIG LEDGER / MUTASI (Buku Besar Keseluruhan)
# ==============================================================================

@router.get("/mutasi", response_class=HTMLResponse)
async def mutasi_page(request: Request, admin=Depends(get_current_admin)):
    """
    CORE ROUTE: Menampilkan Buku Besar (Ledger) dengan Join Data Lengkap.
    Menarik hingga 1000 row terakhir untuk kemudian difilter secara dinamis di Frontend.
    """
    mutations = []
    accounts = []
    
    if supabase:
        try:
            # Tarik daftar bank buat dropdown filter rekening di UI
            res_acc = supabase.table("finance_accounts").select("id, bank_name").eq("is_active", True).execute()
            accounts = res_acc.data or []

            # Tarik data mutasi masif
            # Menggunakan Limit 1000 agar performa server dan browser tetap terjaga
            res_mut = supabase.table("finance_mutations").select(
                "*, finance_accounts(bank_name), finance_categories(category_name, type)"
            ).order("created_at", desc=True).limit(1000).execute()
            
            mutations = res_mut.data or []
            logger.info(f"📚 [FINANCE] Ledger diakses. Total baris dimuat: {len(mutations)}")
            
        except Exception as e:
            logger.error(f"❌ [FINANCE MUTASI ERROR]: Gagal memuat buku besar: {e}")

    return render_admin_template(
        request, "admin/finance_mutasi.html", 
        admin_data=admin,
        mutations=mutations, 
        accounts=accounts,
        pending_count=get_pending_count()
    )


# ==============================================================================
# 📊 SECTION 3: PROFIT & LOSS REPORT (Laporan Eksekutif)
# ==============================================================================

@router.get("/report", response_class=HTMLResponse)
async def admin_finance_report(request: Request, 
                               month: Optional[str] = Query(None), 
                               year: Optional[str] = Query(None),
                               admin=Depends(get_current_admin)):
    """
    CORE ROUTE: Mesin Kalkulasi Laba Rugi (P&L) Standar Enterprise.
    Membedah Pendapatan (Revenue), HPP (COGS), dan Biaya Operasional (Opex) secara mendalam.
    """
    # Proteksi Ketat: Hanya Super Admin yang boleh melihat angka margin dan P&L
    if str(admin.get("admin_role")).lower() != "super_admin":
        logger.warning(f"🔒 [SECURITY] Admin {admin.get('admin_name')} mencoba akses P&L Report secara ilegal!")
        return RedirectResponse(url="/admin/finance/aset")

    # Inisialisasi struktur data laporan
    report_data = {
        "total_revenue": 0.0, "total_hpp": 0.0, "total_opex": 0.0,
        "gross_profit": 0.0, "net_profit": 0.0, "margin": 0.0,
        "total_trx_in": 0, "total_trx_out": 0, "avg_revenue_per_day": 0.0,
        "biggest_expense_cat": "N/A", "biggest_expense_amt": 0.0
    }
    
    categories_breakdown = {"income": {}, "hpp": {}, "opex": {}}
    daily_trends = {}
    raw_mutations = []
    
    if supabase:
        try:
            # 1. Setup Range Tanggal (Default: Bulan Berjalan)
            now = datetime.now()
            t_month = int(month) if month else now.month
            t_year = int(year) if year else now.year
            last_day = calendar.monthrange(t_year, t_month)[1]

            # Format ISO untuk Query PostgreSQL
            start_date = f"{t_year}-{t_month:02d}-01T00:00:00"
            end_date = f"{t_year}-{t_month:02d}-{last_day}T23:59:59"

            # 2. Tarik Data Mutasi Khusus Periode Tersebut (Mencegah Overload RAM)
            res_mut = supabase.table("finance_mutations").select(
                "*, finance_categories(category_name, type), finance_accounts(bank_name)"
            ).gte("created_at", start_date).lte("created_at", end_date).order("created_at", desc=False).execute()
            
            raw_mutations = res_mut.data or []
            
            # 3. ENGINE KALKULASI: Loop Tunggal (O(n)) untuk Memisahkan Kategori
            for m in raw_mutations:
                cat_info = m.get("finance_categories") or {}
                raw_cat = cat_info.get("category_name", "Umum")
                cat_lower = str(raw_cat).lower()
                amt = float(m.get("amount", 0))
                
                # Split tanggal untuk tren harian chart
                trx_date = m.get("created_at", "").split("T")[0]
                if trx_date not in daily_trends: 
                    daily_trends[trx_date] = {"in": 0.0, "out": 0.0}
                
                trx_type = str(m.get("transaction_type")).upper()
                
                if trx_type == "IN":
                    # Menghitung Pendapatan / Uang Masuk
                    report_data["total_revenue"] += amt
                    report_data["total_trx_in"] += 1
                    daily_trends[trx_date]["in"] += amt
                    
                    # Grouping berdasarkan nama kategori
                    categories_breakdown["income"][raw_cat] = categories_breakdown["income"].get(raw_cat, 0) + amt
                    
                elif trx_type == "OUT":
                    # Menghitung Pengeluaran / Uang Keluar
                    report_data["total_trx_out"] += 1
                    daily_trends[trx_date]["out"] += amt
                    
                    # LOGIC BISNIS BABA: Pisahkan HPP (Modal Barang) vs Opex (Biaya Operasional)
                    is_hpp = any(keyword in cat_lower for keyword in ["stok", "belanja", "jastip", "ongkir", "biang", "botol", "lakban", "kardus"])
                    
                    if is_hpp:
                        report_data["total_hpp"] += amt
                        categories_breakdown["hpp"][raw_cat] = categories_breakdown["hpp"].get(raw_cat, 0) + amt
                    else:
                        report_data["total_opex"] += amt
                        categories_breakdown["opex"][raw_cat] = categories_breakdown["opex"].get(raw_cat, 0) + amt
                        
                        # Deteksi pengeluaran operasional paling membengkak
                        if categories_breakdown["opex"][raw_cat] > report_data["biggest_expense_amt"]:
                            report_data["biggest_expense_amt"] = categories_breakdown["opex"][raw_cat]
                            report_data["biggest_expense_cat"] = raw_cat

            # 4. FINALISASI METRIK KEUANGAN
            # Laba Kotor = Total Omset - Total Modal Barang
            report_data["gross_profit"] = report_data["total_revenue"] - report_data["total_hpp"]
            
            # Laba Bersih = Laba Kotor - Biaya Operasional (Gaji, Listrik, Iklan, dll)
            report_data["net_profit"] = report_data["gross_profit"] - report_data["total_opex"]
            
            # Hitung Margin dalam Persen
            if report_data["total_revenue"] > 0:
                report_data["margin"] = round((report_data["net_profit"] / report_data["total_revenue"]) * 100, 1)
                
            # Hitung rata-rata omset per hari aktif
            active_days = len(daily_trends) if len(daily_trends) > 0 else 1
            report_data["avg_revenue_per_day"] = round(report_data["total_revenue"] / active_days, 2)

            logger.info(f"📈 [REPORT ENGINE] P&L {t_month}/{t_year} sukses dirender. Net Profit: {report_data['net_profit']}")

        except Exception as e:
            logger.error(f"❌ [REPORT ENGINE ERROR]: Gagal mengkalkulasi laporan: {e}")

    return render_admin_template(
        request, "admin/finance_report.html", 
        admin_data=admin,
        report=report_data,
        categories=categories_breakdown,
        daily_trends=daily_trends,
        mutations=raw_mutations, # Dikirim utuh buat di-parse oleh Chart.js di frontend
        period_text=f"{t_month:02d}/{t_year}",
        pending_count=get_pending_count()
    )


# ==============================================================================
# ⚡ SECTION 4: API ENDPOINTS (Action Modals & AJAX Calls)
# ==============================================================================

@router.post("/api/v1/finance/transaction")
async def api_manual_transaction(payload: ManualTransactionPayload, admin=Depends(get_current_admin)):
    """
    API: Mencatat Kas Masuk/Keluar manual dari modal UI Aset.
    Mendukung skenario: Suntik modal, bayar gaji, beli bensin, dll.
    """
    if not supabase: return api_error("Sistem Database Offline. Hubungi IT Support.", 503)
    
    try:
        # 1. Validasi Keberadaan Rekening & Ambil Saldo Saat Ini
        res_acc = supabase.table("finance_accounts").select("current_balance, bank_name").eq("id", payload.account_id).single().execute()
        if not res_acc.data: 
            return api_error("Rekening tidak valid atau sudah dihapus!")
        
        curr_bal = float(res_acc.data.get("current_balance", 0))
        amt = float(payload.amount)
        bank_name = str(res_acc.data.get("bank_name", "Unknown"))
        trx_type = str(payload.transaction_type).upper()

        # 2. Hitung Saldo Baru & Validasi Overdraft
        if trx_type == "IN":
            new_bal = curr_bal + amt
        elif trx_type == "OUT":
            # Cegah saldo minus jika bukan kartu kredit
            if curr_bal < amt: 
                return api_error(f"Gagal! Saldo di rekening {bank_name} tidak mencukupi. (Sisa: {curr_bal})")
            new_bal = curr_bal - amt
        else:
            return api_error("Tipe transaksi tidak valid. Harus IN atau OUT.")

        # 3. Eksekusi Database (Update Saldo & Catat Log Mutasi)
        # Idealnya menggunakan Transaction RPC, tapi kita pisah eksekusinya disini
        res_update = supabase.table("finance_accounts").update({"current_balance": new_bal}).eq("id", payload.account_id).execute()
        
        if res_update.data:
            ref_id = generate_trx_ref("MAN")
            
            supabase.table("finance_mutations").insert({
                "account_id": payload.account_id,
                "category_id": payload.category_id,
                "transaction_type": trx_type,
                "amount": amt,
                "balance_after": new_bal,
                "description": payload.description,
                "reference_order_id": None, # Karena ini manual, bukan dari order bot
                "created_by": admin.get("admin_id") # PENTING: Untuk Audit Trail
            }).execute()

            logger.info(f"💸 [FINANCE API] TRX {trx_type} sebesar {amt} di {bank_name} diproses oleh Admin ID: {admin.get('admin_id')}")
            return api_success(message="Transaksi berhasil dicatat dengan aman di buku besar!")
        else:
            raise Exception("Gagal mengupdate saldo rekening utama.")

    except Exception as e:
        logger.error(f"❌ [API TRX ERROR]: Gagal eksekusi transaksi manual: {e}")
        return api_error(f"Kesalahan Sistem: {str(e)}")


@router.post("/api/v1/finance/transfer")
async def api_transfer_transaction(payload: TransferPayload, admin=Depends(get_current_admin)):
    """
    CORE API: Logika Pindah Kas / Money Exchange Antar Rekening (Double-Entry Bookkeeping).
    Sangat krusial untuk mencegah uang gaib. Mendukung cross-currency rate.
    """
    if not supabase: return api_error("Sistem Database Offline.", 503)
    
    try:
        # 1. Validasi Penuh Rekening Sumber (From) & Tujuan (To)
        res_src = supabase.table("finance_accounts").select("current_balance, bank_name, currency").eq("id", payload.from_account_id).single().execute()
        res_dst = supabase.table("finance_accounts").select("current_balance, bank_name, currency").eq("id", payload.to_account_id).single().execute()
        
        if not res_src.data or not res_dst.data: 
            return api_error("Salah satu rekening tidak terdeteksi di database.")
        
        src_name = res_src.data.get("bank_name", "Source")
        dst_name = res_dst.data.get("bank_name", "Target")
        bal_src = float(res_src.data.get("current_balance", 0))
        bal_dst = float(res_dst.data.get("current_balance", 0))
        
        # 2. Validasi Ketersediaan Dana
        if bal_src < payload.amount_out: 
            return api_error(f"Pindah kas gagal! Saldo {src_name} kurang. (Tersedia: {bal_src})")

        # 3. Eksekusi Pengurangan (Source Account)
        new_bal_src = bal_src - payload.amount_out
        res_upd_src = supabase.table("finance_accounts").update({"current_balance": new_bal_src}).eq("id", payload.from_account_id).execute()
        
        # 4. Eksekusi Penambahan (Target Account)
        new_bal_dst = bal_dst + payload.amount_in
        res_upd_dst = supabase.table("finance_accounts").update({"current_balance": new_bal_dst}).eq("id", payload.to_account_id).execute()

        # Pastikan kedua rekening terupdate sebelum mencatat sejarahnya
        if res_upd_src.data and res_upd_dst.data:
            # 5. Catat Mutasi Ganda (Double Entry Bookkeeping)
            transfer_ref = generate_trx_ref("EXC" if payload.exchange_rate != 1.0 else "TF")
            cat_id = get_category_id_by_name("transfer", 1)
            
            # Log Uang Keluar (Kredit)
            supabase.table("finance_mutations").insert({
                "account_id": payload.from_account_id, 
                "category_id": cat_id,
                "transaction_type": "OUT", 
                "amount": payload.amount_out,
                "balance_after": new_bal_src, 
                "description": f"[{transfer_ref}] Kas keluar ke {dst_name} - {payload.description}",
                "created_by": admin.get("admin_id")
            }).execute()
            
            # Log Uang Masuk (Debit)
            supabase.table("finance_mutations").insert({
                "account_id": payload.to_account_id, 
                "category_id": cat_id,
                "transaction_type": "IN", 
                "amount": payload.amount_in,
                "balance_after": new_bal_dst, 
                "description": f"[{transfer_ref}] Kas masuk dari {src_name} - {payload.description}",
                "created_by": admin.get("admin_id")
            }).execute()

            logger.info(f"💱 [FINANCE TRANSFER] {payload.amount_out} dipindah dari {src_name} ke {dst_name} menjadi {payload.amount_in}")
            return api_success(message=f"Pindah kas dari {src_name} ke {dst_name} berhasil!")
        else:
            raise Exception("Gagal menyinkronkan saldo salah satu bank.")

    except Exception as e:
        logger.error(f"❌ [TRANSFER ERROR]: Kesalahan sistem saat memindah kas: {e}")
        return api_error(f"Sistem gagal mengeksekusi perpindahan dana: {str(e)}")


# ==============================================================================
# 🏦 SECTION 5: BANK MANAGEMENT & UTILITIES
# ==============================================================================

@router.post("/bank")
async def tambah_bank_baru(nama_bank: str = Form(...), 
                           nomor_rekening: str = Form(None), 
                           saldo_awal: float = Form(0.0), 
                           mata_uang: str = Form("IDR")):
    """
    API: Mendaftarkan rekening bank / E-Wallet baru ke dalam ekosistem BABA.
    Disiapkan untuk scale-up operasional di Cambodia (USD/KHR).
    """
    try:
        # Sanitasi data sebelum masuk database
        clean_bank_name = nama_bank.strip().upper()
        clean_currency = mata_uang.strip().upper()
        
        payload = {
            "bank_name": clean_bank_name,
            "account_number": nomor_rekening.strip() if nomor_rekening else None,
            "current_balance": saldo_awal,
            "currency": clean_currency,
            "is_active": True
        }
        
        # Eksekusi Insert
        res_insert = supabase.table("finance_accounts").insert(payload).execute()
        
        if res_insert.data:
            # Jika ada saldo awal > 0, langsung catat sebagai mutasi masuk "Modal Awal"
            if saldo_awal > 0:
                new_account_id = res_insert.data[0].get("id")
                cat_id = get_category_id_by_name("modal", 1)
                
                supabase.table("finance_mutations").insert({
                    "account_id": new_account_id,
                    "category_id": cat_id,
                    "transaction_type": "IN",
                    "amount": saldo_awal,
                    "balance_after": saldo_awal,
                    "description": f"Setoran saldo awal pembuatan rekening {clean_bank_name}"
                }).execute()
        
        logger.info(f"🏦 [BANK ADDED] Rekening baru terdaftar: {clean_bank_name} ({clean_currency})")
        # Balik lagi ke halaman aset setelah sukses
        return RedirectResponse(url="/admin/finance/aset", status_code=status.HTTP_303_SEE_OTHER)
        
    except Exception as e:
        logger.error(f"❌ [ADD BANK ERROR]: Gagal mendaftarkan bank baru: {e}")
        raise HTTPException(status_code=500, detail=f"Sistem gagal menambahkan bank: {str(e)}")


@router.get("/export/csv")
async def export_mutasi_csv(admin=Depends(get_current_admin)):
    """
    ENTERPRISE FEATURE: Download riwayat Mutasi (Ledger) ke dalam format CSV.
    Berguna untuk rekonsiliasi data dengan akuntan atau diolah di Excel.
    """
    # Proteksi keamanan export data sensitif
    if str(admin.get("admin_role")).lower() not in ["super_admin", "oprasional"]:
        raise HTTPException(status_code=403, detail="Tidak ada akses untuk export data.")

    if not supabase:
        raise HTTPException(status_code=503, detail="Database Offline")

    try:
        # Ambil 5000 transaksi terakhir untuk diexport
        res_mut = supabase.table("finance_mutations").select(
            "created_at, transaction_type, amount, balance_after, description, finance_categories(category_name), finance_accounts(bank_name)"
        ).order("created_at", desc=True).limit(5000).execute()
        
        mutations = res_mut.data or []
        
        # Buat buffer string untuk CSV
        output = io.StringIO()
        writer = csv.writer(output, delimiter=',', quotechar='"', quoting=csv.QUOTE_MINIMAL)
        
        # Tulis Header CSV
        writer.writerow(['Tanggal Waktu', 'Sumber/Bank', 'Tipe', 'Kategori', 'Nominal', 'Sisa Saldo', 'Deskripsi/Keterangan'])
        
        # Tulis Baris Data
        for m in mutations:
            dt_obj = datetime.fromisoformat(m.get('created_at').replace('Z', '+00:00'))
            formatted_date = dt_obj.strftime('%Y-%m-%d %H:%M:%S')
            
            bank_name = m.get('finance_accounts', {}).get('bank_name', 'Umum') if m.get('finance_accounts') else 'Umum'
            category = m.get('finance_categories', {}).get('category_name', 'Lainnya') if m.get('finance_categories') else 'Lainnya'
            
            # Formatting Angka biar kebaca di Excel
            amount = f"{m.get('amount', 0):.2f}"
            balance = f"{m.get('balance_after', 0):.2f}"
            
            writer.writerow([
                formatted_date,
                bank_name,
                m.get('transaction_type', '-'),
                category,
                amount,
                balance,
                m.get('description', '')
            ])
            
        output.seek(0)
        
        # Buat response yang nge-trigger browser untuk download file
        filename = f"BABA_Ledger_Export_{datetime.now().strftime('%Y%m%d')}.csv"
        headers = {
            'Content-Disposition': f'attachment; filename="{filename}"'
        }
        
        logger.info(f"📄 [FINANCE EXPORT] CSV diekspor oleh {admin.get('admin_name')} ({len(mutations)} baris)")
        return StreamingResponse(iter([output.getvalue()]), media_type='text/csv', headers=headers)

    except Exception as e:
        logger.error(f"❌ [EXPORT CSV ERROR]: {e}")
        raise HTTPException(status_code=500, detail="Gagal mengenerate file CSV")