# DemoBaba (BABA Parfume Enterprise Backend)

Backend monolith berbasis **FastAPI + Jinja2 + Supabase** untuk operasional toko parfum, dashboard admin, CRM automation, dan integrasi Telegram Bot.

---

## 1. Deskripsi Proyek

DemoBaba adalah sistem backend terintegrasi untuk:

- **Customer storefront** (halaman katalog, checkout, profil, AI customer support).
- **Admin backoffice** (dashboard operasional, order management, stock/inventory, finance, settings, staff).
- **CRM automation** (MTProto session manager, template manager, auto-reply AI, dan broadcast campaign scheduler).
- **Telegram bot operations** (notification bridge + command bot).

### Tujuan proyek

- Menyatukan alur jual-beli, CRM, dan komunikasi customer di satu engine.
- Menyediakan panel admin server-rendered yang ringan tanpa SPA frontend kompleks.
- Menyediakan fondasi automasi pemasaran via Telegram.

### Target pengguna

- Tim operasional/admin BABA Parfume.
- Tim marketing/CS yang mengelola campaign dan customer engagement.
- Developer internal yang maintenance backend FastAPI + Supabase.

---

## 2. Tech Stack

| Layer | Teknologi |
|---|---|
| Backend Framework | FastAPI, Starlette |
| Templating/UI server-rendered | Jinja2, HTML, Alpine.js (di template) |
| Database | Supabase (PostgreSQL) |
| Auth & Security | Cookie-based admin session, Passlib (bcrypt), custom middleware security |
| Bot & Messaging | Aiogram (Telegram Bot API), Telethon (MTProto) |
| Scheduling/Automation | APScheduler |
| AI Integration | Google Gemini (`google-genai`) via `ai_agent.py` & `ai_mtproto.py` |
| HTTP Client | HTTPX / AIOHTTP |
| Runtime | Uvicorn |
| Config | python-dotenv |

> Catatan: Swagger/ReDoc dinonaktifkan pada app (`docs_url=None`, `redoc_url=None`).

---

## 3. Struktur Folder Proyek

```text
.
├── main.py
├── database.py
├── security.py
├── bot.py
├── ai_agent.py
├── ai_mtproto.py
├── created_admin.py
├── requirements.txt
├── schema.sql
├── routers/
│   ├── common.py
│   ├── dependencies.py
│   ├── schemas.py
│   ├── admin/
│   │   ├── __pycache__/
│   │   ├── __init__.py
│   │   ├── auth.py
│   │   ├── dashboard.py
│   │   ├── stock.py
│   │   ├── orders.py
│   │   ├── customers.py
│   │   ├── settings.py
│   │   ├── staff.py
│   │   ├── cs_management.py
│   │   ├── profile.py
│   │   └── finance.py
│   ├── customer/
│   │   ├── __init__.py
│   │   ├── cs.py
│   │   ├── profile.py
│   │   └── store.py
│   └── crm/
│       ├── __init__.py
│       ├── auto_reply.py
│       ├── broadcast.py
│       ├── dashboard.py
│       ├── sessions.py
│       └──templates.py
├── templates/
│   ├── admin/
│   │   ├── base.html
│   │   ├── login.html
│   │   ├── dashboard.html
│   │   ├── orders.html
│   │   ├── customers.html
│   │   ├── stock.html
│   │   ├── stock_belanja.html
│   │   ├── stock_mutation.html
│   │   ├── finance_aset.html
│   │   ├── finance_mutasi.html
│   │   ├── finance_report.html
│   │   ├── finance_debts.html
│   │   ├── cs_management.html
│   │   ├── staff.html
│	│   ├── profile.html
│   │   └── settings.html
│   ├── customer/
│   │   ├── index.html
│   │   ├── base.html
│   │   ├── profile.html
│   │   ├── cs.html
│   │   ├── _testimoni.html
│   │   ├── _hero.html
│   │   └── _faq.html
│   └── crm/
│       ├── auto_reply.html
│       ├── templates.html
│       ├── dashboard.html
│       └── broadcast.html
└── static/
    ├── css/
    └── img/
	

```

### Penjelasan folder utama

