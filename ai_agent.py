"""
====================================================================================
BABA PARFUME - ENTERPRISE AI AGENT (V3.0 - MASTERPIECE EDITION)
====================================================================================
Deskripsi : Otak utama 'Mimin BABA'. Dibangun menggunakan arsitektur OOP untuk
            skalabilitas tinggi, keamanan berlapis, dan logika rekomendasi yang 
            super akurat.
Fitur     : 
            - Smart Context Memory (Mengingat chat sebelumnya)
            - Safe Database Bridge (Anti-crash kalau data kosong)
            - Advanced NLP Fallback (Rekomendasi otomatis berbasis gender)
            - Security Layer (Anti-spam & Anti-SARA/Judi)
            - Dynamic Prompt Engineering
====================================================================================
"""

import os
import re
import time
import logging
import asyncio
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Union, Any

# Supabase Bridge
try:
    from database import supabase
except ImportError:
    supabase = None

# Gemini SDK
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
client = None
if GEMINI_API_KEY:
    try:
        from google import genai
        from google.genai import types
        client = genai.Client(api_key=GEMINI_API_KEY)
    except Exception as e:
        print(f"❌ [GEMINI INIT ERROR]: {e}")

# ==============================================================================
# 1. ADVANCED LOGGING SYSTEM
# ==============================================================================
class BabaLogger:
    """Sistem pencatatan log agar mudah di-debug di VPS"""
    def __init__(self):
        self.logger = logging.getLogger("baba.ai.master")
        if not self.logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter('%(asctime)s | %(levelname)s | [AI_AGENT] %(message)s')
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)
            self.logger.setLevel(logging.INFO)
            
    def info(self, msg: str): self.logger.info(msg)
    def warning(self, msg: str): self.logger.warning(msg)
    def error(self, msg: str): self.logger.error(msg)

log = BabaLogger()
log.info("🚀 Menginisialisasi Baba Enterprise AI Agent V3.0...")

# ==============================================================================
# 2. SECURITY & RATE LIMITER MANAGER
# ==============================================================================
class SecurityManager:
    """Manajer keamanan untuk mencegah spam dan injeksi topik terlarang"""
    def __init__(self):
        self.spam_tracker: Dict[int, List[float]] = {}
        self.max_msg_per_min = 10
        self.max_chars = 600
        
        # Regex rahasia untuk memblokir niat jahat user
        self.blocked_patterns = [
            re.compile(r"judi|slot|gacor|maxwin|zeus|scatter|pragmatic", re.IGNORECASE),
            re.compile(r"narkoba|sabu|ganja|weed|meth", re.IGNORECASE),
            re.compile(r"porno|bokep|xxx|onlyfans|vcs", re.IGNORECASE),
            re.compile(r"pinjol|pinjaman|hutang|rentenir", re.IGNORECASE),
            re.compile(r"politik|presiden|pemilu|gubernur|partai", re.IGNORECASE),
            re.compile(r"hack|carding|phishing|ddos", re.IGNORECASE)
        ]

    def check_spam(self, tele_id: int, message: str) -> Tuple[bool, str]:
        """Pengecekan spam brutal dan panjang karakter"""
        curr_time = time.time()
        
        # Filter panjang
        if len(message) > self.max_chars:
            return True, f"Waduh kak, kepanjangan ngetiknya 😅 Maksimal {self.max_chars} huruf ya biar Mimin ga pusing bacanya."
            
        # Filter ketikan acak (asdfghjkl)
        if len(set(message.replace(" ", ""))) < 3 and len(message) > 10:
            return True, "Kakak ngetik apa tuh? Mimin ga ngerti hehe. Ketik kata yang bener ya kak ✨"

        # Rate Limiting Logic
        if tele_id not in self.spam_tracker:
            self.spam_tracker[tele_id] = []
            
        # Bersihkan log yang lebih dari 60 detik
        self.spam_tracker[tele_id] = [t for t in self.spam_tracker[tele_id] if curr_time - t < 60]
        
        if len(self.spam_tracker[tele_id]) >= self.max_msg_per_min:
            return True, "Sabar kak, ngetiknya cepet banget kaya pelari marathon 🏃‍♂️💨 Tunggu bentar ya baru chat Mimin lagi."
            
        self.spam_tracker[tele_id].append(curr_time)
        return False, ""

    def check_blocked_content(self, message: str) -> Tuple[bool, str]:
        """Menghalau obrolan di luar konteks bisnis"""
        for pattern in self.blocked_patterns:
            if pattern.search(message):
                log.warning(f"🛡️ [SECURITY] Blocked topic detected: {message[:20]}...")
                return True, "Waduh kak, maaf banget Mimin cuma bisa ngobrolin seputar wangi-wangian dan parfum BABA aja nih. Ada varian parfum yang lagi kakak cari? ✨"
        return False, ""

