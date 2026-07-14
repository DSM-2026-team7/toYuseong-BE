# 후순위: POST /auth/google (목업). 데모 인증은 X-User-Id 헤더로 대체한다.
from fastapi import APIRouter

router = APIRouter(tags=["auth"])
