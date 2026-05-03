import uuid
import asyncio
from datetime import datetime
import logging
from typing import Optional

from fastapi import APIRouter, Request, Form, HTTPException, status, Depends
from fastapi.responses import HTMLResponse, RedirectResponse

# Import toolkit BABA
from routers.common import templates, render_admin_template, require_admin_roles, api_success, api_error, BOT_AVAILABLE
from routers.dependencies import get_current_admin

logger = logging.getLogger("BabaOrderEngine")

try:
    from database import supabase
except ImportError:
    supabase = None

# Inisiasi Router khusus Admin Logistik & CRM
router = APIRouter(prefix="/admin", tags=["Admin CRM"])

# ==============================================================================
# HELPER FUNCTIONS
# ==============================================================================
def get_pending_count() -> int:
    """Ngitung antrian orderan yang belum dibayar/diproses"""
    if not supabase: return 0
    try:
        res = supabase.table("orders").select("id").eq("status", "Menunggu Pembayaran").execute()
        return len(res.data or [])
    except Exception as e:
        logger.warning(f"Gagal hitung pending orders: {e}")
        return 0

def find_bank_id(bank_name: str) -> Optional[int]:
    """Cari ID akun bank di database berdasarkan namanya"""
    if not supabase or not bank_name: return None
    try:
        res = supabase.table("finance_accounts").select("id").ilike("bank_name", f"%{bank_name}%").execute()
        return res.data[0]["id"] if res.data else None
    except:
        return None

def get_finance_category(category_keyword: str) -> int:
    """Cari ID kategori finance (Penjualan/Refund), default 1 jika ga nemu"""
    if not supabase: return 1
    try:
        res = supabase.table("finance_categories").select("id").ilike("category_name", f"%{category_keyword}%").limit(1).execute()
        return res.data[0]["id"] if res.data else 1
    except:
        return 1


# ==============================================================================
# 1. RENDER HALAMAN UTAMA (GET)
# ==============================================================================
@router.get("/orders", response_class=HTMLResponse)
async def admin_orders(request: Request, admin=Depends(get_current_admin)):
    """Menampilkan Dashboard Daftar Pesanan Masuk dengan Relasi Deep-Join"""
    pesanan = []
    
    if supabase:
        try:
            # LEVERAGE: Tarik data Deep-Join (Order + Customer + Items + Produk)
            # Query ini udah sinkron 100% sama Modal Detail di frontend
            res = supabase.table("orders").select(
                 "*, customers(full_name, phone, username, default_address, telegram_id), order_items(*, products(name, image_url))"
            ).order("created_at", desc=True).execute()
            
            pesanan = res.data or []
        except Exception as e:
            logger.error(f"❌ [DB ERROR] Gagal load orders: {e}")
            
    # Kembalikan tampilan dengan formasi lengkap
    return render_admin_template(
        request, 
        "admin/orders.html", 
        admin_data=admin, 
        pesanan=pesanan, 
        pending_count=get_pending_count()
    )