# ==============================================================================
# 3. KNOWLEDGE & SOP MANAGER
# ==============================================================================
class SOPManager:
    """Pusat aturan baku perusahaan yang tidak boleh dilanggar AI"""
    def __init__(self):
        self.rules = {
            "harga": "Semua parfum BABA mulai dari $10 per botol kak. The best value banget pokoknya!",
            "lokasi": "Kita *base*-nya di Sihanoukville (KPS), Cambodia kak. Kapan-kapan mampir ya!",
            "ongkir": "Tenang kak, kita kasih FREE ONGKIR ke mana aja tanpa minimal order! Asik kan? Tinggal duduk manis paket dateng.",
            "racikan": "Parfum kita ini *ready-to-wear* (udah diracik sempurna dari pabrik pake bibit Import Paris). Jadi kakak nggak bisa *request* custom racikan sendiri ya kak. Percaya deh, racikan *default* kita udah divalidasi ribuan hidung! ✨",
            "kualitas": "100% Halal, aman di kulit, nggak bikin baju kuning, dan pastinya awet nemenin aktivitas kakak seharian.",
            "pembayaran": "Pembayaran gampang banget kak. Bisa bayar pake Dolar ABA, Transfer BCA, atau Cash Rill pas COD.",
            "cara_pesan": "Kalau udah nemu yang cocok, langsung tekan tombol 'Mulai Belanja' di menu bawah kak, pilih parfumnya, terus ikutin aja panduannya. Gampang banget!"
        }

    def bypass_ai_for_sop(self, message: str) -> Optional[str]:
        """Fungsi pembaca cepat untuk menghemat limit API Gemini jika pertanyaan sangat umum"""
        msg = message.lower()
        if any(k in msg for k in ["berapa harga", "harganya berapa", "pricelist", "price list", "paling murah"]):
            return self.rules["harga"] + " Kakak lagi nyari wangi yang cowok banget atau cewek nih?"
            
        if any(k in msg for k in ["ongkir", "ongkos kirim", "pengiriman", "kirim ke", "biaya kirim", "free ongkir"]):
            return self.rules["ongkir"] + " Langsung pesen aja kak, gausah pusingin biaya jalan hehe."
            
        if any(k in msg for k in ["lokasi", "alamat", "di mana", "dari mana", "posisi", "toko offline"]):
            return self.rules["lokasi"] + " Posisinya deketan ga nih sama kita? Kalo iya bisa kita anter cepet kak!"
            
        if any(k in msg for k in ["bisa custom", "bikin wangi sendiri", "pesen wangi", "racik sendiri", "campur"]):
            return self.rules["racikan"]
            
        if any(k in msg for k in ["cara pesen", "cara order", "gimana belinya", "mau beli"]):
            return self.rules["cara_pesan"]
            
        return None

