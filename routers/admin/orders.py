from fastapi import APIRouter, Request, Form, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

# Import koneksi Supabase murni
try:
    from database import supabase
except ImportError:
    print("❌ [SYSTEM] File database.py tidak ditemukan!")
    supabase = None

# Inisiasi Router khusus Admin CRM (Pesanan)
router = APIRouter(prefix="/admin", tags=["Admin CRM"])
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
@router.get("/orders", response_class=HTMLResponse)
async def admin_orders(request: Request):
    pesanan = []
    pending_count = 0
    if supabase:
        try:
            # LEVERAGE: Tarik data Deep-Join (Order + Customer + Items + Nama Produk)
            # Ini kuncinya biar Modal Detail lu ga kosong!
            res = supabase.table("orders").select(
                 "*, customers(full_name, phone, username, default_address, telegram_id), order_items(*, products(name, image_url))"
            ).order("created_at", desc=True).execute()
            pesanan = res.data or []
            pending_count = sum(1 for o in pesanan if o.get('status') == 'Menunggu Pembayaran')
        except Exception as e:
            print(f"❌ [ERROR LOAD ORDERS]: {e}")
            
    return templates.TemplateResponse("admin/orders.html", {
        "request": request, 
        "pesanan": pesanan, 
        "pending_count": pending_count
    })

