import hashlib
from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi import status
from routers.common import supabase, render_admin_template, require_admin_roles, sanitize_admin_role, ADMIN_USER
router=APIRouter(prefix='/admin', tags=['Admin Staff'])

@router.get('/staff', response_class=HTMLResponse, dependencies=[require_admin_roles('super_admin')])
async def admin_staff_page(request: Request):
    staffs=supabase.table('admins').select('*').order('created_at', desc=True).execute().data if supabase else []
    return render_admin_template(request,'admin/staff.html',staffs=staffs or [])

@router.post('/staff/add', dependencies=[require_admin_roles('super_admin')])
async def add_new_staff(username:str=Form(...), password:str=Form(...), full_name:str=Form(...), role:str=Form(...)):
    safe_role=sanitize_admin_role(role); safe_username=username.lower().strip()
    if safe_role in {'','super_admin'} or safe_username==ADMIN_USER.strip().lower(): raise HTTPException(status_code=400, detail='Role/username invalid')
    supabase.table('admins').insert({'username':safe_username,'password_hash':hashlib.sha256(password.encode()).hexdigest(),'full_name':full_name.strip(),'role':safe_role}).execute()
    return RedirectResponse('/admin/staff', status_code=status.HTTP_303_SEE_OTHER)
