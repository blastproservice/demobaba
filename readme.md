# 🌟 BABA Parfume Enterprise System 🌟
**Sistem ERP, CRM, & Telegram Mini-App Terintegrasi Berbasis AI**

![Version](https://img.shields.io/badge/Version-4.0.0--Enterprise-goldenrod?style=for-the-badge)
![Python](https://img.shields.io/badge/Python-3.9+-blue?style=for-the-badge&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-009688?style=for-the-badge&logo=fastapi&logoColor=white)
![Supabase](https://img.shields.io/badge/Supabase-PostgreSQL-3ECF8E?style=for-the-badge&logo=supabase&logoColor=white)
![TailwindCSS](https://img.shields.io/badge/Tailwind_CSS-3.4-38B2AC?style=for-the-badge&logo=tailwind-css&logoColor=white)
![Alpine.js](https://img.shields.io/badge/Alpine.js-3.x-8BC0D0?style=for-the-badge&logo=alpine.js&logoColor=white)

---

## 📖 Executive Summary
**BABA Parfume Enterprise System** adalah aplikasi monolith *end-to-end* yang dirancang khusus untuk mengelola operasional bisnis parfum lintas negara (Indonesia - Kamboja). Sistem ini menggabungkan kekuatan **Backend API**, **Sistem Manajemen Keuangan (Ledger)**, **Manajemen Inventaris**, **Customer Relationship Management (CRM)**, dan **Kecerdasan Buatan (AI Assistant)**.

Dibangun dengan arsitektur **Mobile-First** untuk sisi pelanggan via Telegram Mini App, dan **Enterprise Desktop Dashboard** untuk sisi Administrator.

---

## 🚀 Fitur Unggulan (Core Features)

### 1. 🛒 Customer Telegram Mini-App
Aplikasi pelanggan yang berjalan mulus di dalam Telegram WebApp tanpa perlu install aplikasi tambahan.
* **Smart Catalog:** Pencarian produk real-time, filter kategori, dan pengurutan harga/stok.
* **Persistent Cart:** Keranjang belanja disimpan di `localStorage`, aman meskipun aplikasi ditutup.
* **Voucher Engine:** Sistem input kode promo (contoh: `BABA2026`) yang langsung memotong total tagihan.
* **Gamified Profile:** Halaman profil yang menampilkan *Pride Metrics* (Total Koleksi Botol) dan deteksi selera aroma (Taste Profiling).
* **Seamless Checkout:** Mendukung berbagai metode pembayaran lintas negara (BCA, ABA Bank Cambodia, Cash On Delivery).

### 2. 🤖 Mimin AI (Google Gemini Integration)
Customer Service otomatis berbasis kecerdasan buatan.
* **Context-Aware:** AI mengetahui produk apa saja yang sedang *Ready Stock* di database.
* **Personalized Recommendation:** AI membaca *Taste Profile* pelanggan dari riwayat pesanannya untuk memberikan rekomendasi parfum yang akurat.
* **Human Handoff:** Sesi obrolan AI direkam di database dan dapat dipantau (Sadap) atau diambil alih (Intercept) oleh Admin/CS secara *real-time*.

### 3. 📦 Manajemen Gudang & Pembelian (Procurement)
* **Real-time Stock Deduction:** Stok otomatis terpotong saat pelanggan melakukan *checkout*.
* **Purchase Order (PO) System:** Fitur pencatatan belanja stok dari *supplier* (kulakan). 
* **Smart Autocomplete:** Pembuatan nota belanja dilengkapi pencarian barang otomatis. Jika barang tidak ada, sistem akan mendaftarkannya sebagai inventaris baru.
* **Auto-Restock:** Jika pesanan pelanggan dibatalkan, sistem otomatis mengembalikan stok fisik ke gudang.

### 4. 💸 Enterprise Finance Engine (Sistem Keuangan Dewa)
Bukan sekadar pencatatan, melainkan mesin akuntansi berbasis **Double-Entry Ledger**.
* **Multi-Currency Wallets:** Mendukung pencatatan IDR (BCA/Jago) dan USD/KHR (ABA Bank / Laci Cash).
* **Cross-Currency Transfer (Pindah Kas):** Fitur memindahkan uang antar rekening dengan input *Exchange Rate* manual (Mendukung IDR <-> USD).
* **Automated Ledger:** Checkout pelanggan -> Otomatis mencatat Pemasukan (IN). Belanja PO -> Otomatis mencatat Pengeluaran (OUT). Refund Otomatis jika order dibatalkan.
* **P&L Statement (Laba Rugi):** Kalkulasi otomatis untuk Pendapatan, Harga Pokok Penjualan (HPP/COGS), Biaya Operasional (OpEx), dan Net Profit Margin. Dilengkapi fitur **Export PDF**.

### 5. 👮 Secure Admin Dashboard
* **Role-Based Access Control (RBAC):** Hak akses terbagi menjadi `super_admin`, `oprasional`, `marketing`, dan `cs`.
* **Encrypted Session:** Menggunakan sistem *Cookie* yang di-hash dengan algoritma `SHA-256` untuk mencegah *session hijacking*.
* **Telegram Background Bot:** Admin mendapatkan notifikasi *real-time* via Telegram jika ada pesanan baru atau perubahan status resi.

---

## 🏗️ Arsitektur Sistem (Tech Stack)

Sistem ini menggunakan pendekatan **Monolithic Modern** untuk kemudahan *deployment* (cocok untuk VPS / PaaS seperti Render atau Railway).

* **Backend Framework:** `FastAPI` (Python) - Dipilih karena asinkron (async), sangat cepat, dan memiliki auto-dokumentasi (Swagger UI).
* **Database:** `Supabase` (PostgreSQL) - Diakses melalui HTTP REST via `supabase-py`.
* **AI Engine:** `google-genai` - Menggunakan model Google Gemini 2.0 Flash untuk inferensi cepat.
* **Telegram Bot:** `aiogram` - Dijalankan sebagai *background task* di dalam *lifespan* FastAPI.
* **Frontend Engine:** `Jinja2` Templates.
* **Frontend UI/UX:** `TailwindCSS` (Styling), `Alpine.js` (Reaktivitas DOM & State Management), `Lucide` (Icons), `Chart.js` (Visualisasi Data).

---

## 📁 Struktur Direktori Proyek

```text
baba_parfume_project/
│
├── main.py                 # 🌟 CORE ENGINE: Entry point FastAPI, Routing, Middleware, Auth.
├── database.py             # Koneksi Supabase client.
├── bot.py                  # 🤖 Telegram Bot: Polling, Notifikasi background, Alarm.
├── ai_agent.py             # 🧠 Konfigurasi Google Gemini & Prompt Engineering BABA.
├── requirements.txt        # Daftar dependensi Python.
├── .env                    # Variabel lingkungan (API Keys, Database URL, dll).
│
├── static/                 # Aset Statis Publik
│   └── img/
│       └── Logo_BABA.png   # Logo Utama
│
└── templates/              # View Layer (HTML Jinja2)
    ├── admin/              # 🔐 PANEL ADMIN (ZONA TERBATAS)
    │   ├── base.html             # Master layout Admin (Sidebar, Navbar, Lucide, Alpine global).
    │   ├── dashboard.html        # Overview metrik bisnis, statistik singkat.
    │   ├── login.html            # Pintu gerbang keamanan berbasis role.
    │   ├── stock.html            # Manajemen inventaris produk (Tambah, Edit, Hapus).
    │   ├── stock_belanja.html    # Modul Procurement / Kulakan / PO dengan fitur Auto-restock.
    │   ├── orders.html           # CRM: Manajemen Pesanan & Perubahan Status Resi.
    │   ├── customers.html        # CRM: Direktori Pelanggan & LTV (Lifetime Value).
    │   ├── finance_aset.html     # FIN: Dompet, Rekening, dan Fitur Pindah Kas Lintas Mata Uang.
    │   ├── finance_mutasi.html   # FIN: Buku Besar (Ledger) dengan Live Filter Alpine.js.
    │   ├── finance_report.html   # FIN: Statement Laba/Rugi (P&L), Chart.js, Export PDF.
    │   ├── cs_management.html    # Modul Sadap & Intercept chat pelanggan dengan AI.
    │   ├── staff.html            # Manajemen akun karyawan (Khusus Super Admin).
    │   ├── profile.html          # Detail profil admin yang sedang login.
    │   └── settings.html         # Konfigurasi sistem web & toko.
    │
    └── customer/           # 📱 TELEGRAM MINI-APP (PUBLIC VIEW)
        ├── index.html            # Katalog utama, Cart system, Flash Sale, Checkout logic.
        ├── cs.html               # Antarmuka interaksi pengguna dengan AI Assistant BABA.
        └── profile.html          # Gamifikasi profil pengguna, analisis selera (Taste Profile).

🗄️ Skema Database (Supabase PostgreSQL)
Sistem menggunakan struktur database relasional yang saling mengikat. Berikut adalah topologi utamanya:

1. Entitas Core Bisnis
products: Menyimpan master data parfum (Nama, Kategori, Harga Coret, Harga Diskon, Stok, Notes Piramida Aroma, URL Gambar).

categories: Grup produk (Man, Woman, Unisex, dll).

customers: Direktori pelanggan yang terhubung dengan telegram_id.

2. Modul Penjualan (Orders)
orders: Menyimpan header transaksi pelanggan, status pesanan, alamat, dan metode pembayaran.

order_items: Rincian barang per pesanan. Di sinilah stok dipotong dari products.

3. Modul AI & Pelayanan
ai_chat_sessions: Mencatat aktivitas percakapan per user Telegram.

ai_chat_messages: Detail chat antara User, Model (AI), dan Admin (Intercept).

ai_feedbacks: Penilaian bintang (Rating) dan keluhan layanan.

4. Modul Keuangan & Pembelian (The Engine)
finance_accounts: Daftar Rekening/Dompet (BCA, ABA, Jago, Cash Laci). Menyimpan Saldo saat ini.

finance_categories: Kategori pembukuan (Tipe INCOME dan EXPENSE).

finance_mutations: BUKU BESAR (Ledger). Jantung akuntansi. Setiap pergerakan uang wajib dicatat di sini.

stock_purchases: Dokumen Purchase Order (PO) saat belanja barang.

stock_purchase_items: Rincian barang yang dibeli dari supplier.

stock_logs: Audit Trail (Riwayat) pergerakan keluar/masuk stok fisik.

5. Keamanan
admins: Akun staff dengan hashing password dan Role RBAC.

store_settings: Pengaturan nama toko, kontak admin, dan status bot (Global Toggle).

⚙️ Panduan Instalasi (Setup Guide)
Ikuti langkah-langkah ini untuk menjalankan BABA Enterprise System di mesin lokal atau server (VPS).

Prasyarat:
Python 3.9 atau lebih baru.

Akun Supabase (untuk Database).

Akun Google AI Studio (untuk API Key Gemini).

Bot Telegram (Dibuat melalui BotFather).

Langkah 1: Kloning Repositori
Bash
git clone [https://github.com/username/baba_parfume_project.git](https://github.com/username/baba_parfume_project.git)
cd baba_parfume_project
Langkah 2: Virtual Environment & Dependensi
Bash
# Buat virtual environment (Direkomendasikan)
python -m venv venv

# Aktivasi Venv (Windows)
venv\Scripts\activate
# Aktivasi Venv (Mac/Linux)
source venv/bin/activate

# Install semua kebutuhan paket
pip install -r requirements.txt
Langkah 3: Konfigurasi Environment (.env)
Buat file bernama .env di direktori root, lalu isi dengan kredensial berikut:

Ini, TOML
# ==========================================
# 1. DATABASE (SUPABASE)
# ==========================================
SUPABASE_URL=https://[PROJECT-ID].supabase.co
SUPABASE_KEY=eyJhbG...[YOUR_SUPABASE_ANON_KEY]

# ==========================================
# 2. TELEGRAM BOT
# ==========================================
BOT_TOKEN=1234567890:AAH...[YOUR_BOT_TOKEN]
ADMIN_ID=123456789  # Telegram ID Pemilik untuk Notif Order

# ==========================================
# 3. ARTIFICIAL INTELLIGENCE (GOOGLE GEMINI)
# ==========================================
GEMINI_API_KEY=AIzaSy...[YOUR_GEMINI_API_KEY]

# ==========================================
# 4. KEAMANAN SISTEM & AUTENTIKASI ADMIN
# ==========================================
ADMIN_USER=adminbaba         # Username Super Admin bawaan
ADMIN_PASS=B4baSultan2026!   # Password Super Admin
SECRET_TOKEN=R4h4s14_B4ng3T_Br3_2026
COOKIE_SECURE=false          # Set "true" jika menggunakan HTTPS (Production)
PORT=8000                    # Port uvicorn berjalan

Langkah 4: Jalankan Server BABA Engine

Web Customer (Mini App): Akses di http://localhost:8000/

Admin Panel: Akses di http://localhost:8000/admin

API Docs (Swagger): Akses di http://localhost:8000/api/docs

💡 Panduan Penggunaan Modul Khusus
1. Bagaimana Modul Keuangan Bekerja Otomatis?
Anda TIDAK PERLU memasukkan pendapatan secara manual jika pelanggan berbelanja dari Mini App.

Saat pesanan berstatus "Menunggu Pembayaran" -> Belum ada mutasi keuangan.

Saat Admin mengubah status pesanan menjadi "Diproses" atau "Selesai" melalui menu Orders, sistem Backend (lihat update_order_status di main.py) akan secara otomatis memotong pesanan, mendeteksi metode pembayaran, dan memasukkan uang nominal transaksi ke Buku Besar (Bank BCA, Jago, dsb).

Jika pesanan "Dibatalkan", sistem secara ajaib akan melakukan Rollback: Mengembalikan fisik barang ke rak, dan mencabut/refund uang dari Buku Besar jika sebelumnya sudah sempat diproses.

2. Fitur "Pindah Kas" (Cross-Currency)
Buka /admin/finance/aset. Jika Anda ingin memindahkan uang Cash Harian (IDR) untuk disimpan di ABA Bank (USD).

Klik tombol Pindah Kas.

Pilih sumber "Cash Laci", pilih tujuan "ABA Bank".

Kolom Rate / Kurs akan otomatis aktif (karena beda mata uang).

Masukkan nominal IDR, masukkan kurs saat ini (Misal: 15500), sistem otomatis menghitung berapa USD yang masuk ke ABA. Semua tercatat rapi di Mutasi!

3. Melatih AI dengan Taste Profile Customer
Sistem AI (ai_agent.py) akan menarik data "Aroma Favorit" dari Database. Jika pelanggan sering berbelanja varian "Baccarat" yang memiliki Tag SWEET dan WOODY, sistem prompt akan memberikan instruksi ke Google Gemini untuk menyarankan parfum dengan nuansa serupa jika pengguna bertanya di halaman /cs.

🛠️ Internal API References (Dipanggil oleh Alpine.js)
Frontend sangat mengandalkan API internal yang dilindungi dengan validasi Pydantic.

POST /api/v1/checkout: Memproses order pelanggan.

GET /api/v1/products/live: Menyuplai data produk terkini ke frontend tanpa membebani template rendering.

POST /api/v1/chat/send: Menjembatani pesan pengguna ke Google Gemini.

POST /api/v1/stock/belanja/process: Mesin pengolah Nota Pembelian (Logika: Kurangi Saldo -> Tambah Barang -> Insert Mutasi -> Insert Log).

POST /api/v1/finance/transfer: Mengelola pemindahan dana antar bank.

🔮 Roadmap Pengembangan (Future Updates)
Untuk versi selanjutnya, berikut adalah beberapa area yang dapat diperkaya:

Supabase Storage Integration: Mengganti input manual image_url pada produk dengan fitur unggah file (Multipart Form) langsung ke Bucket Supabase.

Native CSV Export: Menggunakan library pandas atau csv bawaan Python untuk memungkinkan Administrator mengunduh laporan Mutasi dan Laba Rugi dalam format .xlsx atau .csv.

Payment Gateway API: Integrasi dengan API Xendit (IDR) atau PayWay ABA (USD) untuk pengecekan mutasi dan pembaruan status resi pelanggan tanpa campur tangan Admin.

Stock Audit GUI: Membuat antarmuka visual (Tabel) untuk membaca data dari tabel stock_logs agar Admin dapat memantau jejak pergerakan stok harian.

🛡️ Lisensi & Hak Cipta
Proyek ini dilindungi oleh hak cipta BABA Parfume.
Dikembangkan untuk skala operasional tingkat dewa dengan efisiensi tinggi. "Membawa wangi signature ke seluruh Kamboja!" 🇰🇭✨

"Jangan pernah menghapus kode lama, tingkatkan dan perkayalah menjadi lebih dewa!" - BABA Dev Team.
        
