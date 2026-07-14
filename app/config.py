import os


DEFAULT_TOSS_SECRET_KEY = "test_gsk_docs_OaPz8L5KdmLxqZqRxTmwrlBN"
TOSS_SECRET_KEY = os.environ.get("TOSS_SECRET_KEY") or DEFAULT_TOSS_SECRET_KEY
TOSS_CONFIRM_URL = "https://api.tosspayments.com/v1/payments/confirm"
TOSS_REQUEST_TIMEOUT_SECONDS = 10.0


def _int_env(key: str, default: int) -> int:
    value = os.environ.get(key)
    return int(value) if value not in (None, "") else default


# 패스 가격/할인율은 운영 중 변경될 가능성이 높아 환경변수로 뺀다.
# 지정하지 않으면 기획 초안 값(기본값)을 그대로 쓴다.
PASS_ONEDAY_PRICE = _int_env("PASS_ONEDAY_PRICE", 2900)
PASS_ONEDAY_DISCOUNT_RATE = _int_env("PASS_ONEDAY_DISCOUNT_RATE", 10)

PASS_WEEKEND_CAFE_PRICE = _int_env("PASS_WEEKEND_CAFE_PRICE", 9900)
PASS_WEEKEND_CAFE_DISCOUNT_RATE = _int_env("PASS_WEEKEND_CAFE_DISCOUNT_RATE", 10)

PASS_GUNGDONG_LOYALTY_PRICE = _int_env("PASS_GUNGDONG_LOYALTY_PRICE", 4900)
PASS_GUNGDONG_LOYALTY_DISCOUNT_RATE = _int_env("PASS_GUNGDONG_LOYALTY_DISCOUNT_RATE", 15)
