from fastapi import Request, HTTPException, status
try:
    from database import supabase
except ImportError:
    supabase = None

async def get_current_admin(request: Request):
    # Cek apakah ada cookie session
    session_id = request.cookies.get("baba_admin_session")
    
    if not session_id:
        # Kalo gak ada cookie, tendang kasih status 401
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Belum login")
        
    if supabase:
        try:
            # Ambil data asli dari Supabase berdasarkan ID di cookie
            res = supabase.table("admins").select("id, full_name, role").eq("id", session_id).execute()
            if res.data:
                admin = res.data[0]
                return {
                    "admin_id": admin["id"],
                    "admin_name": admin["full_name"],
                    "admin_role": admin["role"]
                }
        except Exception:
            pass
            
    # Kalo ID di cookie palsu atau error, tendang juga
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sesi tidak valid")