# ==============================================================================
# JALUR API / LOGIKA BISNIS (CRUD)
# ==============================================================================
@router.post("/update-order-status")
async def update_order_status(order_id: str = Form(...), status_order: str = Form(..., alias="status")):
    """Ubah status resi, eksekusi finansial otomatis, pengembalian stok jika batal, dan notifikasi bot"""
    try:
        # 0. Tarik Data Order Lama (Sebelum di-update) buat ngecek state sebelumnya
        res_old_order = supabase.table("orders").select("status, total_amount, order_number, payment_method").eq("id", order_id).single().execute()
        if not res_old_order.data:
            raise HTTPException(status_code=404, detail="Order tidak ditemukan")
        
        old_status = res_old_order.data.get("status", "").lower()
        new_status = status_order.lower()
        omset = float(res_old_order.data.get("total_amount", 0))
        no_order = res_old_order.data.get("order_number")
        payment_method = res_old_order.data.get("payment_method", "Cash")

        # 1. Update DB Pesanan Utama
        supabase.table("orders").update({"status": status_order}).eq("id", order_id).execute()
        logger.info(f"🔄 [ORDER] Status Order ID:{order_id} berubah dari {old_status} menjadi {status_order}")

        # ==========================================================
        # 💸 MAGIC AUTOPILOT 1: PEMASUKAN DANA (IN)
        # ==========================================================
        # Jika orderan diproses/selesai, dan sebelumnya BUKAN diproses/selesai
        if new_status in ["diproses", "selesai"] and old_status not in ["diproses", "selesai"]:
            
            # Cek apakah transaksi ini udah pernah dicatat di mutasi biar gak dobel
            cek_mutasi = supabase.table("finance_mutations").select("id").eq("reference_order_id", order_id).eq("transaction_type", "IN").execute()
            
            if not cek_mutasi.data: # Kalau belum ada di buku kas
                # Coba cari Bank ID berdasarkan payment_method (Misal bayar via "BCA", dia otomatis masuk bank BCA)
                res_bank_search = supabase.table("finance_accounts").select("id, current_balance").ilike("bank_name", f"%{payment_method}%").execute()
                if res_bank_search.data:
                    target_bank_id = res_bank_search.data[0]["id"]
                    saldo_skrg = float(res_bank_search.data[0]["current_balance"])
                else:
                    # Default Fallback (Misal Cash Laci)
                    target_bank_id = 1 
                    res_bank = supabase.table("finance_accounts").select("current_balance").eq("id", target_bank_id).single().execute()
                    saldo_skrg = float(res_bank.data.get("current_balance", 0)) if res_bank.data else 0

                saldo_baru = saldo_skrg + omset
                # Update Saldo Bank
                supabase.table("finance_accounts").update({"current_balance": saldo_baru}).eq("id", target_bank_id).execute()

                # Cari kategori 'Penjualan'
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
                    "reference_order_id": order_id
                }).execute()
                logger.info(f"💰 [FINANCE] Duit Rp {omset} dari {no_order} otomatis masuk ke Kas (Bank ID: {target_bank_id})!")

        # ==========================================================
        # 📦 MAGIC AUTOPILOT 2: KEMBALIKAN STOK & REFUND (JIKA DIBATALKAN)
        # ==========================================================
        elif new_status == "dibatalkan" and old_status != "dibatalkan":
            
            # A. KEMBALIKAN STOK BARANG (RESTOCK)
            res_items = supabase.table("order_items").select("product_id, quantity").eq("order_id", order_id).execute()
            for item in (res_items.data or []):
                pid = item["product_id"]
                qty_to_restore = item["quantity"]
                
                # Cek stok barang saat ini
                res_prod = supabase.table("products").select("stock_quantity").eq("id", pid).single().execute()
                if res_prod.data:
                    current_stock = int(res_prod.data.get("stock_quantity", 0))
                    restored_stock = current_stock + qty_to_restore
                    
                    # Balikin stok fisik
                    supabase.table("products").update({"stock_quantity": restored_stock}).eq("id", pid).execute()
                    # Catat ke log stok audit
                    supabase.table("stock_logs").insert({
                        "product_id": pid,
                        "action": "RESTORE_BATAL",
                        "adjustment_amount": qty_to_restore,
                        "final_stock": restored_stock,
                        "reason": f"Pengembalian stok dari pesanan batal: {no_order}"
                    }).execute()
            logger.info(f"📦 [INVENTORY] Stok barang untuk pesanan {no_order} berhasil dikembalikan ke gudang.")

            # B. TARIK KEMBALI DANA JIKA SEBELUMNYA SUDAH MASUK BUKU KAS (REFUND)
            cek_mutasi_masuk = supabase.table("finance_mutations").select("account_id").eq("reference_order_id", order_id).eq("transaction_type", "IN").execute()
            cek_mutasi_keluar = supabase.table("finance_mutations").select("id").eq("reference_order_id", order_id).eq("transaction_type", "OUT").execute()
            
            # Jika dulu duitnya udah sempat masuk (status sempat diproses), tapi sekarang dibatalin
            if cek_mutasi_masuk.data and not cek_mutasi_keluar.data:
                bank_refund_id = cek_mutasi_masuk.data[0]["account_id"]
                
                res_bank = supabase.table("finance_accounts").select("current_balance").eq("id", bank_refund_id).single().execute()
                if res_bank.data:
                    saldo_skrg = float(res_bank.data.get("current_balance", 0))
                    saldo_baru = saldo_skrg - omset # Tarik duitnya
                    
                    # Update Saldo Bank
                    supabase.table("finance_accounts").update({"current_balance": saldo_baru}).eq("id", bank_refund_id).execute()
                    
                    # Catat Pengeluaran Refund
                    cat_res = supabase.table("finance_categories").select("id").ilike("category_name", "%refund%").limit(1).execute()
                    cat_id = cat_res.data[0].get("id") if cat_res.data else 1

                    supabase.table("finance_mutations").insert({
                        "account_id": bank_refund_id,
                        "category_id": cat_id,
                        "transaction_type": "OUT",
                        "amount": omset,
                        "balance_after": saldo_baru,
                        "description": f"Koreksi/Refund dana pesanan batal {no_order}",
                        "reference_order_id": order_id
                    }).execute()
                    logger.info(f"💸 [FINANCE REFUND] Dana Rp {omset} ditarik kembali karena {no_order} dibatalkan!")

        # ==========================================================
        # 🤖 3. Notifikasi Background Telegram (Dengan UX Baru)
        # ==========================================================
        if BOT_AVAILABLE:
            try:
                res_order_cust = supabase.table("orders").select("customers(telegram_id, full_name)").eq("id", order_id).single().execute()
                if res_order_cust.data and res_order_cust.data.get("customers"):
                    tele_id = res_order_cust.data["customers"]["telegram_id"]
                    cust_name = res_order_cust.data["customers"]["full_name"]
                    
                    # Emoji Dinamis biar Telegram pesannya lebih asik
                    emoji_status = "✅" if new_status == "selesai" else "🚚" if new_status == "dikirim" else "❌" if new_status == "dibatalkan" else "👉"
                    
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
                    asyncio.create_task(bot_instance.send_message(chat_id=tele_id, text=pesan_notif, parse_mode="HTML"))
            except Exception as e:
                logger.warning(f"⚠️ [NOTIF BOT ERROR] Gagal mengirim info resi: {e}")

        return RedirectResponse(url="/admin/orders", status_code=status.HTTP_303_SEE_OTHER)
    except Exception as e:
        logger.error(f"❌ [UPDATE STATUS ERROR]: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# 🔥 FITUR TAMBAHAN (LEVERAGE): Hapus Pesanan Fiktif/Batal
@router.get("/orders/delete/{order_id}")
async def delete_order(order_id: str):
    try:
        supabase.table("orders").delete().eq("id", order_id).execute()
        return RedirectResponse(url="/admin/orders", status_code=status.HTTP_303_SEE_OTHER)
    except Exception as e:
        print(f"❌ [ERROR HAPUS PESANAN]: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/orders/delete/{order_id}")