# ==============================================================================
# 4. DATABASE & CONTEXT MANAGER
# ==============================================================================
class DatabaseManager:
    """Manajer cerdas untuk interaksi aman dengan Supabase"""
    def __init__(self):
        self.k_cache = {"data": "", "last_fetched": 0.0}
        self.cache_ttl = 300 # 5 Menit

    async def get_active_session(self, tele_id: int) -> Union[int, str]:
        """Mengambil atau membuat sesi chat. Sinkron dengan Dashboard Admin"""
        if not supabase: return "NO_DB"
        try:
            # FIX: Ganti order dari updated_at jadi created_at (sesuai schema lu)
            res = supabase.table("ai_chat_sessions").select("id, is_active").eq("telegram_id", tele_id).order("created_at", desc=True).limit(1).execute()
            if res.data:
                session = res.data[0]
                if not session.get("is_active"):
                    log.info(f"🛑 [INTERCEPT] Admin is handling chat for {tele_id}")
                    return "HANDLED_BY_ADMIN"
                return session["id"]
            
            # Buat sesi baru jika kosong
            new_sess = supabase.table("ai_chat_sessions").insert({"telegram_id": tele_id, "is_active": True}).execute()
            return new_sess.data[0]["id"]
        except Exception as e:
            log.error(f"DB Session Error: {e}")
            return "NO_DB"

    async def update_history(self, session_id: int, role: str, content: str):
        """Simpan pesan ke riwayat database"""
        if not supabase or session_id in ["NO_DB", "HANDLED_BY_ADMIN"]: return
        try:
            supabase.table("ai_chat_messages").insert({"session_id": session_id, "role": role, "content": content}).execute()
            # FIX: Kita hapus update ke `last_message` dan `updated_at` karena kolomnya belum ada di DB lu.
        except Exception as e:
            log.error(f"DB Update History Error: {e}")

    async def fetch_chat_context(self, session_id: int, limit: int = 6) -> str:
        """Ambil X pesan terakhir untuk ingatan AI"""
        if not supabase or session_id in ["NO_DB", "HANDLED_BY_ADMIN"]: return ""
        try:
            res = supabase.table("ai_chat_messages").select("role, content").eq("session_id", session_id).order("created_at", desc=False).limit(limit).execute()
            context = ""
            for msg in (res.data or []):
                speaker = "User" if msg["role"] == "user" else "Mimin"
                context += f"{speaker}: {msg['content']}\n"
            return context
        except Exception as e:
            log.error(f"DB Fetch Context Error: {e}")
            return ""

    async def build_catalog(self) -> str:
        """Tarik data stok dengan SAFE PARSING anti-crash"""
        curr_time = time.time()
        if curr_time - self.k_cache["last_fetched"] < self.cache_ttl and self.k_cache["data"]:
            return self.k_cache["data"]

        if not supabase: return ""

        try:
            res = supabase.table("products").select(
                "name, categories(name), tagline, discounted_price, stock_quantity, tags"
            ).eq("is_active", True).gt("stock_quantity", 0).order("stock_quantity", desc=True).execute()

            katalog = "DAFTAR PARFUM READY STOK (URUT DARI PALING LARIS):\n"
            
            for p in (res.data or []):
                # 🛡️ PENGAMAN SUPER KETAT: Mencegah NoneType Error jika category kosong
                cat_data = p.get("categories")
                if isinstance(cat_data, dict):
                    cat_name = cat_data.get("name", "NETRAL")
                else:
                    cat_name = "NETRAL"
                
                cat_upper = str(cat_name).upper()
                nama_parfum = p.get('name', 'Parfum BABA')
                tagline = p.get('tagline', 'Wangi elegan')
                harga = p.get('discounted_price', 10)
                stok = p.get('stock_quantity', 0)
                
                katalog += f"- [{cat_upper}] **{nama_parfum}**: {tagline} (${harga} | Stok: {stok})\n"
                
            self.k_cache["data"] = katalog
            self.k_cache["last_fetched"] = curr_time
            log.info("✅ Katalog berhasil diperbarui ke memori AI.")
            return katalog
            
        except Exception as e:
            log.error(f"❌ FATAL ERROR DB Catalog: {e}")
            return ""

    async def get_learning_feedback(self) -> str:
        """Tarik feedback dari rating user untuk memperbaiki gaya AI"""
        if not supabase: return ""
        try:
            res = supabase.table("ai_feedbacks").select("rating, complaint").order("created_at", desc=True).limit(5).execute()
            feedbacks = res.data or []
            if not feedbacks: return ""

            avg_rating = sum(f['rating'] for f in feedbacks) / len(feedbacks)
            learning = f"Rata-rata Rating Kinerjamu: {avg_rating:.1f}/5.0.\n"
            
            if avg_rating <= 3.0:
                learning += "⚠️ PERINGATAN: User kurang nyaman. Pastikan kamu menjawab sangat singkat, santai, dan tidak bertele-tele!\n"
            else:
                learning += "🌟 BAGUS: Pertahankan gaya santai dan ramahmu.\n"
                
            return learning
        except: return ""

