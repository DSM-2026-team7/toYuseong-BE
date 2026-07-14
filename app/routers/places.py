import html
import re
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Query

from app import config, schemas

router = APIRouter(prefix="/places", tags=["places"])

_TAG_RE = re.compile(r"<[^>]+>")


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = html.unescape(str(value))
    text = _TAG_RE.sub("", text).strip()
    return text or None


def _naver_coord(value: Any) -> float | None:
    """??? ?? ??? mapx/mapy ?? ??/?? ??? ????.

    ?? ?? API? ??? ?? ???? ????? ?? GPS ??? ?? ??
    10,000,000?? ???. ?? ??? ??? ? ??? None? ????.
    """
    if value in (None, ""):
        return None
    try:
        return int(value) / 10_000_000
    except (TypeError, ValueError):
        return None


def _naver_headers() -> dict[str, str]:
    if not config.NAVER_SEARCH_CLIENT_ID or not config.NAVER_SEARCH_CLIENT_SECRET:
        raise HTTPException(
            status_code=500,
            detail={
                "error": "naver_api_key_missing",
                "message": "??? ?? ?? API ?? ???? ????",
            },
        )
    return {
        "X-Naver-Client-Id": config.NAVER_SEARCH_CLIENT_ID,
        "X-Naver-Client-Secret": config.NAVER_SEARCH_CLIENT_SECRET,
    }


@router.get("/naver/search", response_model=schemas.PlaceSearchResponse)
def search_naver_places(
    q: str = Query(..., min_length=1, description="??? ??? ?? ???"),
    display: int = Query(default=5, ge=1, le=20),
):
    """??? ?? ?? API? ?? ??? ????.

    ???? ???/??? ?? ?? ???? ? API? ??? ????,
    ???? ??? ??? address/latitude/longitude? Store? ???? ??.
    """
    try:
        response = httpx.get(
            config.NAVER_LOCAL_SEARCH_URL,
            params={"query": q.strip(), "display": display, "sort": "random"},
            headers=_naver_headers(),
            timeout=config.NAVER_REQUEST_TIMEOUT_SECONDS,
        )
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "error": "naver_network_error",
                "message": f"??? ?? ?? ?? ??: {exc}",
            },
        ) from exc

    if response.status_code != 200:
        raise HTTPException(
            status_code=response.status_code,
            detail={
                "error": "naver_search_error",
                "message": "??? ?? ??? ?????",
            },
        )

    try:
        data = response.json()
    except ValueError as exc:
        raise HTTPException(
            status_code=502,
            detail={"error": "invalid_naver_response", "message": "??? ?? ??? ???? ???"},
        ) from exc

    places: list[schemas.PlaceSearchItem] = []
    for item in data.get("items", []):
        longitude = _naver_coord(item.get("mapx"))
        latitude = _naver_coord(item.get("mapy"))
        places.append(
            schemas.PlaceSearchItem(
                name=_clean_text(item.get("title")) or "",
                category=_clean_text(item.get("category")),
                address=_clean_text(item.get("address")),
                road_address=_clean_text(item.get("roadAddress")),
                phone=_clean_text(item.get("telephone")),
                latitude=latitude,
                longitude=longitude,
                source="naver",
            )
        )

    return schemas.PlaceSearchResponse(places=places)
