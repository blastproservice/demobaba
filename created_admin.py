import os
from dotenv import load_dotenv
from passlib.context import CryptContext

# Import koneksi Supabase lu
try:
    from database import supabase
except ImportError:
    supabase = None

# Muat variabel dari .env
load_dotenv()

# Inisialisasi alat enkripsi standar Enterprise (Bcrypt)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def create_super_admin():
    print("⏳ [SYSTEM] Memulai proses inisiasi Super Admin...")

    if not supabase:
        print("❌ [ERROR] Koneksi Supabase terputus. Pastikan database.py aman.")
        return

    # Tarik data dari .env biar profesional dan aman
    username = os.getenv("ADMIN_USER")
    password = os.getenv("ADMIN_PASS")

    if not username or not password:
        print("❌ [ERROR] Kredensial ADMIN_USER atau ADMIN_PASS tidak ditemukan di .env!")
        return

    print(f"🔍 [INFO] Menemukan kredensial untuk user: {username}")

    try:
        # Cek apakah akun sudah pernah dibuat sebelumnya
        existing_admin = supabase.table("admins").select("username").eq("username", username).execute()
        
        if existing_admin.data:
            print(f"⚠️ [INFO] Admin '{username}' sudah eksis di database. Skip proses.")
            return

        # Enkripsi password secara mutlak
        hashed_password = pwd_context.hash(password)

        # Siapkan payload data
        payload = {
            "username": username,
            "password_hash": hashed_password,
            "full_name": "Dewa BABA (Super Admin)",
            "role": "super_admin"
        }

        # Eksekusi injeksi ke Supabase
        supabase.table("admins").insert(payload).execute()
        
        print("✅ [SUCCESS] Akun Super Admin berhasil ditanamkan di database!")
        print(f"👤 Username : {username}")
        print(f"🔑 Password : (Diambil dengan aman dari .env)")
        print("🚀 Silakan login di Portal Admin BABA sekarang.")

    except Exception as e:
        print(f"❌ [ERROR] Terjadi kegagalan sistem saat injeksi data: {e}")

if __name__ == "__main__":
    create_super_admin()