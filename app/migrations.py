from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine


SQLITE_COLUMNS: dict[str, dict[str, str]] = {
    "users": {
        "google_sub": "VARCHAR",
        "email": "VARCHAR",
        "profile_image_url": "VARCHAR",
        "customer_enabled": "BOOLEAN NOT NULL DEFAULT 1",
        "owner_enabled": "BOOLEAN NOT NULL DEFAULT 0",
        "onboarding_completed": "BOOLEAN NOT NULL DEFAULT 1",
        "location_permission": "VARCHAR NOT NULL DEFAULT 'unknown'",
    },
    "stores": {
        "address": "VARCHAR",
        "image_url": "VARCHAR",
        "latitude": "FLOAT",
        "longitude": "FLOAT",
        "verification_status": "VARCHAR NOT NULL DEFAULT 'approved'",
    },
    "stamp_policies": {
        "active": "BOOLEAN NOT NULL DEFAULT 1",
        "min_amount": "INTEGER NOT NULL DEFAULT 0",
        "completion_limit": "INTEGER",
        "reward_type": "VARCHAR NOT NULL DEFAULT 'discount_amount'",
        "reward_value": "INTEGER NOT NULL DEFAULT 0",
        "reward_min_payment": "INTEGER NOT NULL DEFAULT 0",
        "reward_max_discount": "INTEGER",
        "reward_valid_days": "INTEGER DEFAULT 30",
    },
    "stamp_cards": {
        "completed_count": "INTEGER NOT NULL DEFAULT 0",
    },
    "coupons": {
        "status": "VARCHAR NOT NULL DEFAULT 'active'",
        "created_at": "DATETIME",
        "stopped_at": "DATETIME",
        "source": "VARCHAR NOT NULL DEFAULT 'owner'",
    },
    "payment_qrs": {
        "expires_at": "DATETIME",
        "scanned_at": "DATETIME",
    },
    "user_coupons": {
        "deleted_at": "DATETIME",
    },
    "passes": {
        "max_discount_amount": "INTEGER",
    },
    "user_passes": {
        "discount_used": "INTEGER NOT NULL DEFAULT 0",
        "discount_limit": "INTEGER",
        "name_snapshot": "VARCHAR",
        "scope_snapshot": "VARCHAR",
        "scope_category_snapshot": "VARCHAR",
        "scope_store_id_snapshot": "INTEGER",
        "discount_rate_snapshot": "INTEGER",
        "max_discount_snapshot": "INTEGER",
    },
    "transactions": {
        "store_id": "INTEGER",
        "discount_rate": "INTEGER",
    },
    "payments": {
        "original_amount": "INTEGER",
        "discount_amount": "INTEGER NOT NULL DEFAULT 0",
        "benefit_summary": "TEXT",
        "completed_at": "DATETIME",
    },
    "store_applications": {
        "owner_id": "INTEGER",
        "store_id": "INTEGER",
        "address": "VARCHAR",
        "latitude": "FLOAT",
        "longitude": "FLOAT",
        "application_type": "VARCHAR NOT NULL DEFAULT 'initial'",
    },
    "settlements": {
        "transaction_count": "INTEGER NOT NULL DEFAULT 0",
    },
}


def ensure_compatibility_columns(engine: Engine) -> None:
    """기존 SQLite 개발 DB에도 새 소비자 기능 컬럼을 추가한다."""
    if engine.dialect.name != "sqlite":
        return

    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    with engine.begin() as connection:
        for table, columns in SQLITE_COLUMNS.items():
            if table not in existing_tables:
                continue
            existing_columns = {column["name"] for column in inspector.get_columns(table)}
            for name, definition in columns.items():
                if name not in existing_columns:
                    connection.execute(text(f'ALTER TABLE "{table}" ADD COLUMN "{name}" {definition}'))

        if "users" in existing_tables:
            connection.execute(text("UPDATE users SET owner_enabled = 1 WHERE role = 'owner'"))
            connection.execute(text("UPDATE users SET customer_enabled = 1"))
            connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_users_google_sub ON users (google_sub)"))
        if "coupons" in existing_tables:
            connection.execute(text("UPDATE coupons SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL"))
        if "settlements" in existing_tables:
            connection.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_settlement_store_month "
                    "ON settlements (store_id, year, month)"
                )
            )
        if "transactions" in existing_tables and "stores" in existing_tables:
            connection.execute(
                text(
                    "UPDATE transactions SET store_id = ("
                    "SELECT stores.id FROM stores WHERE stores.name = transactions.store_name LIMIT 1"
                    ") WHERE store_id IS NULL AND store_name IS NOT NULL"
                )
            )
