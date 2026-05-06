"""
====================================================================================
BABA PARFUME - DASHBOARD ANALYTICS ENGINE (ENTERPRISE EDITION)
====================================================================================
Deskripsi : Otak di balik Dashboard Utama BABA Enterprise.
            Beroperasi sebagai REST API yang menyuplai data JSON ke frontend Alpine.js
            mendukung filter periode dinamis, perbandingan omset (growth),
            distribusi stok, dan algoritma Top Sales (Hall of Fame).
====================================================================================
"""
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any
from collections import defaultdict

from fastapi import APIRouter, Request, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse

from routers.common import supabase, safe_array, render_admin_template
from routers.dependencies import get_current_admin

logger = logging.getLogger("baba.dashboard")

router = APIRouter(prefix="/admin", tags=["Admin Dashboard"])

# ==============================================================================
# 1. JALUR RENDER HTML (KOSONGAN) - Data diisi via AJAX dari Frontend
# ==============================================================================
@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def admin_dashboard_page(request: Request, admin=Depends(get_current_admin)):
    """Hanya me-render skeleton HTML. Data aktual diambil frontend via API di bawah."""
    return render_admin_template(
        request, 
        "admin/dashboard.html",
        admin_data=admin
    )

# ==============================================================================
# 2. API ENDPOINT: DASHBOARD STATS (ENGINE UTAMA)
# ==============================================================================
@router.get("/api/v1/dashboard/stats")
async def api_dashboard_stats(
    start: str = Query(..., description="Start date YYYY-MM-DD"),
    end: str = Query(..., description="End date YYYY-MM-DD"),
    admin=Depends(get_current_admin)
):
    """
    Menyediakan semua data untuk Dashboard berdasarkan rentang waktu yang dipilih.
    """
    if not supabase:
        raise HTTPException(status_code=503, detail="Database Offline")

    try:
        # --- PREPARASI TANGGAL ---
        # Format tanggal untuk query ke Supabase
        start_dt = datetime.strptime(start, "%Y-%m-%d")
        end_dt = datetime.strptime(end, "%Y-%m-%d").replace(hour=23, minute=59, second=59)
        start_iso = start_dt.isoformat()
        end_iso = end_dt.isoformat()

        # Kalkulasi periode sebelumnya (untuk Growth %)
        delta_days = (end_dt - start_dt).days + 1
        prev_end_dt = start_dt - timedelta(seconds=1)
        prev_start_dt = prev_end_dt - timedelta(days=delta_days)
        prev_start_iso = prev_start_dt.isoformat()
        prev_end_iso = prev_end_dt.isoformat()

        # --- CONTAINER DATA ---
        metrics = {
            "revenue": 0.0, 
            "revenue_growth": 0.0, 
            "orders": 0, 
            "orders_completed": 0,
            "total_customers": 0, 
            "new_customers": 0,
            "low_stock": 0
        }
        category_stock = {"man": 0, "woman": 0, "netral": 0}
        chart_map = defaultdict(float) # Untuk numpuk omset per tanggal
        top_sales_map = defaultdict(lambda: {"name": "", "sold": 0, "revenue": 0.0})

        # ==========================================
        # A. ANALISA INVENTARIS & KATEGORI
        # ==========================================
        res_prod = supabase.table("products").select("id, name, stock_quantity, tags, is_active").execute()
        for p in res_prod.data or []:
            stock = int(p.get("stock_quantity") or 0)
            is_active = p.get("is_active", True)
            
            if stock <= 5 and is_active:
                metrics["low_stock"] += 1
                
            tags = [t.upper() for t in safe_array(p.get("tags"))]
            if "MAN" in tags and "WOMAN" not in tags:
                category_stock["man"] += stock
            elif "WOMAN" in tags:
                category_stock["woman"] += stock
            else:
                category_stock["netral"] += stock

        # ==========================================
        # B. ANALISA PELANGGAN
        # ==========================================
        res_cust = supabase.table("customers").select("id, created_at").execute()
        cust_data = res_cust.data or []
        metrics["total_customers"] = len(cust_data)
        metrics["new_customers"] = len([c for c in cust_data if start_iso <= c['created_at'] <= end_iso])

        # ==========================================
        # C. ANALISA PENJUALAN (CURRENT PERIOD)
        # ==========================================
        # Ambil pesanan di periode terpilih
        res_orders = supabase.table("orders").select("id, order_number, total_amount, status, created_at, payment_method, customers(full_name)")\
                             .gte("created_at", start_iso).lte("created_at", end_iso).order("created_at", desc=True).execute()
        
        current_orders = res_orders.data or []
        metrics["orders"] = len(current_orders)
        
        completed_order_ids = []
        recent_orders_list = []

        for idx, o in enumerate(current_orders):
            status = o.get("status", "").upper()
            amount = float(o.get("total_amount") or 0)
            
            # Format Recent Orders (Ambil 5 Teratas)
            if idx < 5:
                cust_name = "Unknown"
                if o.get("customers") and isinstance(o["customers"], dict):
                    cust_name = o["customers"].get("full_name", "Unknown")
                    
                recent_orders_list.append({
                    "order_number": o.get("order_number"),
                    "created_at": o.get("created_at"),
                    "customer_name": cust_name,
                    "payment_method": o.get("payment_method", "UNKNOWN"),
                    "total_amount": amount,
                    "status": status
                })

            # Jika pesanan Selesai / Diproses, masuk hitungan Omset & Chart
            if status in ["SELESAI", "COMPLETED", "DIPROSES", "PROSES"]:
                metrics["orders_completed"] += 1
                metrics["revenue"] += amount
                completed_order_ids.append(o.get("id"))
                
                # Chart Data Grouping (Format: "12 May")
                order_dt = datetime.fromisoformat(o["created_at"].replace("Z", "+00:00"))
                label = order_dt.strftime("%d %b")
                chart_map[label] += amount

        # ==========================================
        # D. MENGHITUNG GROWTH (REVENUE PERIODE SEBELUMNYA)
        # ==========================================
        res_prev = supabase.table("orders").select("total_amount, status")\
                           .gte("created_at", prev_start_iso).lte("created_at", prev_end_iso).execute()
        
        prev_revenue = 0.0
        for po in res_prev.data or []:
            if po.get("status", "").upper() in ["SELESAI", "COMPLETED", "DIPROSES", "PROSES"]:
                prev_revenue += float(po.get("total_amount") or 0)

        if prev_revenue > 0:
            growth = ((metrics["revenue"] - prev_revenue) / prev_revenue) * 100
            metrics["revenue_growth"] = round(growth, 1)
        elif metrics["revenue"] > 0:
            metrics["revenue_growth"] = 100.0  # Naik 100% dari 0
        else:
            metrics["revenue_growth"] = 0.0

        # ==========================================
        # E. THE REAL HALL OF FAME (TOP SALES)
        # ==========================================
        top_sales_list = []
        if completed_order_ids:
            # Ambil item dari orderan yang sukses di periode ini
            res_items = supabase.table("order_items").select("product_id, quantity, price_at_time, products(name)")\
                                .in_("order_id", completed_order_ids).execute()
            
            for item in res_items.data or []:
                pid = item.get("product_id")
                qty = int(item.get("quantity") or 0)
                subtotal = qty * float(item.get("price_at_time") or 0)
                
                p_name = "Deleted Product"
                if item.get("products") and isinstance(item["products"], dict):
                    p_name = item["products"].get("name", p_name)

                top_sales_map[pid]["name"] = p_name
                top_sales_map[pid]["sold"] += qty
                top_sales_map[pid]["revenue"] += subtotal

            # Sortir berdasarkan jumlah terjual (sold) terbanyak, ambil top 4
            sorted_sales = sorted(top_sales_map.values(), key=lambda x: x["sold"], reverse=True)[:4]
            top_sales_list = sorted_sales

        # ==========================================
        # F. FINALISASI DATA CHART
        # ==========================================
        # Konversi Map ke List untuk frontend [{label: "12 May", val: 50000}]
        # Diurutkan berdasarkan tanggal aktual
        chart_raw = []
        
        # Buat rentang tanggal kosong (agar grafik tidak putus kalau ada hari tanpa order)
        # Batasi maksimal 30 titik di grafik agar UI tidak rusak
        days_to_plot = min(delta_days, 30) 
        step = max(1, delta_days // 30) # Jika pilih 1 tahun, step-nya lompat beberapa hari

        curr_dt = start_dt
        while curr_dt <= end_dt:
            lbl = curr_dt.strftime("%d %b")
            chart_raw.append({
                "label": lbl,
                "val": chart_map.get(lbl, 0.0)
            })
            curr_dt += timedelta(days=step)

        # ==========================================
        # KEMBALIKAN KE FRONTEND
        # ==========================================
        return JSONResponse(content={
            "status": "success",
            "metrics": metrics,
            "category_stock": category_stock,
            "chart_raw": chart_raw,
            "recent_orders": recent_orders_list,
            "top_sales": top_sales_list
        })

    except Exception as e:
        logger.error(f"❌ [API DASHBOARD STATS ERROR]: {e}")
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})