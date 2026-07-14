import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import database


@pytest.fixture()
def client():
    """테스트마다 새 in-memory SQLite로 database.engine/SessionLocal을 바꿔치기한 뒤
    TestClient를 열어 lifespan(테이블 생성+시드)이 그 DB에 대해 다시 돌게 한다."""
    test_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    database.engine = test_engine
    database.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

    from app.main import app

    with TestClient(app) as c:
        yield c