- `main.py`: bootstrap FastAPI, register middleware security, mount static, include semua router, dan start lifecycle task Telegram bot.
- `routers/admin/`: endpoint dan page admin (auth, dashboard, stock, orders, customers, finance, settings, staff, profile, cs management).
- `routers/customer/`: endpoint customer-facing (storefront, checkout, profile, AI chat).
- `routers/crm/`: fitur CRM enterprise (dashboard, broadcast, auto-reply, templates, MTProto sessions).
- `templates/`: Jinja2 template untuk admin/customer/crm.
- `static/`: asset CSS & image.
- `database.py`: inisialisasi client Supabase dari `.env`.
- `security.py`: CORS, security headers, in-memory rate limiter.
- `schema.sql`: snapshot schema PostgreSQL/Supabase yang dipakai aplikasi.

---

## 4. Instalasi & Setup

## Prasyarat

- Python 3.10+ (disarankan 3.11/3.12).
- Akses ke project Supabase.
- (Opsional) kredensial Telegram Bot API & MTProto API.

## Langkah setup lokal

```bash
git clone <repo-url>
cd demobaba
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Buat file `.env` lalu isi variabel (lihat bagian Environment Variables).

Jalankan server:

```bash
python main.py
```

Akses:

- Customer store: `http://localhost:8000/`
- Admin login: `http://localhost:8000/admin/login`

## Bootstrap admin awal

Jika tabel `admins` masih kosong:

```bash
python created_admin.py
```

Script ini membaca `ADMIN_USER` dan `ADMIN_PASS` dari `.env` lalu menambahkan akun admin ke database.

---

## 5. Environment Variables

Berikut variabel env yang dipakai codebase saat ini:

| Variable | Wajib | Fungsi |
|---|---|---|
| `SUPABASE_URL` | Ya | URL project Supabase |
| `SUPABASE_KEY` | Ya | Service/API key Supabase untuk query aplikasi |
| `ADMIN_USER` | Opsional (bootstrap) | Username untuk `created_admin.py` |
| `ADMIN_PASS` | Opsional (bootstrap) | Password untuk `created_admin.py` |
| `BOT_TOKEN` | Wajib jika bot aktif | Token Telegram bot (Aiogram) |
| `ADMIN_ID` | Opsional/fitur bot | Telegram ID admin utama untuk notifikasi/otorisasi tertentu |
| `WEB_APP_URL` | Opsional | URL web app yang dipakai bot |
| `API_ID` | Wajib untuk CRM MTProto | Telegram API ID (Telethon) |
| `API_HASH` | Wajib untuk CRM MTProto | Telegram API hash (Telethon) |
| `WHITELIST_GROUPS` | Opsional | Daftar ID grup (comma-separated) untuk auto-reply engine |
| `GEMINI_API_KEY` | Opsional | API key Google Gemini untuk AI recommendation/reply |

Contoh `.env`:

```env
SUPABASE_URL=https://xxxx.supabase.co
SUPABASE_KEY=your_supabase_key

ADMIN_USER=admin
ADMIN_PASS=strong_password

BOT_TOKEN=123456:ABCDEF...
ADMIN_ID=123456789
WEB_APP_URL=https://your-web-app-url

API_ID=1234567
API_HASH=xxxxxxxxxxxxxxxxxxxxxxxxx
WHITELIST_GROUPS=-10012345,-10067890

GEMINI_API_KEY=your_gemini_api_key
```

---

## 6. Database Documentation

## Jenis database

- **PostgreSQL (via Supabase)**.
- Akses database dilakukan melalui Supabase Python client (`supabase.table(...).select()/insert()/update()/delete()`).

## Sumber schema

- `schema.sql` adalah snapshot struktur tabel untuk referensi pengembangan.
- Beberapa query aplikasi melakukan fallback jika table/kolom tertentu tidak tersedia (terutama area CRM/legacy).

## Entitas inti dan relasi utama

### Master admin

- `admins`: akun admin panel.
  - Dipakai oleh auth login dan relasi ke modul CRM/finance.

### Catalog & commerce

- `categories` → `products` (`products.category_id` FK ke `categories.id`).
- `customers` → `orders` (`orders.customer_id` FK ke `customers.id`).
- `orders` → `order_items` (`order_items.order_id` FK ke `orders.id`).
- `products` → `order_items` (`order_items.product_id` FK ke `products.id`).

### Inventory & procurement

- `stock_logs` relasi ke `products` (`stock_logs.product_id`).
- `stock_purchases` dan `stock_purchase_items` (procurement/pembelanjaan stock).

### Finance

