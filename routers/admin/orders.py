import uuid
import asyncio
from datetime import datetime
import logging

try:
    import google.genai
except ImportError:
    google = None

from fastapi import APIRouter, Request, Form, HTTPException, status, Depends
from fastapi.responses import HTMLResponse, RedirectResponse

# Import toolkit andalan kita
from routers.common import templates, render_admin_template, require_admin_roles, api_success, api_error, format_currency, BOT_AVAILABLE
from routers.dependencies import get_current_admin

logger = logging.getLogger(__name__)

try:
    from database import supabase
except ImportError:
    supabase = None

# Inisiasi Router khusus Admin CRM (Pesanan)
router = APIRouter(prefix="/admin", tags=["Admin CRM"])

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
@router.get("/orders", response_class=HTMLResponse)
async def admin_orders(request: Request, admin=Depends(get_current_admin)):
    """Menampilkan Dashboard Daftar Pesanan Masuk"""
    pesanan = []
    
    if supabase:
        try:
            # LEVERAGE: Tarik data Deep-Join (Order + Customer + Items + Produk)
            # Query ini udah sinkron 100% sama Modal Detail di frontend lu
            res = supabase.table("orders").select(
                 "*, customers(full_name, phone, username, default_address, telegram_id), order_items(*, products(name, image_url))"
            ).order("created_at", desc=True).execute()
            
            pesanan = res.data or []
        except Exception as e:
            logger.error(f"❌ [ERROR LOAD ORDERS]: {e}")
            
    # Kembalikan tampilan dengan formasi lengkap!
    return render_admin_template(
        request, 
        "admin/orders.html", 
        admin_data=admin, # Kunci biar sidebar gak ilang
        pesanan=pesanan, 
        pending_count=get_pending_count()
    )

