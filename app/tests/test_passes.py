from datetime import timedelta

from app import database, models
from app.utils import utc_now


HEADERS = {"X-User-Id": "100"}


def test_expired_pass_is_not_reported_as_owned(client):
    db = database.SessionLocal()
    try:
        db.add(models.UserPass(
            user_id=100,
            pass_id=1,
            status="active",
            purchased_at=utc_now() - timedelta(days=2),
            expires_at=utc_now() - timedelta(days=1),
        ))
        db.commit()
    finally:
        db.close()

    passes = client.get("/passes", headers=HEADERS).json()["passes"]
    assert next(item for item in passes if item["id"] == 1)["owned"] is False
    assert client.get("/passes/1", headers=HEADERS).json()["owned"] is False
