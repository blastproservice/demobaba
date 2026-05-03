# BABA Parfume Backend (demobaba)

Backend monolith berbasis **FastAPI + Jinja2 + Supabase** untuk operasional toko BABA Parfume.

Dokumen ini disusun dari kode terbaru di repo ini agar struktur proyek, endpoint, dan skema SQL konsisten dengan implementasi saat ini.

---

## 1) Ringkasan Arsitektur

- **Entry point aplikasi:** `main.py`.
- **Routing modular:**
  - `routers/customer/store.py` untuk halaman customer + API customer.
  - `routers/admin/*.py` untuk panel admin dan API admin.
- **Database:** Supabase PostgreSQL melalui `database.py`.
- **Template rendering:** Jinja2 di folder `templates/`.
- **Static assets:** folder `static/`.
- **Integrasi opsional:** Telegram bot (`bot.py`) dan AI assistant (`ai_agent.py`).

Karakter sistem:
- Server-rendered app (bukan SPA React/Next).
- Admin dashboard via Jinja template.
- API internal `/api/v1/*` dipakai frontend (Alpine.js pada template).

---

## 2) Struktur Proyek

```text
/workspace/demobaba
├── main.py
├── database.py
├── ai_agent.py
├── bot.py
├── created_admin.py
├── requirements.txt
├── readme.md
├── routers/
│   ├── common.py
│   ├── dependencies.py
│   ├── schemas.py
│   ├── customer/
│   │   └── store.py
│   └── admin/
│       ├── auth.py
│       ├── dashboard.py
│       ├── stock.py
│       ├── orders.py
│       ├── customers.py
│       ├── settings.py
│       ├── staff.py
│       ├── cs_management.py
│       ├── profile.py
│       └── finance.py
├── templates/
│   ├── customer/
│   │   ├── index.html
│   │   ├── profile.html
│   │   └── cs.html
│   └── admin/
│       ├── base.html
│       ├── login.html
│       ├── dashboard.html
│       ├── orders.html
│       ├── customers.html
│       ├── stock.html
│       ├── stock_belanja.html
│       ├── finance_aset.html
│       ├── finance_mutasi.html
│       ├── finance_report.html
│       ├── finance_debts.html
│       ├── cs_management.html
│       ├── staff.html
│       ├── profile.html
│       └── settings.html
└── static/
    ├── css/admin-dashboard.css
    └── img/Logo_BABA.png
```

---

## 3) Setup Environment

Buat file `.env` di root project.

```env
# Supabase
SUPABASE_URL=https://YOUR_PROJECT.supabase.co
SUPABASE_KEY=YOUR_SUPABASE_KEY

# Admin bootstrap (dipakai script created_admin.py)
ADMIN_USER=admin
ADMIN_PASS=your_secure_password

# Session / auth
SECRET_TOKEN=replace_with_long_random_secret
COOKIE_SECURE=false

# Telegram (opsional)
BOT_TOKEN=your_telegram_bot_token
ADMIN_ID=your_telegram_id

# AI Gemini (opsional)
GEMINI_API_KEY=your_gemini_api_key
```

Catatan:
- `database.py` akan memuat `.env` lalu inisialisasi client Supabase.
- Jangan hardcode credential ke source code.

---

## 4) Instalasi & Menjalankan

```bash
python -m venv .venv
source .venv/bin/activate  # Linux/macOS
pip install -r requirements.txt
python main.py
```

Akses default:
- Customer store: `http://localhost:8000/`
- Admin login: `http://localhost:8000/admin/login`
- Static assets: `http://localhost:8000/static/...`

> Catatan: docs Swagger dinonaktifkan di `main.py` (`docs_url=None`, `redoc_url=None`).

---

## 5) Peta Route Utama

