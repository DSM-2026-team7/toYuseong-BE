from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app import models
from app.database import get_db
from app.utils import utc_now
from web import schemas
from web.auth import require_admin

router = APIRouter(prefix="/admin", tags=["admin-applications"], dependencies=[Depends(require_admin)])

NOT_FOUND = {"error": "application_not_found", "message": "신청 건을 찾을 수 없어요"}
ALREADY_REVIEWED = {"error": "already_reviewed", "message": "이미 심사가 완료된 건이에요"}
CATEGORY_LABELS = {"cafe": "카페", "rest": "음식점", "beauty": "뷰티", "etc": "기타"}


@router.get("/applications", response_model=schemas.ApplicationListResponse)
def list_applications(
    status: str = Query(default="pending"),
    search: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
):
    """가맹점 신청 목록 + 탭별 건수."""
    query = db.query(models.StoreApplication)
    if status != "all":
        query = query.filter(models.StoreApplication.status == status)
    if search:
        query = query.filter(models.StoreApplication.name.contains(search))
    query = query.order_by(models.StoreApplication.applied_at.desc())
    rows = query.all()

    items = [
        schemas.ApplicationListItem(
            id=r.id,
            name=r.name,
            category=r.category,
            region=r.region,
            applicant_name=r.applicant_name,
            applied_at=r.applied_at,
            status=r.status,
            application_type=r.application_type,
        )
        for r in rows
    ]

    pending = db.query(models.StoreApplication).filter(models.StoreApplication.status == "pending").count()
    approved = db.query(models.StoreApplication).filter(models.StoreApplication.status == "approved").count()
    rejected = db.query(models.StoreApplication).filter(models.StoreApplication.status == "rejected").count()

    return schemas.ApplicationListResponse(
        applications=items,
        counts=schemas.ApplicationCounts(pending=pending, approved=approved, rejected=rejected),
    )


@router.get("/applications/{application_id}", response_model=schemas.ApplicationDetailResponse)
def get_application(application_id: int, db: Session = Depends(get_db)):
    row = db.get(models.StoreApplication, application_id)
    if row is None:
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    return schemas.ApplicationDetailResponse(
        id=row.id,
        name=row.name,
        business_number=row.business_number,
        category=row.category,
        region=row.region,
        business_hours=row.business_hours,
        phone=row.phone,
        address=row.address,
        applicant_name=row.applicant_name,
        status=row.status,
        reject_reason=row.reject_reason,
        applied_at=row.applied_at,
        reviewed_at=row.reviewed_at,
        application_type=row.application_type,
        store_id=row.store_id,
    )


@router.post("/applications", response_model=schemas.ApplicationActionResponse, status_code=201)
def create_application(payload: schemas.ApplicationCreateRequest, db: Session = Depends(get_db)):
    """가맹점 신청 접수."""
    row = models.StoreApplication(
        name=payload.name,
        category=payload.category,
        region=payload.region,
        business_number=payload.business_number,
        business_hours=payload.business_hours,
        phone=payload.phone,
        applicant_name=payload.applicant_name,
        address=payload.address,
        status="pending",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return schemas.ApplicationActionResponse(id=row.id, status="pending", message="신청이 접수됐어요")


@router.post("/applications/{application_id}/approve", response_model=schemas.ApplicationActionResponse)
def approve_application(application_id: int, db: Session = Depends(get_db)):
    """승인 → 신청자 계정에 매장을 연결하거나 재인증 변경사항을 반영한다."""
    row = db.get(models.StoreApplication, application_id)
    if row is None:
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    if row.status != "pending":
        raise HTTPException(status_code=409, detail=ALREADY_REVIEWED)

    now = utc_now()
    row.status = "approved"
    row.reviewed_at = now

    if row.store_id is not None:
        store = db.get(models.Store, row.store_id)
        if store is None or (row.owner_id is not None and store.owner_id != row.owner_id):
            raise HTTPException(status_code=404, detail=NOT_FOUND)
        store.name = row.name
        store.category = CATEGORY_LABELS.get(row.category, row.category)
        store.region = row.region
        store.business_hours = row.business_hours
        store.register_num = row.business_number
        store.phone_no = row.phone
        store.address = row.address
        store.latitude = row.latitude
        store.longitude = row.longitude
        store.verification_status = "approved"
    else:
        owner = db.get(models.User, row.owner_id) if row.owner_id is not None else None
        if owner is None:
            owner = models.User(
                nickname=f"{row.name} 사장님",
                region=row.region,
                role="owner",
                owner_enabled=True,
                created_at=now,
            )
            db.add(owner)
            db.flush()
        else:
            owner.owner_enabled = True
            owner.region = row.region
        row.owner_id = owner.id

        store = models.Store(
            name=row.name,
            category=CATEGORY_LABELS.get(row.category, row.category),
            region=row.region,
            business_hours=row.business_hours,
            owner_id=owner.id,
            register_num=row.business_number,
            phone_no=row.phone,
            address=row.address,
            latitude=row.latitude,
            longitude=row.longitude,
            verification_status="approved",
        )
        db.add(store)
        db.flush()
        row.store_id = store.id
    db.commit()

    return schemas.ApplicationActionResponse(
        id=row.id, status="approved", message=f"{row.name}을(를) 승인했어요"
    )


@router.post("/applications/{application_id}/reject", response_model=schemas.ApplicationActionResponse)
def reject_application(
    application_id: int,
    payload: schemas.RejectRequest,
    db: Session = Depends(get_db),
):
    row = db.get(models.StoreApplication, application_id)
    if row is None:
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    if row.status != "pending":
        raise HTTPException(status_code=409, detail=ALREADY_REVIEWED)

    row.status = "rejected"
    row.reject_reason = payload.reason
    row.reviewed_at = utc_now()
    if row.store_id is not None:
        store = db.get(models.Store, row.store_id)
        if store is not None:
            store.verification_status = "approved"
    db.commit()

    return schemas.ApplicationActionResponse(
        id=row.id, status="rejected", message=f"{row.name}을(를) 반려했어요"
    )
