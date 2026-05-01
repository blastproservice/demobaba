from fastapi import APIRouter, Request, Depends
from routers.common import render_admin_template
from routers.dependencies import get_current_admin

router = APIRouter(prefix="/admin/profile", tags=["Profile"])

@router.get("")
async def profile_page(request: Request, admin=Depends(get_current_admin)):
    # TODO: Pindahin logic ambil data profil/history admin dari main.py lama
    return render_admin_template(
        request, 
        "admin/profile.html", 
        admin_data=admin
    )