# ==============================================================================
# 2. THE EXECUTION ENGINE (POST) - UPDATE STATUS & FINANCE ROUTING
# ==============================================================================
@router.post("/update-order-status")
async def update_order_status(
    request: Request, 
    order_id: str = Form(...), 
    status_order: str = Form(..., alias="status"),
    target_bank: str = Form(None), # Nangkap data bank dari UI baru
    exchange_rate: float = Form(1.0), # Nangkap data kurs manual dari UI baru
    admin=Depends(get_current_admin)
):
    """
    Otak utama untuk mengubah status logistik, eksekusi pembukuan pintar, 
    pengembalian stok, dan kirim notif bot Telegram.
    """
    
    # -------------------------------------------------------------------
    # A. VALIDASI OTORISASI
    # -------------------------------------------------------------------
    admin_id = admin.get("admin_id")
    admin_role = admin.get("admin_role")
    
    # Keamanan Ekstra: Cuma Oprasional & Super Admin yang boleh mainan order
    if admin_role not in ["super_admin", "oprasional"]:
        logger.warning(f"🛑 [ACCESS DENIED] {admin.get('admin_name')} mencoba mengubah order.")
        raise HTTPException(status_code=403, detail="Akses ditolak. Hanya Oprasional/Super Admin.")

    if not supabase:
        raise HTTPException(status_code=503, detail="Sistem Database Sedang Offline")

    try:
        # -------------------------------------------------------------------
        # B. TARIK DATA ORDER EKSISTING (UNTUK KOMPARASI STATE)
        # -------------------------------------------------------------------
        res_old = supabase.table("orders").select("status, total_amount, order_number, payment_method, customer_id").eq("id", order_id).single().execute()
        if not res_old.data:
            raise HTTPException(status_code=404, detail="Data Pesanan Fiktif/Tidak Ditemukan")
        
        old_data = res_old.data
        old_status = old_data.get("status", "").lower()
        new_status = status_order.lower()
        
        # Nominal Tagihan Asli (Base USD)
        omset_usd_raw = float(old_data.get("total_amount", 0))
        no_order = old_data.get("order_number")
        
        # -------------------------------------------------------------------
        # C. UPDATE STATUS UTAMA DI DATABASE
        # -------------------------------------------------------------------
        # Biar frontend berubah statusnya, update dulu tabel ordernya
        supabase.table("orders").update({
            "status": status_order,
            "updated_at": datetime.now().isoformat()
        }).eq("id", order_id).execute()
        
        logger.info(f"🔄 [LOGISTIK] {no_order} berpindah: {old_status.upper()} ➡️ {new_status.upper()}")

        # ===================================================================
        # D. STRATEGI FINANSIAL: SMART CURRENCY ROUTING (THE BRAIN)
        # ===================================================================
        # Syarat Uang Cair: Status baru "Selesai" dan status sebelumnya BUKAN "Selesai"
        # Ini mencegah uang masuk dobel kalau admin klik "Selesai" berkali-kali.
        if new_status == "selesai" and old_status != "selesai":
            
            logger.info(f"⚡ [FINANCE ENGINE] Menyiapkan eksekusi kas untuk {no_order}...")
            
            # D.1. Proteksi Mutasi Ganda
            cek_mutasi = supabase.table("finance_mutations").select("id").eq("reference_order_id", order_id).eq("transaction_type", "IN").execute()
            
            if not cek_mutasi.data: 
                # D.2. Tentukan Bank Target
                # Ambil dari input UI (target_bank), kalau null pake fallback payment_method
                bank_pilihan = target_bank if target_bank else old_data.get("payment_method", "Cash")
                
                # Cari ID Bank di DB
                bank_id = find_bank_id(bank_pilihan)
                
                if bank_id:
                    # Tarik info detail bank target
                    bank_info_res = supabase.table("finance_accounts").select("current_balance, currency, bank_name").eq("id", bank_id).single().execute()
                    bank_info = bank_info_res.data
                    
                    if bank_info:
                        saldo_awal = float(bank_info.get("current_balance", 0))
                        mata_uang_bank = bank_info.get("currency", "IDR").upper()
                        nama_bank_asli = bank_info.get("bank_name", "Unknown")
                        
                        # -------------------------------------------------------
                        # D.3. LOGIKA KONVERSI MATA UANG (THE LEVERAGE)
                        # -------------------------------------------------------
                        nominal_final = 0.0
                        deskripsi_kurs = ""
                        
                        if mata_uang_bank == "IDR":
                            # Harus dikonversi sesuai input rate (BCA)
                            # Misal: $10 x 15.000 = Rp 150.000
                            rate_valid = float(exchange_rate) if exchange_rate and float(exchange_rate) > 0 else 15000.0
                            nominal_final = omset_usd_raw * rate_valid
                            deskripsi_kurs = f" (Konversi USD ke IDR: Rate {rate_valid})"
                            
                        elif mata_uang_bank == "USD":
                            # Murni USD ke USD (Dolar Wings)
                            nominal_final = omset_usd_raw
                            deskripsi_kurs = " (Pure USD Rate)"
                            
                        elif mata_uang_bank == "KHR":
                            # Fallback KHR (Kas Laci). Default statis 1 USD = 4000 KHR (Ubah jika perlu)
                            nominal_final = omset_usd_raw * 4000.0 
                            deskripsi_kurs = " (Auto KHR Rate 4000)"
                            
                        else:
                            # Safety Fallback
                            nominal_final = omset_usd_raw
                            
                        # D.4. Eksekusi Penambahan Saldo (Update Aset)
                        saldo_baru = saldo_awal + nominal_final
                        supabase.table("finance_accounts").update({
                            "current_balance": saldo_baru,
                            "updated_at": datetime.now().isoformat()
                        }).eq("id", bank_id).execute()

                        # D.5. Catat Mutasi ke Buku Besar (Ledger)
                        cat_id = get_finance_category("penjualan")
                        
                        catatan_mutasi = f"Pelunasan Order {no_order} via {nama_bank_asli}{deskripsi_kurs}"
                        
                        supabase.table("finance_mutations").insert({
                            "account_id": bank_id,
                            "category_id": cat_id,
                            "transaction_type": "IN",
                            "amount": nominal_final,
                            "balance_after": saldo_baru,
                            "description": catatan_mutasi,
                            "reference_order_id": order_id,
                            "created_by": admin_id
                        }).execute()
                        
                        # D.6. Update Total Spent Customer (Bonus CRM)
                        # Nambahin "Total Belanja" di profil pelanggan (dalam USD murni)
                        cust_id = old_data.get("customer_id")
                        if cust_id:
                            cust_res = supabase.table("customers").select("total_orders, total_spent").eq("id", cust_id).single().execute()
                            if cust_res.data:
                                cur_orders = int(cust_res.data.get("total_orders") or 0)
                                cur_spent = float(cust_res.data.get("total_spent") or 0.0)
                                
                                supabase.table("customers").update({
                                    "total_orders": cur_orders + 1,
                                    "total_spent": cur_spent + omset_usd_raw
                                }).eq("id", cust_id).execute()
                        
                        logger.info(f"💰 [FINANCE DONE] +{nominal_final} {mata_uang_bank} masuk ke {nama_bank_asli} dari {no_order}!")

                else:
                    logger.error(f"❌ [FINANCE FAILED] Akun Bank '{bank_pilihan}' tidak ditemukan di database!")

        # ===================================================================
        # E. STRATEGI REFUND & RESTOCK: JIKA DIBATALKAN
        # ===================================================================
        elif new_status == "dibatalkan" and old_status != "dibatalkan":
            
            logger.info(f"⚠️ [RESTOCK ENGINE] Mengembalikan barang {no_order} ke gudang...")
            
            # E.1. Restock Barang (Kembalikan fisik gudang)
            res_items = supabase.table("order_items").select("product_id, quantity").eq("order_id", order_id).execute()
            for item in (res_items.data or []):
                pid = item["product_id"]
                qty_to_restore = int(item["quantity"])
                
                res_prod = supabase.table("products").select("stock_quantity").eq("id", pid).single().execute()
                if res_prod.data:
                    current_stock = int(res_prod.data.get("stock_quantity", 0))
                    restored_stock = current_stock + qty_to_restore
                    
                    # Update Stok Utama
                    supabase.table("products").update({"stock_quantity": restored_stock}).eq("id", pid).execute()
                    
                    # Catat Log Audit Stok
                    supabase.table("stock_logs").insert({
                        "product_id": pid,
                        "action": "RESTORE_BATAL",
                        "adjustment_amount": qty_to_restore,
                        "final_stock": restored_stock,
                        "reason": f"Sistem: Pembatalan pesanan logistik {no_order}"
                    }).execute()
            logger.info(f"📦 [INVENTORY] Stok {no_order} berhasil direstore.")

            # E.2. Penarikan Dana (Jika terlanjur 'Selesai' sebelumnya)
            # Logika: Cari apakah order ini pernah bikin mutasi "IN". Jika ya, kita harus keluarin "OUT" sejumlah mutasi itu.
            cek_mutasi_masuk = supabase.table("finance_mutations").select("account_id, amount, description").eq("reference_order_id", order_id).eq("transaction_type", "IN").execute()
            cek_mutasi_keluar = supabase.table("finance_mutations").select("id").eq("reference_order_id", order_id).eq("transaction_type", "OUT").execute()
            
            # Kalau ada uang masuk, dan belum pernah ada uang keluar untuk order ini
            if cek_mutasi_masuk.data and not cek_mutasi_keluar.data:
                mutasi_in = cek_mutasi_masuk.data[0]
                bank_refund_id = mutasi_in["account_id"]
                nominal_refund = float(mutasi_in["amount"]) # Tarik nominal yang sama persis saat dia masuk (sudah kena kurs)
                
                res_bank = supabase.table("finance_accounts").select("current_balance, bank_name, currency").eq("id", bank_refund_id).single().execute()
                if res_bank.data:
                    saldo_skrg = float(res_bank.data.get("current_balance", 0))
                    saldo_baru = saldo_skrg - nominal_refund 
                    
                    # Potong saldo
                    supabase.table("finance_accounts").update({"current_balance": saldo_baru}).eq("id", bank_refund_id).execute()
                    
                    # Catat Refund
                    cat_id = get_finance_category("refund")
                    supabase.table("finance_mutations").insert({
                        "account_id": bank_refund_id,
                        "category_id": cat_id,
                        "transaction_type": "OUT",
                        "amount": nominal_refund,
                        "balance_after": saldo_baru,
                        "description": f"Koreksi/Refund otomatis pesanan dibatalkan: {no_order}",
                        "reference_order_id": order_id,
                        "created_by": admin_id
                    }).execute()
                    
                    logger.info(f"💸 [FINANCE KOREKSI] Dana {nominal_refund} ditarik dari {res_bank.data.get('bank_name')} akibat batal.")

        # ===================================================================
        # F. NOTIFIKASI BACKGROUND TELEGRAM (SILENT FIRING)
        # ===================================================================
        if BOT_AVAILABLE:
            try:
                res_order_cust = supabase.table("orders").select("customers(telegram_id, full_name)").eq("id", order_id).single().execute()
                if res_order_cust.data and res_order_cust.data.get("customers"):
                    tele_id = res_order_cust.data["customers"]["telegram_id"]
                    cust_name = res_order_cust.data["customers"]["full_name"]
                    
                    # Visualisasi UI Bot yang lebih asik
                    emoji_status = "✅" if new_status == "selesai" else "🚚" if new_status == "diproses" else "❌" if new_status == "dibatalkan" else "👉"
                    
                    pesan_notif = (
                        f"🔔 <b>UPDATE STATUS PESANAN</b> 🔔\n\n"
                        f"Halo kak <b>{cust_name}</b>!\n"
                        f"Pesanan kakak dengan nomor resi:\n"
                        f"🔖 <code>{no_order}</code>\n\n"
                        f"Saat ini statusnya:\n"
                        f"{emoji_status} <b>{status_order.upper()}</b>\n\n"
                    )
                    
                    if new_status == "dibatalkan":
                        pesan_notif += "<i>Mohon maaf, pesanan dibatalkan oleh sistem/admin. Hubungi CS kami jika ada kendala.</i>"
                    elif new_status == "diproses":
                        pesan_notif += "<i>Hore! Paket kakak sedang kami kemas dan siap dikirim. Harap ditunggu ya! 📦💨</i>"
                    elif new_status == "selesai":
                        pesan_notif += "<i>Terima kasih sudah belanja di BABA Parfume! Ditunggu pesanan selanjutnya ya kak ✨</i>"
                        
                    # Eksekusi bot tanpa membebani response web
                    from bot import bot as bot_instance
                    asyncio.create_task(bot_instance.send_message(chat_id=tele_id, text=pesan_notif, parse_mode="HTML"))
                    
            except Exception as e:
                # Cukup di-log, jangan bikin error web
                logger.warning(f"⚠️ [NOTIF BOT ERROR] Gagal nembak pesan ke Telegram: {e}")

        # G. KEMBALI KE LAYAR UTAMA
        return RedirectResponse(url="/admin/orders", status_code=status.HTTP_303_SEE_OTHER)

    except Exception as e:
        logger.error(f"❌ [CRITICAL ERROR] Sistem Gagal Eksekusi Order: {e}")
        # Kalau gagal, kasih tau admin lewat tampilan HTML
        raise HTTPException(status_code=500, detail=f"Sistem gagal mengeksekusi perintah logistik: {str(e)}")


