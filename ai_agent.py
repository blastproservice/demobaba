import os
import logging
import time
import asyncio
from typing import Dict, List, Optional

from database import supabase

logger = logging.getLogger("baba.ai.enterprise")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# ==============================================================================
# 1. INISIALISASI MESIN AI (GOOGLE GENAI SDK)
# ==============================================================================
client = None
if GEMINI_API_KEY:
    try:
        from google import genai
        from google.genai import types
        client = genai.Client(api_key=GEMINI_API_KEY)
        logger.info("✅ [AI ENGINE] Gemini 2.5 Flash Enterprise Ready!")
    except Exception as exc:
        logger.error(f"❌ [AI ENGINE] Gagal inisialisasi: {exc}")

# ==============================================================================
# 2. SISTEM KEAMANAN & ANTI-SPAM (CREDIT SAVER)
# ==============================================================================
SPAM_TRACKER: Dict[int, List[float]] = {}
MAX_MESSAGES_PER_MINUTE = 7  
MAX_CHARACTERS = 500         

def is_spam(tele_id: int, user_message: str) -> bool:
    current_time = time.time()
    
    if len(user_message) > MAX_CHARACTERS:
        return True, f"Waduh kak, kepanjangan ngetiknya 😅 Maksimal {MAX_CHARACTERS} huruf ya biar Mimin ga pusing bacanya."

    if len(set(user_message.replace(" ", ""))) < 3 and len(user_message) > 10:
        return True, "Kakak ngetik apa tuh? Mimin ga ngerti hehe. Ketik yang bener dong kak ✨"

    if tele_id not in SPAM_TRACKER:
        SPAM_TRACKER[tele_id] = []
    
    SPAM_TRACKER[tele_id] = [t for t in SPAM_TRACKER[tele_id] if current_time - t < 60]
    
    if len(SPAM_TRACKER[tele_id]) >= MAX_MESSAGES_PER_MINUTE:
        return True, "Sabar kak, ngetiknya cepet banget kaya pelari marathon 🏃‍♂️💨 Tunggu 1 menitan lagi ya baru chat Mimin."
    
    SPAM_TRACKER[tele_id].append(current_time)
    return False, ""

# ==============================================================================
# 3. DATABASE HELPER (SESSION & KNOWLEDGE)
# ==============================================================================
async def get_or_create_session(tele_id: int):
    """Mencari sesi aktif atau membuat baru di database (SINKRON DENGAN CS PANEL)"""
    if not supabase: return None
    
    # PERBAIKAN: Pakai nama tabel 'chat_sessions' biar sinkron sama Panel Admin
    res = supabase.table("chat_sessions").select("id, is_active").eq("telegram_id", tele_id).order("updated_at", desc=True).limit(1).execute()
    
    if res.data:
        session = res.data[0]
        # Kalau is_active False, artinya Admin (Amel/Radit) lagi nge-handle chat ini.
        # AI harus diam dan nggak usah buatin sesi baru.
        if not session.get("is_active"):
            return "HANDLED_BY_ADMIN" 
        return session["id"]
        
    # Kalau belum ada, bikin sesi baru
    new_sess = supabase.table("chat_sessions").insert({"telegram_id": tele_id, "is_active": True}).execute()
    return new_sess.data[0]["id"]

KNOWLEDGE_CACHE = {"data": "", "last_fetched": 0}

async def get_perfume_knowledge_base():
    current_time = time.time()
    if current_time - KNOWLEDGE_CACHE["last_fetched"] < 300 and KNOWLEDGE_CACHE["data"]:
        return KNOWLEDGE_CACHE["data"]

    if not supabase: return ""

    res = supabase.table("products").select(
        "name, tags, tagline, discounted_price, stock_quantity, top_notes, heart_notes, base_notes"
    ).eq("is_active", True).gt("stock_quantity", 0).execute()

    katalog = ""
    for p in (res.data or []):
        tags_str = ", ".join(p["tags"]) if isinstance(p.get("tags"), list) else str(p.get("tags") or "-")
        katalog += (
            f"- {p.get('name', 'Tanpa Nama')}: {p.get('tagline', '-')}. "
            f"Kategori/Tags: {tags_str}. "
            f"Wangi Detail: {p.get('top_notes', [])} (awal), {p.get('heart_notes', [])} (tengah). "
            f"Harga: ${p.get('discounted_price', 0)}. Stok: {p.get('stock_quantity', 0)} pcs.\n"
        )
    
    KNOWLEDGE_CACHE["data"] = katalog
    KNOWLEDGE_CACHE["last_fetched"] = current_time
    return katalog

