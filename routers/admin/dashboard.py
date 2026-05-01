from typing import Optional
from datetime import datetime, timedelta
import logging

from fastapi import APIRouter, Request, Depends, HTTPException, status, Query
from fastapi.responses import HTMLResponse

from routers.common import supabase, safe_array, logger, render_admin_template, format_currency
from routers.dependencies import get_current_admin

router = APIRouter(prefix="/admin", tags=["Admin Core"])

# ==============================================================================
# HELPER: Filter Waktu (Biar dropdown lu fungsi!)
# ==============================================================================
def get_time_range(period: str):
    now = datetime.now()
    if period == "Bulan Ini":
        start_date = now.replace(day=1, hour=0, minute=0, second=0)
        label = "Bulan ini"
    elif period == "Tahun Ini":
        start_date = now.replace(month=1, day=1, hour=0, minute=0, second=0)
        label = "Tahun ini"
    else: # Default 7 Hari Terakhir
        start_date = now - timedelta(days=7)
        label = "7 Hari Terakhir"
    return start_date.isoformat(), label

# ==============================================================================
# JALUR RENDER DASHBOARD UTAMA
# ==============================================================================
@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def admin_dashboard(
    request: Request, 
    period: str = Query("7 Hari Terakhir"), # Tangkap pilihan dropdown
    admin=Depends(get_current_admin)        # Satpam VIP
):
    metrics = {
        "total_revenue": 0.0, "revenue_growth": 0.0, 
        "total_orders": 0, "completed_orders": 0,
        "total_customers": 0, "new_customers": 0,
        "low_stock_count": 0,
        "cat_man": 0, "cat_woman": 0, "cat_netral": 0
    }
    chart_data = [0, 0, 0, 0, 0, 0, 0] # Data asli buat grafik (7 hari)
    recent_orders = []
    top_products = []
    
    start_date_iso, period_label = get_time_range(period)

    if supabase:
        try:
            # 1. Ambil Data Inventaris (Statis/Semua)
            res_produk = supabase.table("products").select("*").execute()
            produk_data = res_produk.data or []
            
            for p in produk_data:
                tags = [t.upper() for t in safe_array(p.get("tags"))]
                stok = int(p.get("stock_quantity", 0))
                if stok <= 5 and p.get("is_active", True): metrics["low_stock_count"] += 1
                
                if "MAN" in tags: metrics["cat_man"] += stok
                elif "WOMAN" in tags: metrics["cat_woman"] += stok
                else: metrics["cat_netral"] += stok

            # 2. Ambil Data Orders BERDASARKAN FILTER WAKTU
            res_orders = supabase.table("orders").select("*, customers(full_name)")\
                        .gte("created_at", start_date_iso).order("created_at", desc=True).execute()
            orders_data = res_orders.data or []
            metrics["total_orders"] = len(orders_data)

            for o in orders_data:
                amount = float(o.get("total_amount", 0))
                if o.get("status") in ["Selesai", "Diproses"]:
                    metrics["completed_orders"] += 1
                    metrics["total_revenue"] += amount
                
                # Isi data grafik (Jika 7 hari terakhir)
                if period == "7 Hari Terakhir":
                    order_date = datetime.fromisoformat(o['created_at'].replace('Z', '+00:00'))
                    days_ago = (datetime.now() - order_date).days
                    if 0 <= days_ago < 7:
                        chart_data[6 - days_ago] += amount

            # 3. Analisis Pelanggan
            res_cust = supabase.table("customers").select("id, created_at").execute()
            cust_data = res_cust.data or []
            metrics["total_customers"] = len(cust_data)
            metrics["new_customers"] = len([c for c in cust_data if c['created_at'] >= start_date_iso])

            # UI Slicing
            recent_orders = orders_data[:5]
            top_products = sorted(produk_data, key=lambda x: x.get('stock_quantity', 0))[:4]
            
            # Hitung Growth (Simulasi perbandingan dengan total order)
            if metrics["total_orders"] > 0:
                metrics["revenue_growth"] = round((metrics["completed_orders"] / metrics["total_orders"]) * 100, 1)

        except Exception as e:
            logger.error(f"❌ [DASHBOARD ERROR]: {e}")

    return render_admin_template(
        request, "admin/dashboard.html",
        admin_data=admin,
        metrics=metrics,
        recent_orders=recent_orders,
        top_products=top_products,
        chart_data=chart_data,
        current_period=period,
        period_label=period_label
    )