### Customer
- `GET /` halaman store.
- `GET /profile` profil customer (berdasarkan `tele_id`).
- `GET /cs` halaman chat AI.
- `GET /api/v1/products/live` data produk aktif.
- `POST /api/v1/checkout` proses checkout.
- `GET /api/v1/chat/history`
- `POST /api/v1/chat/send`
- `POST /api/v1/chat/reset`
- `POST /api/v1/chat/feedback`

### Admin
- Auth: `/admin/login`, `/admin/logout`
- Dashboard: `/admin`, `/admin/`
- Orders: `/admin/orders`, `/admin/update-order-status`, `/admin/orders/delete/{order_id}`
- Stock: `/admin/stock`, `/admin/stock/belanja`, `/admin/add-product`, `/admin/stock/edit/{pid}`
- Procurement API: `POST /admin/api/v1/stock/belanja/process`
- Customers: `/admin/customers`, `/admin/customers/edit/{cid}`
- Staff: `/admin/staff` + endpoint `/staff/api/*`
- CS Management: `/admin/cs`, `/admin/api/v1/admin/cs/*`
- Settings: `/admin/settings`, `/admin/settings/update`

---

## 6) Skema Database (SQL)

Berikut baseline SQL yang mencerminkan tabel-tabel yang dipakai di kode saat ini.

```sql
-- UUID helper
create extension if not exists "pgcrypto";

-- 1) master admin
create table if not exists admins (
  id uuid primary key default gen_random_uuid(),
  username text unique not null,
  password_hash text not null,
  full_name text,
  role text not null default 'cs',
  is_active boolean not null default true,
  created_at timestamptz not null default now()
);

-- 2) store settings singleton (id=1)
create table if not exists store_settings (
  id int primary key,
  store_name text,
  admin_whatsapp text,
  checkout_message text,
  updated_at timestamptz not null default now()
);

-- 3) category & product
create table if not exists categories (
  id bigserial primary key,
  name text not null,
  created_at timestamptz not null default now()
);

create table if not exists products (
  id bigserial primary key,
  category_id bigint references categories(id) on delete set null,
  name text not null,
  tagline text,
  description text,
  image_url text,
  original_price numeric(14,2) not null default 0,
  discounted_price numeric(14,2) not null default 0,
  stock_quantity int not null default 0,
  tags text[] default '{}',
  top_notes text[] default '{}',
  heart_notes text[] default '{}',
  base_notes text[] default '{}',
  longevity text,
  recommendation text,
  is_active boolean not null default true,
  created_at timestamptz not null default now()
);

-- 4) customer & orders
create table if not exists customers (
  id uuid primary key default gen_random_uuid(),
  telegram_id bigint unique not null,
  username text,
  full_name text,
  default_address text,
  total_orders int not null default 0,
  total_spent numeric(14,2) not null default 0,
  created_at timestamptz not null default now()
);

create table if not exists orders (
  id uuid primary key default gen_random_uuid(),
  order_number text unique not null,
  customer_id uuid references customers(id) on delete set null,
  shipping_address text,
  total_amount numeric(14,2) not null default 0,
  status text not null default 'Menunggu Pembayaran',
  order_source text,
  payment_method text,
  receipt_number text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists order_items (
  id bigserial primary key,
  order_id uuid not null references orders(id) on delete cascade,
  product_id bigint references products(id) on delete set null,
  quantity int not null,
  price_at_time numeric(14,2) not null,
  created_at timestamptz not null default now()
);

-- 5) finance
create table if not exists finance_accounts (
  id bigserial primary key,
  bank_name text not null,
  account_number text,
  currency text not null default 'IDR',
  current_balance numeric(14,2) not null default 0,
  is_active boolean not null default true,
  created_at timestamptz not null default now()
);

create table if not exists finance_categories (
  id bigserial primary key,
  category_name text not null,
  transaction_type text not null, -- IN / OUT
  created_at timestamptz not null default now()
);

create table if not exists finance_mutations (
  id bigserial primary key,
  account_id bigint references finance_accounts(id) on delete set null,
  category_id bigint references finance_categories(id) on delete set null,
  transaction_type text not null, -- IN / OUT
  amount numeric(14,2) not null,
  description text,
  reference_order_id uuid references orders(id) on delete set null,
  created_at timestamptz not null default now()
);

-- 6) procurement & stock logs
create table if not exists stock_purchases (
  id bigserial primary key,
  supplier_name text,
  account_id bigint references finance_accounts(id) on delete set null,
  total_amount numeric(14,2) not null default 0,
  created_at timestamptz not null default now()
);

create table if not exists stock_purchase_items (
  id bigserial primary key,
  purchase_id bigint not null references stock_purchases(id) on delete cascade,
  product_id bigint references products(id) on delete set null,
  quantity int not null,
  unit_cost numeric(14,2) not null,
  created_at timestamptz not null default now()
);

create table if not exists stock_logs (
  id bigserial primary key,
  product_id bigint references products(id) on delete set null,
  change_type text not null, -- IN / OUT / RESTORE
  quantity int not null,
  note text,
  reference_order_id uuid references orders(id) on delete set null,
  created_at timestamptz not null default now()
);

-- 7) AI chat
create table if not exists ai_chat_sessions (
  id bigserial primary key,
  telegram_id bigint not null,
  is_active boolean not null default true,
  created_at timestamptz not null default now()
);

create table if not exists ai_chat_messages (
  id bigserial primary key,
  session_id bigint not null references ai_chat_sessions(id) on delete cascade,
  role text not null, -- user / model / admin
  content text not null,
  created_at timestamptz not null default now()
);

create table if not exists ai_feedbacks (
  id bigserial primary key,
  telegram_id bigint,
  rating int,
  complaint text,
  created_at timestamptz not null default now()
);

-- indeks rekomendasi
create index if not exists idx_products_active on products(is_active);
create index if not exists idx_orders_status on orders(status);
create index if not exists idx_orders_customer on orders(customer_id);
create index if not exists idx_mutations_reference_order on finance_mutations(reference_order_id);
create index if not exists idx_chat_session_telegram on ai_chat_sessions(telegram_id);
```

