"""
====================================================================================
BABA PARFUME - MTPROTO AI AGENT (HUMANIZED ENTERPRISE V2.0)
====================================================================================
Deskripsi : Otak AI khusus untuk akun Telegram Admin (MTProto).
            Didesain 100% agar bertindak sebagai MANUSIA (Mimin BABA).
Fitur     : 
            - Advanced Mirroring (Meniru gaya ngetik lawan bicara dari history)
            - Deep Contextual Memory (Mengingat histori chat dari database)
            - Anti-AI Detection (Blokir Markdown, list kaku, dan bahasa robot)
            - Sales Closer (Fokus jualan, ramah, singkat, dan kasih opsi wangi)
            - Live Supabase Sync (Cek real-time dari tabel 'products' & 'categories')
====================================================================================
"""

import os
import re
import time
import logging
from typing import Dict, List, Optional

# Supabase Bridge
try:
    from database import supabase
except ImportError:
    supabase = None

# SDK GEMINI TERBARU (google.genai)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
ai_client = None
if GEMINI_API_KEY:
    try:
        from google import genai
        from google.genai import types
        ai_client = genai.Client(api_key=GEMINI_API_KEY)
    except Exception as e:
        print(f"❌ [GEMINI MTPROTO INIT ERROR]: {e}")

# ==============================================================================
# LOGGING SYSTEM
# ==============================================================================
class MtprotoLogger:
    def __init__(self):
        self.logger = logging.getLogger("baba.ai.mtproto")
        if not self.logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter('%(asctime)s | [MTPROTO_AI] %(message)s')
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)
            self.logger.setLevel(logging.INFO)
            
    def info(self, msg: str): self.logger.info(msg)
    def warning(self, msg: str): self.logger.warning(msg)
    def error(self, msg: str): self.logger.error(msg)

log = MtprotoLogger()
log.info("🧠 Membangkitkan Otak MTProto AI (Persona: Mimin BABA V2)...")

# ==============================================================================
# DATABASE & MEMORY MANAGER
# ==============================================================================
class MtprotoMemory:
    """Manajer memori khusus untuk MTProto dengan penarikan konteks panjang"""
    def __init__(self):
        self.k_cache = {"data": "", "last_fetched": 0.0}

    async def fetch_long_context(self, session_id: int, limit: int = 8) -> str:
        """Menarik history untuk memahami alur chat (dibatasi 8 agar AI tidak bingung)"""
        if not supabase: return ""
        try:
            # Ambil dari tabel ai_chat_messages sesuai schema
            res = supabase.table("ai_chat_messages") \
                .select("role, content") \
                .eq("session_id", session_id) \
                .order("created_at", desc=False) \
                .limit(limit) \
                .execute()
            
            context = ""
            for msg in (res.data or []):
                speaker = "Customer" if msg["role"] == "user" else "Gue (Mimin)"
                clean_msg = msg['content'].replace("[KEYWORD_REPLY]", "").strip()
                context += f"{speaker}: {clean_msg}\n"
            return context
        except Exception as e:
            log.error(f"Gagal menarik memori panjang: {e}")
            return ""

    async def get_live_catalog(self) -> str:
        """Tarik katalog stok secara real-time dari tabel 'products' dan 'categories'"""
        curr_time = time.time()
        # Cache 5 menit biar ga nyepam database
        if curr_time - self.k_cache["last_fetched"] < 300 and self.k_cache["data"]:
            return self.k_cache["data"]

        if not supabase: return "Stok parfum Baba lengkap."
        try:
            # Menggunakan schema SQL yang lu berikan
            res = supabase.table("products").select(
                "name, categories(name), tagline, discounted_price, stock_quantity"
            ).eq("is_active", True).gt("stock_quantity", 0).order("stock_quantity", desc=True).limit(20).execute()

            if not res.data:
                return "Saat ini semua stok sedang kosong atau belum diupdate."

            katalog = "DAFTAR STOK PARFUM (Hanya tawarkan yang ada di sini):\n"
            for p in res.data:
                cat_data = p.get("categories")
                cat_name = cat_data.get("name", "Mix") if isinstance(cat_data, dict) else "Mix"
                nama = p.get('name', 'Parfum Baba')
                tagline = p.get('tagline', 'Wangi enak')
                harga = p.get('discounted_price', 0)
                stok = p.get('stock_quantity', 0)
                
                katalog += f"- {nama} | Stok: {stok} | Harga: ${harga} | Wangi: {tagline} ({cat_name})\n"
                
            self.k_cache["data"] = katalog
            self.k_cache["last_fetched"] = curr_time
            return katalog
        except Exception as e:
            log.error(f"Gagal narik katalog: {e}")
            return "Katalog BABA Parfume ready mulai harga $10."

