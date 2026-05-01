import os
from dotenv import load_dotenv
from supabase import create_client, Client

# Ini buat nyuruh Python baca file .env lu
load_dotenv()

# Ngambil URL dan KEY rahasia dari .env
url: str = os.getenv("SUPABASE_URL")
key: str = os.getenv("SUPABASE_KEY")

# Bikin mesin koneksi ke Supabase
try:
    supabase: Client = create_client(url, key)
    print("Berhasil connect ke brankas Supabase!")
except Exception as e:
    print(f"Gagal connect ke Supabase: {e}")