> Penting: SQL di atas adalah **baseline kompatibel kode**. Jika DB existing sudah berjalan, sesuaikan migrasi secara bertahap (ALTER) agar tidak merusak data produksi.

---

## 7) Alur Bisnis Inti

### Checkout customer
1. Upsert customer by `telegram_id`.
2. Insert header order + item order.
3. Potong `products.stock_quantity`.
4. Kirim notifikasi Telegram (jika bot aktif).

### Update status order admin
- Saat status diproses/selesai: bisa trigger mutasi keuangan (`finance_mutations`) dan update saldo akun.
- Saat status dibatalkan: restore stok, dan catat mutasi keluar/refund jika sebelumnya sudah ada pemasukan.

### Procurement (belanja stok)
- Validasi saldo akun keuangan.
- Insert purchase + purchase items.
- Tambah stok produk & log stok.
- Kurangi saldo akun + catat mutasi OUT.

---

## 8) Catatan Operasional

- `docs_url` dan `redoc_url` dinonaktifkan.
- CORS saat ini terbuka `*` (disarankan dibatasi di production).
- Error 401 diarahkan ke `/admin/login` oleh exception handler global.
- Jika Supabase down/tidak terhubung, beberapa route merespons fallback/error 503.

---

## 9) Rekomendasi Pengembangan Lanjut

- Pisahkan shared logic `orders` & `finance` yang masih mirip agar tidak duplikasi.
- Tambahkan migration tooling (mis. Alembic / SQL migration scripts).
- Tambahkan test otomatis untuk alur kritis: checkout, update status order, procurement.
- Tambahkan hardening security: CSRF untuk form admin, cookie policy ketat, serta audit log admin action.

---

## 10) Lisensi & Kontribusi

Belum ada file lisensi eksplisit di repo ini. Jika akan open-source/public, tambahkan LICENSE dan CONTRIBUTING.md.