- `finance_accounts`, `finance_categories`.
- `finance_mutations` terkait account/category dan dapat mereferensi order/purchase/debt.
- `finance_debts` + riwayat pembayaran (via mutasi/debt logs sesuai implementasi module finance).

### CRM & AI

- `crm_telegram_sessions` (session string Telethon per admin).
- `crm_templates` (template pesan/target).
- `crm_campaigns` + `crm_blast_logs` (campaign scheduler dan hasil kirim).
- `crm_auto_replies` (keyword/reply mapping).
- `ai_chat_sessions`, `ai_chat_messages`, `ai_feedbacks` (riwayat AI chat customer).

### Loyalty/Testimonial/Settings (tergantung fitur aktif)

- `loyalty_logs`, `testimonials`, `store_settings`, dan tabel reward/config lain yang dipakai modul settings.

## Indexing & constraint penting (berdasarkan schema)

- Unique: `admins.username`, `customers.telegram_id`, `orders.order_number`, `categories.slug`, `crm_telegram_sessions.phone_number`.
- Foreign key memastikan integritas untuk order item, mutasi ke account/category, dan campaign ke template/session.

## Contoh query operasional

```sql
-- Ambil order terbaru
SELECT order_number, total_amount, status, created_at
FROM orders
ORDER BY created_at DESC
LIMIT 20;

-- Rekap mutasi kas per account
SELECT account_id, SUM(amount) AS total
FROM finance_mutations
GROUP BY account_id;
```

---

## 7. API Documentation (Endpoint Utama)

> Catatan: Endpoint di bawah adalah endpoint utama/sering dipakai. Seluruh definisi aktual ada di file router masing-masing.

## Customer

| Method | URL | Auth | Keterangan |
|---|---|---|---|
| GET | `/` | No | Halaman store |
| GET | `/profile` | No | Halaman profil customer |
| GET | `/cs` | No | Halaman AI customer service |
| GET | `/api/v1/products/live` | No | Ambil produk aktif |
| POST | `/api/v1/testimoni/submit` | No | Kirim testimonial |
| POST | `/api/v1/checkout` | No | Checkout order |
| GET | `/api/v1/profile/{tele_id}` | No | Data profil by Telegram ID |
| POST | `/api/v1/profile/update` | No | Update profil customer |
| POST | `/api/v1/profile/redeem` | No | Redeem reward/points |
| POST | `/api/v1/chat/send` | No | Kirim pesan ke AI |
| POST | `/api/v1/chat/reset` | No | Reset chat session |
| POST | `/api/v1/chat/feedback` | No | Simpan feedback AI |
| GET | `/api/v1/chat/history` | No | Ambil riwayat chat |

## Admin

| Method | URL | Auth | Keterangan |
|---|---|---|---|
| GET | `/admin/login` | No | Halaman login |
| POST | `/admin/login` | No | Proses login + set cookie |
| GET | `/admin/logout` | Cookie | Logout |
| GET | `/admin` | Cookie | Dashboard |
| GET | `/admin/orders` | Cookie | List order |
| POST | `/admin/update-order-status` | Cookie | Ubah status order |
| GET | `/admin/orders/delete/{order_id}` | Cookie | Hapus order |
| GET | `/admin/stock` | Cookie | List produk/stok |
| POST | `/admin/add-product` | Cookie | Tambah produk |
| POST | `/admin/stock/edit/{pid}` | Cookie | Edit produk |
| POST | `/admin/api/v1/stock/belanja/process` | Cookie | Proses pembelian stok |
| POST | `/admin/api/v1/stock/adjustment` | Cookie | Adjustment stok |
| GET | `/admin/customers` | Cookie | List customer |
| POST | `/admin/customers/sync` | Cookie | Sync customer |
| POST | `/admin/customers/bulk-message` | Cookie | Blast message customer |
| GET | `/admin/finance/aset` | Cookie | Finance assets |
| POST | `/admin/finance/transaction` | Cookie | Catat transaksi |
| POST | `/admin/finance/transfer` | Cookie | Transfer antar akun |
| GET | `/admin/settings` | Cookie + role | Konfigurasi aplikasi |
| GET | `/staff` | Cookie + super_admin | Manajemen staff |

## CRM