# ==============================================================================
# 4. SELF-LEARNING ENGINE
# ==============================================================================
async def get_ai_learning_context() -> str:
    if not supabase: return ""

    try:
        res = supabase.table("ai_feedbacks").select("rating, complaint").order("created_at", desc=True).limit(10).execute()
        feedbacks = res.data or []
        
        if not feedbacks:
            return "Kamu belum menerima feedback. Lakukan yang terbaik sesuai instruksi awal."

        avg_rating = sum(f['rating'] for f in feedbacks) / len(feedbacks)
        keluhan_teks = [f['complaint'] for f in feedbacks if f.get('complaint') and f['complaint'].strip() != ""]

        learning_prompt = f"EVALUASI KINERJAMU SAAT INI (Rata-rata rating: {avg_rating:.1f}/5.0):\n"

        if avg_rating <= 1.5:
            learning_prompt += "🚨 KRITIS (Bintang 1): Pengguna merasa kamu sangat kurang memuaskan. KAMU HARUS lebih mengerti, berempati, banyak bertanya kebutuhan mereka, dan jangan asal jualan!\n"
        elif avg_rating <= 2.5:
            learning_prompt += "⚠️ PERLU EVALUASI (Bintang 2): Perhatikan gaya bahasamu. Jangan terlalu kaku, coba lebih mengalir dan pastikan kamu menjawab inti pertanyaan pengguna.\n"
        elif avg_rating <= 3.5:
            learning_prompt += "🟡 CUKUP (Bintang 3): Jawabanmu masih kurang bisa dimengerti oleh beberapa orang. Gunakan analogi yang lebih gampang dan sederhanakan bahasamu.\n"
        elif avg_rating <= 4.5:
            learning_prompt += "🟢 BAGUS (Bintang 4): Pengguna suka gayamu! Tetap pertahankan keseruannya, tapi coba maksimalkan lagi detail penawarannya agar lebih nge-hook.\n"
        else:
            learning_prompt += "🌟 SEMPURNA (Bintang 5): Pertahankan gayamu yang sekarang! Pengguna sangat puas. Kembangkan gaya asikmu ini.\n"

        if keluhan_teks:
            learning_prompt += "\nKELUHAN/MASUKAN USER BARU-BARU INI (Pastikan kamu TIDAK MENGULANGI kesalahan ini):\n"
            for keluhan in keluhan_teks[:3]: 
                learning_prompt += f"- \"{keluhan}\"\n"
        
        return learning_prompt
    except Exception as e:
        logger.error(f"Gagal memuat learning context: {e}")
        return ""

# ==============================================================================
# 5. CORE SYSTEM & FALLBACK
# ==============================================================================
def build_fallback_reply(user_message: str) -> str:
    lowered = user_message.lower()
    if any(keyword in lowered for keyword in ["cowok", "man", "maskulin"]):
        vibe = "nyari yang fresh atau woody biar keliatan gentle"
    elif any(keyword in lowered for keyword in ["cewek", "woman", "feminin"]):
        vibe = "nyari wangi kalem, manis, atau floral biar makin anggun"
    else:
        vibe = "milih wangi yang paling pas sama karakter kakak"

    return (
        "Halo kak! Mimin BABA di sini ✨ Sistem katalog kita lagi istirahat bentar nih.\n\n"
        f"Tapi santai, kalau kakak lagi {vibe}, sebutin aja biasa pakenya buat acara apa atau budgetnya berapa. "
        "Nanti Mimin bantu cariin racikan yang paling the best buat kakak! 🙌"
    )

