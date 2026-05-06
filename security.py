"""
====================================================================================
BABA PARFUME - ENTERPRISE SECURITY SHIELD
====================================================================================
Deskripsi : Lapisan pertahanan global untuk melindungi aset, API, dan server
            dari serangan DDoS, XSS, Clickjacking, dan akses ilegal.
====================================================================================
"""
import time
import logging
from typing import List

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger("baba.security")

# ==============================================================================
# 1. KONFIGURASI PINTU GERBANG (CORS)
# ==============================================================================
def setup_cors(app: FastAPI):
    """
    Mengatur siapa saja yang boleh berinteraksi dengan API ini dari luar.
    Saat production, ubah ALLOWED_ORIGINS ke domain web/mini app BABA.
    """
    ALLOWED_ORIGINS = [
        "*", # TODO: Ganti dengan domain asli (contoh: "https://babaparfumecambodia.com") saat live di VPS
    ]
    
    app.add_middleware(
        CORSMiddleware,
        allow_origins=ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Requested-With"],
    )
    logger.info("🛡️ [SECURITY] CORS Policy diaktifkan.")

# ==============================================================================
# 2. HELM BAJA (SECURITY HEADERS MIDDLEWARE)
# ==============================================================================
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Menyuntikkan header keamanan HTTP standar industri ke setiap response.
    Melindungi aset dan mencegah browser mengeksekusi kode berbahaya.
    """
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        
        # Mencegah MIME-Sniffing (Memaksa browser patuh pada tipe file asli)
        response.headers["X-Content-Type-Options"] = "nosniff"
        
        # Mencegah Clickjacking (Web BABA tidak bisa di-embed di iFrame web phising)
        response.headers["X-Frame-Options"] = "DENY"
        
        # Filter XSS bawaan browser diaktifkan
        response.headers["X-XSS-Protection"] = "1; mode=block"
        
        # Memaksa koneksi HTTPS selama 1 tahun penuh (Strict Transport Security)
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        
        # Mencegah web membocorkan dari mana user berasal (Referrer-Policy)
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        
        return response

# ==============================================================================
# 3. PENJAGA PINTU (RATE LIMITER & ANTI-SPAM MIDDLEWARE)
# ==============================================================================
class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Sistem In-Memory Rate Limiter. 
    Mencegah DDoS ringan dan Brute-Force dengan membatasi jumlah request per IP.
    """
    def __init__(self, app: FastAPI, max_requests: int = 150, window_seconds: int = 60):
        super().__init__(app)
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.ip_records = {} # Menyimpan riwayat jejak IP di memory RAM

    async def dispatch(self, request: Request, call_next):
        # Ambil IP pengunjung
        client_ip = request.client.host if request.client else "Unknown"
        
        # Jangan limit untuk akses aset static agar web loading cepat
        if request.url.path.startswith("/static/"):
            return await call_next(request)

        current_time = time.time()

        # Bersihkan riwayat request yang sudah lewat batas waktu (window_seconds)
        record = self.ip_records.get(client_ip, [])
        record = [t for t in record if current_time - t < self.window_seconds]

        # Cek apakah IP ini barbar / melebihi batas request
        if len(record) >= self.max_requests:
            logger.warning(f"🚨 [SECURITY] Serangan Spam terdeteksi dari IP: {client_ip}")
            return JSONResponse(
                status_code=429,
                content={
                    "status": "error", 
                    "message": "Terlalu banyak permintaan. Sistem mengunci akses Anda sementara."
                }
            )

        # Catat jejak waktu request ini
        record.append(current_time)
        self.ip_records[client_ip] = record

        return await call_next(request)

# ==============================================================================
# 4. MASTER SWITCH (EKSEKUTOR GLOBAL)
# ==============================================================================
def apply_enterprise_security(app: FastAPI):
    """
    Fungsi master yang dipanggil di main.py untuk menyalakan semua sistem keamanan.
    Urutan middleware SANGAT PENTING. Jangan diubah.
    """
    # 1. Pasang CORS pertama kali
    setup_cors(app)
    
    # 2. Pasang Helm Baja Headers
    app.add_middleware(SecurityHeadersMiddleware)
    
    # 3. Pasang Penjaga Anti-Spam (Batas 200 request per 60 detik)
    app.add_middleware(RateLimitMiddleware, max_requests=200, window_seconds=60)
    
    logger.info("🛡️ [SECURITY] Enterprise Shield berhasil dipasang ke sistem utama.")