| Method | URL | Auth | Keterangan |
|---|---|---|---|
| GET | `/admin/crm/dashboard` | Cookie | Dashboard CRM |
| GET | `/admin/crm/api/stats` | Cookie | Statistik CRM realtime |
| POST | `/admin/api/crm/mtproto/send_code` | Cookie | Kirim OTP MTProto |
| POST | `/admin/api/crm/mtproto/verify` | Cookie | Verifikasi OTP |
| POST | `/admin/api/crm/mtproto/verify_password` | Cookie | Verifikasi 2FA |
| POST | `/admin/api/crm/mtproto/logout` | Cookie | Logout session MTProto |
| GET | `/admin/crm/templates` | Cookie | Halaman template |
| GET | `/admin/crm/templates/list` | Cookie | Data template |
| POST | `/admin/crm/templates/save` | Cookie | Simpan template |
| GET | `/admin/crm/auto-reply` | Cookie | Halaman auto reply |
| POST | `/admin/crm/auto-reply/api/save` | Cookie | Simpan aturan auto reply |
| GET | `/admin/crm/broadcast` | Cookie | Halaman broadcast |
| POST | `/admin/crm/broadcast/api/launch` | Cookie | Launch campaign |

## Format response API

Mayoritas endpoint API menggunakan pola:

```json
{"status": "success", "message": "...", "data": {...}}
```

Error umumnya:

```json
{"status": "error", "message": "..."}
```

---

## 8. Authentication Flow

- Login admin melalui `POST /admin/login`.
- Sistem memverifikasi `username` + `password_hash` (bcrypt) pada tabel `admins`.
- Jika valid, server meng-set cookie `baba_admin_session` (HTTPOnly, max_age 86400).
- Endpoint admin menggunakan dependency guard (`get_current_admin`/role checker) sesuai router.
- Logout menghapus cookie session.

### Role/permission

Role yang digunakan di codebase: `super_admin`, `marketing`, `oprasional`, `cs`.

---

## 9. Feature Documentation

## Customer Features

- Katalog produk aktif.
- Checkout order.
- Profil customer & redeem reward.
- AI chat + history + feedback.

## Admin Features

- Login/logout admin panel.
- Dashboard metrik bisnis.
- CRUD produk dan manajemen stok + mutasi.
- Order processing (status/update/delete).
- Customer management (sync/edit/export/bulk message).
- Finance module (aset, mutasi, transfer, debt, reporting, csv export).
- Settings & moderation testimonial/reward.
- Staff management (add/update/reset password/delete).

## CRM Features

- MTProto login flow (OTP + 2FA).
- Template management (message/target groups).
- Auto reply engine (rule-based + AI integration).
- Broadcast campaign manager (once/daily/interval, pause/resume/stop, scheduler).
- CRM analytics dashboard.

---

## 10. Deployment

Repo ini belum menyediakan Dockerfile/CI pipeline bawaan. Deployment umum yang direkomendasikan:

1. Siapkan server Linux + Python runtime.
2. Set environment variables production di secret manager/systemd.
3. Install dependency via `pip install -r requirements.txt`.
4. Jalankan via process manager (mis. `gunicorn`/`uvicorn` + `systemd`).
5. Pasang reverse proxy Nginx.
6. Aktifkan HTTPS.

Contoh command production sederhana:

```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

> Penting: `main.py` lifecycle akan menjalankan Telegram bot task. Pastikan env bot valid jika fitur bot diaktifkan.

---

## 11. Scripts / Commands Penting

Karena proyek tidak menggunakan `package.json`, command utama berbasis Python:

| Command | Fungsi |
|---|---|
| `python main.py` | Menjalankan FastAPI app (dengan reload jika dijalankan dari blok `__main__`) |
| `python created_admin.py` | Membuat akun admin awal dari env |

Opsional (jika memakai uvicorn langsung):

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

---

## 12. Best Practices & Architecture Notes

- Tambah fitur via router modular (`routers/admin`, `routers/customer`, `routers/crm`), hindari menumpuk logic di `main.py`.
- Pisahkan page rendering (HTMLResponse/template) dan endpoint API JSON.
- Reuse helper di `routers/common.py` untuk response standar dan helper template.
- Gunakan pattern `try/except Exception as e` + logging pada operasi DB/network.
- Hindari hardcode credential; wajib melalui `.env`.
- Untuk fitur lintas modul, cek dependency auth/role di `routers/dependencies.py`.

---

## 13. Catatan Penting

- Dokumentasi ini sinkron dengan struktur dan router yang ada di codebase saat ini.
- Jika menambah router/tabel/env baru, update README ini pada commit yang sama agar dokumentasi tetap akurat.