async def get_ai_recommendation(tele_id: int, user_message: str) -> str:
    is_spamming, spam_warning = is_spam(tele_id, user_message)
    if is_spamming:
        logger.warning(f"🛡️ [ANTI-SPAM] Blocked message from {tele_id}")
        return spam_warning

    try:
        sid = await get_or_create_session(tele_id)

        # LEVERAGE: Kalau admin lagi chat manual, AI langsung mati otomatis!
        if sid == "HANDLED_BY_ADMIN":
            return "" # Retun string kosong, nanti di bot.py kita tahan biar AI nggak ngirim apa-apa

        if supabase and sid:
            # PERBAIKAN: Update trigger "last_message" dan "updated_at" biar sesi ini naik ke atas di Panel CS
            supabase.table("chat_sessions").update({
                "last_message": user_message[:50] + "..." if len(user_message) > 50 else user_message,
                "updated_at": "now()"
            }).eq("id", sid).execute()

            # PERBAIKAN: Pakai nama tabel 'chat_messages'
            supabase.table("chat_messages").insert({
                "session_id": sid, "role": "user", "content": user_message
            }).execute()

        chat_context = ""
        if supabase and sid:
            history_res = supabase.table("chat_messages").select("role, content").eq("session_id", sid).order("created_at", desc=False).limit(10).execute()
            for h in (history_res.data or []):
                role_name = "User" if h["role"] == "user" else "AI"
                chat_context += f"{role_name}: {h['content']}\n"

        stok_realtime = await get_perfume_knowledge_base()
        learning_context = await get_ai_learning_context()

        if client and stok_realtime:
            system_instruction = f"""
            Kamu adalah 'Mimin BABA', asisten virtual dan ahli parfum dari BABA Parfume.
            
            IDENTITAS & GAYA BAHASA:
            - Santai, humble, asik, ala Gen Z. Gunakan bahasa sehari-hari yang merakyat dan gampang dimengerti siapa aja (nggak baku/kaku).
            - Panggil user dengan sebutan 'Kak'.
            - Jawabanmu harus SINGKAT, PADAT, NYAMAN DIBACA. JANGAN KAYA KORAN!
            
            {learning_context}
            
            GAYA JUALAN (MARKETING 4.0):
            - Fokus ke fungsi, masalah yang diselesaikan, dan momen pemakaian (misal: "bikin cewek nempel", "enak buat ngantor biar seger", "cocok buat nge-date").
            - JANGAN jelaskan detail piramida wangi (top/heart/base notes) di awal.
            - Kasih detail notes HANYA kalau user secara spesifik bertanya tentang detail aroma parfum tertentu.

            ATURAN FORMAT REKOMENDASI:
            Jika kamu memberikan list rekomendasi parfum yang tersedia, WAJIB pecah ke dalam kategori berikut (jangan tampilkan kategori yang stoknya 0):

            🔥 **Top Seller (Paling Laris)**
            - [Nama Parfum] ([Deskripsi super singkat, ngejual, dan sebutkan fungsinya. Max 1 kalimat])

            👨 **Man (Cowok Banget)**
            - [Nama Parfum] ([Deskripsi super singkat, ngejual, dan sebutkan fungsinya])

            👩 **Woman (Cewek Banget)**
            - [Nama Parfum] ([Deskripsi super singkat, ngejual, dan sebutkan fungsinya])

            👫 **Netral (Unisex)**
            - [Nama Parfum] ([Deskripsi super singkat, ngejual, dan sebutkan fungsinya])

            CONTOH DESKRIPSI: 
            - Baccarat (Wangi mewah yang paling banyak dicari, asik dipake nongkrong seharian)
            - Rextase (Wangi seger, kalem, paling pas dipake kalo lagi kerja atau ngantor)

            DATA STOK REALTIME (HANYA rekomendasikan yang ada di daftar ini):
            {stok_realtime}
            """
            
            full_prompt = f"RIWAYAT CHAT SEBELUMNYA:\n{chat_context}\n\nPertanyaan User Baru: {user_message}"

            response = await client.aio.models.generate_content(
                model="gemini-2.5-flash",
                contents=full_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    temperature=0.7, 
                )
            )
            ai_reply = response.text
        else:
            ai_reply = build_fallback_reply(user_message)

        if supabase and sid:
            supabase.table("chat_messages").insert({
                "session_id": sid, "role": "model", "content": ai_reply
            }).execute()

        return ai_reply

    except Exception as e:
        logger.warning(f"AI agent fallback aktif (Error: {e})")
        return build_fallback_reply(user_message)