# ==============================================================================
# JALUR API / LOGIKA BISNIS (CRUD & AUTOPILOT ENGINE)
# ==============================================================================
@router.post("/update-order-status")
async def update_order_status(
    request: Request, 
    order_id: str = Form(...), 
    status_order: str = Form(..., alias="status"),
    admin=Depends(get_current_admin)
):
    """Ubah status resi, eksekusi finansial otomatis, pengembalian stok jika batal, dan notifikasi bot"""
    
    # Keamanan Ekstra: Cuma Oprasional / Super Admin yang boleh ubah status
    if admin.get("admin_role") not in ["super_admin", "oprasional"]:
        raise HTTPException(status_code=403, detail="Akses ditolak. Anda tidak memiliki izin.")

    if not supabase:
        raise HTTPException(status_code=503, detail="Database Offline")

    try:
        # 0. Tarik Data Order Lama untuk ngecek state/kondisi sebelumnya
        res_old_order = supabase.table("orders").select("status, total_amount, order_number, payment_method").eq("id", order_id).single().execute()
        if not res_old_order.data:
            raise HTTPException(status_code=404, detail="Order tidak ditemukan")
        
        old_status = res_old_order.data.get("status", "").lower()
        new_status = status_order.lower()
        omset = float(res_old_order.data.get("total_amount", 0))
        no_order = res_old_order.data.get("order_number")
        payment_method = res_old_order.data.get("payment_method", "Cash")

        # 1. Update Tabel Pesanan Utama
        supabase.table("orders").update({"status": status_order}).eq("id", order_id).execute()
        logger.info(f"🔄 [ORDER] Status {no_order} berubah: {old_status.upper()} -> {new_status.upper()}")

        # ==========================================================
        # 💸 MAGIC AUTOPILOT 1: PEMASUKAN DANA (IN)
        # ==========================================================
        # Jika orderan baru saja naik tahta jadi 'diproses' atau 'selesai'
        if new_status in ["diproses", "selesai"] and old_status not in ["diproses", "selesai"]:
            
            # Cek apakah transaksi ini udah pernah dicatat di buku kas biar gak dobel
            cek_mutasi = supabase.table("finance_mutations").select("id").eq("reference_order_id", order_id).eq("transaction_type", "IN").execute()
            
            if not cek_mutasi.data: 
                # Cari Bank ID berdasarkan payment_method (Misal bayar via "BCA")
                res_bank_search = supabase.table("finance_accounts").select("id, current_balance").ilike("bank_name", f"%{payment_method}%").execute()
                if res_bank_search.data:
                    target_bank_id = res_bank_search.data[0]["id"]
                    saldo_skrg = float(res_bank_search.data[0]["current_balance"])
                else:
                    # Default Fallback (Kas Laci / ID 1)
                    target_bank_id = 1 
                    res_bank = supabase.table("finance_accounts").select("current_balance").eq("id", target_bank_id).single().execute()
                    saldo_skrg = float(res_bank.data.get("current_balance", 0)) if res_bank.data else 0

                saldo_baru = saldo_skrg + omset
                
                # Update Saldo Bank Asli
                supabase.table("finance_accounts").update({"current_balance": saldo_baru}).eq("id", target_bank_id).execute()

                # Cari ID kategori 'Penjualan'
                cat_res = supabase.table("finance_categories").select("id").ilike("category_name", "%penjualan%").limit(1).execute()
                cat_id = cat_res.data[0].get("id") if cat_res.data else 1

                # Catat ke Mutasi Buku Kas
                supabase.table("finance_mutations").insert({
                    "account_id": target_bank_id,
                    "category_id": cat_id,
                    "transaction_type": "IN",
                    "amount": omset,
                    "balance_after": saldo_baru,
                    "description": f"Penerimaan dana otomatis pesanan {no_order} via {payment_method}",
                    "reference_order_id": order_id,
                    "created_by": admin.get("admin_id") # Catat siapa admin yang proses
                }).execute()
                logger.info(f"💰 [FINANCE] Dana Rp {omset} dari {no_order} otomatis masuk Kas (Bank ID: {target_bank_id})!")

        # ==========================================================
        # 📦 MAGIC AUTOPILOT 2: KEMBALIKAN STOK & REFUND DANA (JIKA DIBATALKAN)
        # ==========================================================
        elif new_status == "dibatalkan" and old_status != "dibatalkan":
            
            # A. RESTOCK BARANG (KEMBALIKAN FISIK KE GUDANG)
            res_items = supabase.table("order_items").select("product_id, quantity").eq("order_id", order_id).execute()
            for item in (res_items.data or []):
                pid = item["product_id"]
                qty_to_restore = item["quantity"]
                
                # Cek stok barang saat ini
                res_prod = supabase.table("products").select("stock_quantity").eq("id", pid).single().execute()
                if res_prod.data:
                    current_stock = int(res_prod.data.get("stock_quantity", 0))
                    restored_stock = current_stock + qty_to_restore
                    
                    # Tembak stok balik
                    supabase.table("products").update({"stock_quantity": restored_stock}).eq("id", pid).execute()
                    
                    # Catat Log Audit Stok
                    supabase.table("stock_logs").insert({
                        "product_id": pid,
                        "action": "RESTORE_BATAL",
                        "adjustment_amount": qty_to_restore,
                        "final_stock": restored_stock,
                        "reason": f"Pengembalian stok dari pesanan batal: {no_order}"
                    }).execute()
            logger.info(f"📦 [INVENTORY] Stok {no_order} berhasil direstore ke gudang.")

            # B. TARIK DANA / REFUND JIKA SEBELUMNYA UDAH TERCATAT SEBAGAI PEMASUKAN
            cek_mutasi_masuk = supabase.table("finance_mutations").select("account_id").eq("reference_order_id", order_id).eq("transaction_type", "IN").execute()
            cek_mutasi_keluar = supabase.table("finance_mutations").select("id").eq("reference_order_id", order_id).eq("transaction_type", "OUT").execute()
            
            if cek_mutasi_masuk.data and not cek_mutasi_keluar.data:
                bank_refund_id = cek_mutasi_masuk.data[0]["account_id"]
                
                res_bank = supabase.table("finance_accounts").select("current_balance").eq("id", bank_refund_id).single().execute()
                if res_bank.data:
                    saldo_skrg = float(res_bank.data.get("current_balance", 0))
                    saldo_baru = saldo_skrg - omset 
                    
                    supabase.table("finance_accounts").update({"current_balance": saldo_baru}).eq("id", bank_refund_id).execute()
                    
                    # Catat Pengeluaran Refund di Buku Kas
                    cat_res = supabase.table("finance_categories").select("id").ilike("category_name", "%refund%").limit(1).execute()
                    cat_id = cat_res.data[0].get("id") if cat_res.data else 1

                    supabase.table("finance_mutations").insert({
                        "account_id": bank_refund_id,
                        "category_id": cat_id,
                        "transaction_type": "OUT",
                        "amount": omset,
                        "balance_after": saldo_baru,
                        "description": f"Koreksi/Refund dana pesanan batal {no_order}",
                        "reference_order_id": order_id,
                        "created_by": admin.get("admin_id")
                    }).execute()
                    logger.info(f"💸 [FINANCE] Dana Rp {omset} di-Refund karena {no_order} dibatalkan!")

        # ==========================================================
        # 🤖 3. NOTIFIKASI BACKGROUND KE BOT TELEGRAM PELANGGAN
        # ==========================================================
        if BOT_AVAILABLE:
            try:
                res_order_cust = supabase.table("orders").select("customers(telegram_id, full_name)").eq("id", order_id).single().execute()
                if res_order_cust.data and res_order_cust.data.get("customers"):
                    tele_id = res_order_cust.data["customers"]["telegram_id"]
                    cust_name = res_order_cust.data["customers"]["full_name"]
                    
                    # Emoji Dinamis biar notif di HP pelanggan kerasa hidup
                    emoji_status = "✅" if new_status == "selesai" else "🚚" if new_status == "diproses" else "❌" if new_status == "dibatalkan" else "👉"
                    
                    pesan_notif = (
                        f"🔔 <b>UPDATE PESANAN BABA PARFUME</b>\n\n"
                        f"Halo kak <b>{cust_name}</b>!\n"
                        f"Status pesanan kamu (<code>{no_order}</code>) sekarang:\n"
                        f"{emoji_status} <b>{status_order.upper()}</b>\n\n"
                    )
                    if new_status == "dibatalkan":
                        pesan_notif += "<i>Mohon maaf ya kak pesanan ini dibatalkan. Hubungi admin via bot jika ada kendala.</i>"
                    else:
                        pesan_notif += "<i>Terima kasih kak! ✨</i>"
                        
                    from bot import bot as bot_instance
                    # Tembak pesan tanpa bikin lemot server website
                    asyncio.create_task(bot_instance.send_message(chat_id=tele_id, text=pesan_notif, parse_mode="HTML"))
            except Exception as e:
                logger.warning(f"⚠️ [NOTIF BOT ERROR] Gagal mengirim info resi: {e}")

        # Redirect santuy kembali ke halaman pesanan
        return RedirectResponse(url="/admin/orders", status_code=status.HTTP_303_SEE_OTHER)
    except Exception as e:
        logger.error(f"❌ [UPDATE STATUS ERROR]: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# 🔥 FITUR TAMBAHAN: Hapus Pesanan Fiktif/Batal
@router.get("/orders/delete/{order_id}")
async def delete_order(order_id: str, admin=Depends(get_current_admin)):
    if admin.get("admin_role") != "super_admin":
        raise HTTPException(status_code=403, detail="Hanya Super Admin yang bisa hapus permanen")
        
    try:
        supabase.table("orders").delete().eq("id", order_id).execute()
        return RedirectResponse(url="/admin/orders", status_code=status.HTTP_303_SEE_OTHER)
    except Exception as e:
        logger.error(f"❌ [ERROR HAPUS PESANAN]: {e}")
        raise HTTPException(status_code=500, detail=str(e))