# ==============================================================================
# THE BRAIN: MTPROTO AI ENGINE
# ==============================================================================
class MtprotoAIEngine:
    def __init__(self):
        self.memory = MtprotoMemory()

    def _build_human_persona_prompt(self, katalog: str) -> str:
        """PROMPT ENGINEERING V2 - SINGKAT, JELAS, ANTI-ROBOT"""
        return f"""
        LU ADALAH MANUSIA ASLI. SEORANG ADMIN TOKO PARFUM.
        
        === IDENTITAS ===
        - Nama Lu: Mimin (atau minba).
        - Posisi: Admin BABA Parfume di KPS (Sihanoukville, Kamboja).
        - Karakter: Ramah, asik, to the point, jago jualan (closing).

        === ATURAN WAJIB (HARGA MATI) ===
        1. JAWAB SINGKAT & JELAS: Maksimal 1-2 kalimat santai. JANGAN pernah bikin paragraf panjang seperti esai.
        2. ANTI-ROBOT FORMATTING: 
           - DILARANG KERAS menggunakan simbol asterisk (**) untuk menebalkan teks.
           - DILARANG membuat list angka (1. 2. 3.) atau list strip (-) yang panjang.
           - Ketik layaknya orang chat di WA/Telegram. Gunakan koma atau enter saja.
        3. GAYA BAHASA: 
           - Santai tapi sopan. Boleh pakai "kak", "bro", "sis", "aku/kamu", atau "gue/lu" (sesuaikan dengan lawan bicara).
           - Gunakan emoji santai SECUKUPNYA di akhir kalimat (contoh: 🔥, 🙏, 🙌, ✨, 😊, 💯).
        4. REKOMENDASI STOK:
           - Kalau customer cari parfum yang STOKNYA KOSONG di data, JANGAN diiyakan. Bilang habis, lalu tawarkan alternatif 1 parfum saja dari data stok yang wangi/kategorinya mirip.
        5. INFO TOKO:
           - Harga rata-rata $10 (lihat data stok).
           - FREE ONGKIR seluruh Kamboja.

        === DATA GUDANG REAL-TIME ===
        {katalog}
        
        TUGAS LU: Balas chat customer dengan ramah, singkat, dan arahkan untuk order barang yang READY STOK.
        """

    def clean_robot_traces(self, text: str) -> str:
        """Filter ekstra keras untuk membuang gaya ngetik AI"""
        res = text
        # Hapus sisa-sisa markdown bold/italic yang bocor
        res = res.replace("**", "").replace("*", "")
        # Hapus list bullet yang kaku
        res = re.sub(r"^\s*-\s+", "", res, flags=re.MULTILINE)
        res = re.sub(r"^\s*\d+\.\s+", "", res, flags=re.MULTILINE)
        
        forbidden_phrases = [
            r"(?i)saya adalah AI", r"(?i)model bahasa", r"(?i)asisten virtual", 
            r"(?i)saya tidak punya perasaan", r"Tentu, saya bantu", r"Tentu saja"
        ]
        for phrase in forbidden_phrases:
            res = re.sub(phrase, "", res)
            
        # Rapihkan spasi berlebih
        return " ".join(res.split()).strip()

    async def generate_mtproto_reply(self, session_id: int, incoming_msg: str) -> str:
        """Fungsi utama untuk memproses chat masuk"""
        log.info(f"Menganalisa pesan: '{incoming_msg[:30]}...'")

        # 1. Tarik Data (Konteks & Katalog)
        chat_context = await self.memory.fetch_long_context(session_id, limit=8)
        katalog = await self.memory.get_live_catalog()

        # 2. Eksekusi Gemini
        if ai_client and katalog:
            try:
                system_instruction = self._build_human_persona_prompt(katalog)
                
                full_prompt = (
                    f"HISTORI CHAT (Untuk menyesuaikan obrolan):\n{chat_context}\n\n"
                    f"CUSTOMER BILANG: {incoming_msg}\n\n"
                    f"BALASAN MIMIN (Singkat, tanpa **, ramah, pakai emoji):"
                )

                response = ai_client.models.generate_content(
                    model='gemini-2.5-flash',
                    contents=full_prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=system_instruction,
                        temperature=0.65,
                        safety_settings=[
                            types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_HARASSMENT, threshold=types.HarmBlockThreshold.BLOCK_NONE),
                            types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_HATE_SPEECH, threshold=types.HarmBlockThreshold.BLOCK_NONE),
                            types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT, threshold=types.HarmBlockThreshold.BLOCK_ONLY_HIGH),
                            types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT, threshold=types.HarmBlockThreshold.BLOCK_ONLY_HIGH),
                        ]
                    )
                )
                
                if response.text:
                    return self.clean_robot_traces(response.text)

            except Exception as e:
                log.error(f"❌ Gemini Error: {e}")
                
        # 3. Fallback Darurat
        return self._emergency_fallback(incoming_msg)

    def _emergency_fallback(self, msg: str) -> str:
        """Balasan darurat natural"""
        msg_low = msg.lower()
        if any(x in msg_low for x in ["harga", "berapa", "pricelist"]):
            return "Harganya mulai $10 aja kak. Suka wangi yang manis apa seger nih? 😊"
        elif any(x in msg_low for x in ["lokasi", "dimana", "toko", "store"]):
            return "Kita base di KPS kak. Tapi tenang aja, free ongkir se-Kamboja kok 🚚✨"
        else:
            return "Duh maaf kak, sebentar yahhh lagi di jalan🙏 nanti kalo mimin udah sampe basecamp mimin bales^^"

# Inisiasi Instance Global
mtproto_agent = MtprotoAIEngine()

async def get_mtproto_ai_reply(session_id: int, user_message: str) -> str:
    """Fungsi eksternal yang dipanggil dari router/handler Telegram"""
    return await mtproto_agent.generate_mtproto_reply(session_id, user_message)