# ==============================================================================
# 3. FITUR KONTROL KERAS (DELETE PERMANEN)
# ==============================================================================
@router.get("/orders/delete/{order_id}")
async def delete_order(order_id: str, admin=Depends(get_current_admin)):
    """Menghapus total rekam jejak pesanan dari database (Super Admin Only)"""
    
    if admin.get("admin_role") != "super_admin":
        logger.warning(f"🛑 [ACCESS DENIED] {admin.get('admin_name')} mencoba menghapus order.")
        raise HTTPException(status_code=403, detail="Akses ditolak. Hanya Dewa/Super Admin yang diizinkan memusnahkan data.")
        
    try:
        # Cek dulu apakah order ini punya history mutasi keuangan
        # Kalau ada, HARUSNYA ga boleh dihapus biar laporan keuangan ga cacat
        cek = supabase.table("finance_mutations").select("id").eq("reference_order_id", order_id).execute()
        if cek.data:
            # Sistem menolak penghapusan kalau udah ada jejak uang
            logger.warning(f"⚠️ [DELETE BLOCKED] Order {order_id} punya histori keuangan.")
            return HTMLResponse("<h1>Gagal Menghapus!</h1><p>Pesanan ini sudah masuk buku besar keuangan. Silakan ubah statusnya jadi 'Dibatalkan' saja agar uang dan stok dikoreksi otomatis.</p><a href='/admin/orders'>Kembali</a>")

        # Kalau aman (belum dibayar), musnahkan
        supabase.table("orders").delete().eq("id", order_id).execute()
        logger.info(f"🗑️ [PURGE] Order ID {order_id} resmi dimusnahkan.")
        return RedirectResponse(url="/admin/orders", status_code=status.HTTP_303_SEE_OTHER)
        
    except Exception as e:
        logger.error(f"❌ [ERROR PURGE]: {e}")
        raise HTTPException(status_code=500, detail=str(e))
