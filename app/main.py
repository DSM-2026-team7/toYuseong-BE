from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import database
from app.routers import checkout, coupons, me, passes, stamps, stores
from app.seed import run_seed


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


app.include_router(stores.router)
app.include_router(stamps.router)
app.include_router(coupons.router)
app.include_router(checkout.router)
app.include_router(passes.router)
app.include_router(me.router)