# ==============================================================================
# 5. THE AI ENGINE CORE
# ==============================================================================
class BabaAIEngine:
    """Jantung utama mesin kecerdasan buatan BABA"""
    def __init__(self):
        self.security = SecurityManager()
        self.sop = SOPManager()
        self.db = DatabaseManager()

    def generate_system_prompt(self, stok_data: str, learning_data: str) -> str:
        """Meracik instruksi dasar yang sangat kuat untuk Gemini"""
        return f"""
        Kamu adalah 'Mimin', Customer Service andalan dari BABA Parfume.

        === IDENTITAS & KARAKTER (WAJIB DIIKUTI) ===
        1. GAYA BAHASA: Sangat humanis, santai, asik, ala tongkrongan ("nih kak", "mantap", "hehe", "oke siap"). JANGAN kaku seperti robot/AI!
        2. PANGGILAN: Selalu panggil lawan bicaramu "Kak" atau "Kakak". Panggil dirimu sendiri "Mimin".
        3. PANJANG PESAN: Jawab MAKSIMAL 2-3 kalimat pendek. Jangan membuat paragraf panjang!

        === LOGIKA REKOMENDASI (STRATEGI JUALAN) ===
        JIKA USER MINTA REKOMENDASI TAPI BELUM JELAS:
        - Tanya dulu: "Buat cowok apa cewek nih kak?" dan "Suka wangi seger (fresh) atau manis?"
        - Jangan asal tebak rekomendasi sebelum tahu ini!

        JIKA USER SUDAH KASIH DETAIL (Contoh: "Cowok yang fresh"):
        1. Kasih MAKSIMAL 2 NAMA PARFUM. Ambil dari produk paling atas di daftar stok (paling laris).
        2. Aturan Trik Fallback (Jika stok spesifik kosong):
           - Jika [MAN] Fresh kosong -> Tawarkan [NETRAL] Fresh.
           - Jika [NETRAL] Fresh juga kosong -> Baru tawarkan [MAN] Manis/lainnya.
           - Berlaku sebaliknya untuk Perempuan ([WOMAN] -> [NETRAL] -> [WOMAN] lain).

        === ATURAN MUTLAK PERUSAHAAN (SOP) ===
        1. HARGA: Semua parfum mulai dari $10.
        2. LOKASI: KPS (Sihanoukville), Cambodia.
        3. ONGKIR: FREE ONGKIR ke seluruh wilayah Kamboja tanpa minimal order.
        4. RACIKAN: Parfum BABA sudah diracik sempurna (Ready-to-wear). Tidak menerima request racikan custom.
        5. CLOSING: Selalu arahkan user untuk klik tombol "Mulai Belanja" di menu bawah jika mereka sudah tertarik.

        {learning_data}

        === CARA JUALAN ===
            - Fokus ke "masalah apa yang diselesaikan parfum ini". Misal: "Wangi ini bikin rileks pas ngantor kak", atau "Ini wangi maskulin yang bikin cewek noleh".
            - Arahkan user untuk "Langsung cek tombol di menu bawah ya kak" jika mereka mau beli.
            - HANYA tawarkan parfum yang ada di data stok di bawah ini. JANGAN MENGOARANG NAMA PRODUK LAIN!

        === DAFTAR PRODUK READY STOK ===
        (Hanya tawarkan nama produk yang ada di list ini. Jangan mengarang nama!)
        {stok_data}
        """

    def clean_ai_response(self, text: str) -> str:
        """Membersihkan halusinasi atau sisa gaya bahasa robot Google"""
        res = text
        robot_phrases = [
            r"Saya adalah model bahasa besar", r"Sebagai AI", r"Saya asisten virtual", 
            r"Menurut database saya", r"Berdasarkan informasi yang diberikan"
        ]
        for phrase in robot_phrases:
            res = re.sub(phrase, "", res, flags=re.IGNORECASE)
            
        res = res.replace("Anda", "Kakak").replace("anda", "kakak")
        res = res.replace("Saya ", "Mimin ").replace("saya ", "Mimin ")
        
        # Batasi panjang output darurat
        paragraphs = res.split("\n\n")
        if len(paragraphs) > 4:
            res = "\n\n".join(paragraphs[:3]) + "\n\n*(Pesen langsung aja klik tombol di bawah ya kak!)* ✨"
            
        return res.strip()

    def generate_fallback_reply(self, message: str) -> str:
        """Sistem pertahanan terakhir jika AI gagal total"""
        msg_low = message.lower()
        if any(k in msg_low for k in ["cowok", "man", "laki", "maskulin"]):
            vibe = "woody atau seger maskulin"
        elif any(k in msg_low for k in ["cewek", "woman", "perempuan", "feminin"]):
            vibe = "manis, floral, atau kalem elegan"
        else:
            vibe = "enak, awet, dan cocok buat kakak"

        return (
            "Halo kak! Mimin BABA di sini ✨ Sistem rekomendasi Mimin lagi loading data bentar nih.\n\n"
            f"Tapi santai kak, kalau kakak nyari wangi yang {vibe}, sebutin aja biasa pakenya buat aktivitas apa (kerja, nongkrong, atau nge-date). "
            "Nanti Mimin milihin yang paling the best buat kakak! 🙌"
        )

    async def process_chat(self, tele_id: int, user_message: str) -> str:
        """ORCHESTRATOR: Fungsi utama pemrosesan pesan masuk"""
        log.info(f"📨 Chat masuk dari {tele_id}")

        # 1. Cek Keamanan Lapisan Pertama
        is_spam, spam_msg = self.security.check_spam(tele_id, user_message)
        if is_spam: return spam_msg

        is_blocked, block_msg = self.security.check_blocked_content(user_message)
        if is_blocked: return block_msg

        # 2. Cek Sesi Database (Apakah Admin ambil alih?)
        session_id = await self.db.get_active_session(tele_id)
        if session_id == "HANDLED_BY_ADMIN":
            return "" # Diam, biarkan Admin bicara

        # 3. Fast-Track SOP (Hemat Limit API)
        sop_fast_reply = self.sop.bypass_ai_for_sop(user_message)
        if sop_fast_reply:
            await self.db.update_history(session_id, "user", user_message)
            await self.db.update_history(session_id, "model", sop_fast_reply)
            return sop_fast_reply

        # 4. Ambil Konteks & Data
        await self.db.update_history(session_id, "user", user_message)
        chat_context = await self.db.fetch_chat_context(session_id)
        katalog = await self.db.build_catalog()
        feedback = await self.db.get_learning_feedback()

        # 5. Panggil LLM (Gemini)
        if client and katalog:
            try:
                sys_prompt = self.generate_system_prompt(katalog, feedback)
                full_prompt = f"RIWAYAT CHAT SEBELUMNYA:\n{chat_context}\n\nUSER (Balas dengan santai & max 3 kalimat): {user_message}"

                response = await client.aio.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=full_prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=sys_prompt,
                        temperature=0.75, # Keseimbangan antara akurat dan kreatif
                    )
                )
                final_reply = self.clean_ai_response(response.text)

                # Simpan jawaban AI
                await self.db.update_history(session_id, "model", final_reply)
                return final_reply

            except Exception as e:
                log.error(f"❌ [GEMINI API CRASH]: {e}")
                return self.generate_fallback_reply(user_message)
        else:
            log.warning("⚠️ Engine LLM atau Katalog kosong, menggunakan Fallback.")
            return self.generate_fallback_reply(user_message)

# ==============================================================================
# 6. EXPORT / ENTRY POINT
# ==============================================================================
# Inisialisasi satu instance global agar cache tetap hidup
baba_engine = BabaAIEngine()

async def get_ai_recommendation(tele_id: int, user_message: str) -> str:
    """
    Fungsi pembungkus luar agar kompatibel dengan router main.py lu yang lama.
    Ini adalah fungsi yang akan dipanggil oleh backend web lu.
    """
    try:
        return await baba_engine.process_chat(tele_id, user_message)
    except Exception as e:
        log.error(f"💥 [CRITICAL FAILURE IN AI AGENT]: {e}")
        return baba_engine.generate_fallback_reply(user_message)