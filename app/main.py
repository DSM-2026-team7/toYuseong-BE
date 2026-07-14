from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import database
from app.routers import admin, checkout, coupons, me, passes, stamps, stores, demo_web
from app.routers import auth as demo_auth
from app.seed import run_seed
from web.routers import applications, auth, dashboard, passes as admin_passes, settlements



@asynccontextmanager
async def lifespan(app: FastAPI):
    # database.engine / database.SessionLocal을 모듈 속성으로 매번 조회한다.
    # (테스트에서 in-memory DB로 바꿔치기한 뒤 이 lifespan을 다시 태울 수 있어야 하므로
    #  import 시점에 이름을 고정 바인딩하지 않는다.)
    database.Base.metadata.create_all(bind=database.engine)
    db = database.SessionLocal()
    try:
        run_seed(db)
    finally:
        db.close()
    yield


app = FastAPI(title="유성으로 (ToYuseong) API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc: HTTPException):
    detail = exc.detail
    if isinstance(detail, dict) and "error" in detail and "message" in detail:
        return JSONResponse(status_code=exc.status_code, content=detail)
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": "error", "message": str(detail)},
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=400,
        content={"error": "invalid_request", "message": "잘못된 요청입니다."},
    )


app.include_router(stores.router)
app.include_router(stamps.router)
app.include_router(coupons.router)
app.include_router(checkout.router)
app.include_router(passes.router)
app.include_router(me.router)
app.include_router(admin.router)
app.include_router(demo_auth.router)

app.include_router(demo_web.router)

# 구청 관리자 API (web/)
app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(applications.router)
app.include_router(settlements.router)
app.include_router(admin_passes.router)
