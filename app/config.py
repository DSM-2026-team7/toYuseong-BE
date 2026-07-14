import os



def _load_dotenv_if_exists(path: str = ".env") -> None:
    """?? ??? ?? ?? .env ?? os.environ? ????.

    ?? ?/?? ??? ??? ?? ???? ???.
    """
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as file:
        for raw_line in file:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


_load_dotenv_if_exists()


DEFAULT_TOSS_SECRET_KEY = "test_gsk_docs_OaPz8L5KdmLxqZqRxTmwrlBN"
TOSS_SECRET_KEY = os.environ.get("TOSS_SECRET_KEY") or DEFAULT_TOSS_SECRET_KEY
TOSS_CONFIRM_URL = "https://api.tosspayments.com/v1/payments/confirm"
TOSS_REQUEST_TIMEOUT_SECONDS = 10.0
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
APP_JWT_SECRET = os.environ.get(
    "APP_JWT_SECRET",
    "change-me-use-at-least-32-bytes-in-production",
)
PAYMENT_QR_TTL_MINUTES = 5


def _int_env(key: str, default: int) -> int:
    value = os.environ.get(key)
    return int(value) if value not in (None, "") else default


# 패스 가격/할인율은 운영 중 변경될 가능성이 높아 환경변수로 뺀다.
# 지정하지 않으면 기획 초안 값(기본값)을 그대로 쓴다.
PASS_ONEDAY_PRICE = _int_env("PASS_ONEDAY_PRICE", 2900)
PASS_ONEDAY_DISCOUNT_RATE = _int_env("PASS_ONEDAY_DISCOUNT_RATE", 10)
PASS_ONEDAY_MAX_DISCOUNT = _int_env("PASS_ONEDAY_MAX_DISCOUNT", 10000)

PASS_WEEKEND_CAFE_PRICE = _int_env("PASS_WEEKEND_CAFE_PRICE", 9900)
PASS_WEEKEND_CAFE_DISCOUNT_RATE = _int_env("PASS_WEEKEND_CAFE_DISCOUNT_RATE", 10)
PASS_WEEKEND_CAFE_MAX_DISCOUNT = _int_env("PASS_WEEKEND_CAFE_MAX_DISCOUNT", 30000)

PASS_GUNGDONG_LOYALTY_PRICE = _int_env("PASS_GUNGDONG_LOYALTY_PRICE", 4900)
PASS_GUNGDONG_LOYALTY_DISCOUNT_RATE = _int_env("PASS_GUNGDONG_LOYALTY_DISCOUNT_RATE", 15)
PASS_GUNGDONG_LOYALTY_MAX_DISCOUNT = _int_env("PASS_GUNGDONG_LOYALTY_MAX_DISCOUNT", 30000)


NAVER_SEARCH_CLIENT_ID = os.environ.get("NAVER_SEARCH_CLIENT_ID", "")
NAVER_SEARCH_CLIENT_SECRET = os.environ.get("NAVER_SEARCH_CLIENT_SECRET", "")
NAVER_LOCAL_SEARCH_URL = "https://openapi.naver.com/v1/search/local.json"
NAVER_REQUEST_TIMEOUT_SECONDS = 5.0
