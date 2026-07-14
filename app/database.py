from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

SQLALCHEMY_DATABASE_URL = "sqlite:///./toyuseong.db"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def ensure_sqlite_schema() -> None:
    """?? ?? SQLite ??? ?? ??? nullable ??? ????.

    SQLAlchemy `create_all()`? ?? ???? ???? ??? ???? ????,
    ???? ?? DB? ?? ??? ?? ?? ?? ??? ?? ????? ??
    ??????? ????.
    """
    if engine.dialect.name != "sqlite":
        return

    inspector = inspect(engine)
    if "stores" not in inspector.get_table_names():
        return

    existing = {column["name"] for column in inspector.get_columns("stores")}
    columns = {
        "address": "VARCHAR",
        "latitude": "FLOAT",
        "longitude": "FLOAT",
        "image_url": "VARCHAR",
    }
    with engine.begin() as conn:
        for name, ddl_type in columns.items():
            if name not in existing:
                conn.execute(text(f"ALTER TABLE stores ADD COLUMN {name} {ddl_type}"))
