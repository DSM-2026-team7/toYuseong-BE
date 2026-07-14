from typing import Any

from fastapi import HTTPException

from app.config import GOOGLE_CLIENT_ID


def verify_google_credential(credential: str) -> dict[str, Any]:
    """Google Identity Services가 발급한 ID 토큰을 공식 라이브러리로 검증한다."""
    if not GOOGLE_CLIENT_ID:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "google_oauth_not_configured",
                "message": "Google OAuth 클라이언트 ID가 설정되지 않았어요",
            },
        )

    try:
        from google.auth.transport import requests
        from google.oauth2 import id_token

        payload = id_token.verify_oauth2_token(
            credential,
            requests.Request(),
            GOOGLE_CLIENT_ID,
        )
    except (ImportError, ValueError) as exc:
        raise HTTPException(
            status_code=401,
            detail={"error": "invalid_google_token", "message": "Google 로그인 정보를 확인할 수 없어요"},
        ) from exc

    if not payload.get("sub"):
        raise HTTPException(
            status_code=401,
            detail={"error": "invalid_google_token", "message": "Google 로그인 정보를 확인할 수 없어요"},
        )
    return payload
