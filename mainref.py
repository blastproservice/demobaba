import logging, time, hashlib
from fastapi import FastAPI, Request, Form, HTTPException, status
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware


from routers.common import (
    templates, lifespan, verify_admin, create_secure_cookie, sanitize_admin_role,
    COOKIE_NAME, COOKIE_SECURE, ADMIN_USER, ADMIN_PASS, supabase
)
from routers.admin.dashboard import router as admin_dashboard_router
from routers.admin.finance import router as admin_finance_router
from routers.admin.stock import router as admin_stock_router
from routers.admin.orders import router as admin_orders_router
from routers.admin.customers import router as admin_customers_router
from routers.admin.staff import router as admin_staff_router
from routers.admin.settings import router as admin_settings_router
from routers.customer.store import router as customer_store_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s")
logger = logging.getLogger("baba.enterprise")

app = FastAPI(title="BABA Parfume Enterprise Engine", version="5.0.0-Modular", lifespan=lifespan, docs_url="/api/docs", redoc_url=None)
app.mount('/static', StaticFiles(directory='static'), name='static')
app.add_middleware(CORSMiddleware, allow_origins=['*'], allow_credentials=True, allow_methods=['*'], allow_headers=['*'])

class RequestTimerMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
	        t=time.time(); resp=await call_next(request)
        if time.time()-t > 1.0: logger.warning(f"Slow request: {request.method} {request.url.path}")
        return resp

app.add_middleware(RequestTimerMiddleware)

@app.get('/admin/login', response_class=HTMLResponse, tags=['Admin Auth'])
async def login_page(request: Request):
    if request.cookies.get(COOKIE_NAME):
        try:
            await verify_admin(request)
			return RedirectResponse('/admin', status_code=status.HTTP_303_SEE_OTHER)
        except HTTPException:
            pass
		
    return templates.TemplateResponse(request=request, name='admin/login.html')
	
@app.post('/admin/login', response_class=HTMLResponse, tags=['Admin Auth'])
async def do_login(request: Request, username: str = Form(...), password: str = Form(...)):
    username=username.strip().lower(); role=''; name=''
    if username == ADMIN_USER.strip().lower() and password == ADMIN_PASS:
        role='super_admin'; name='Dewa BABA (Super Admin)'
    else:
	        if not supabase: return templates.TemplateResponse(request=request,name='admin/login.html',context={'error':'Sistem Database Offline!'})
        hashed=hashlib.sha256(password.encode()).hexdigest()
        res=supabase.table('admins').select('*').eq('username',username).eq('password_hash',hashed).limit(1).execute()
        if not res.data: return templates.TemplateResponse(request=request,name='admin/login.html',context={'error':'Username atau Password salah bre!'})
        staff=res.data[0]; role=sanitize_admin_role(staff.get('role')); name=staff['full_name']
    cookie=create_secure_cookie(username, role, name)
    response=RedirectResponse('/admin',status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(key=COOKIE_NAME,value=cookie,httponly=True,max_age=43200,secure=COOKIE_SECURE,samesite='lax')
    return response

@app.get('/admin/logout', tags=['Admin Auth'])
async def do_logout():

    r=RedirectResponse('/admin/login', status_code=status.HTTP_303_SEE_OTHER); r.delete_cookie(COOKIE_NAME); return r

app.include_router(customer_store_router)
app.include_router(admin_dashboard_router)
app.include_router(admin_finance_router)
app.include_router(admin_stock_router)
app.include_router(admin_orders_router)
app.include_router(admin_customers_router)
app.include_router(admin_staff_router)
app.include_router(admin_settings_router)