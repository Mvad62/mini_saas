import os
import secrets

from passlib.context import CryptContext
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

SECRET_KEY = os.getenv("SECRET_KEY") or secrets.token_urlsafe(32)
SESSION_COOKIE_NAME = "mini_saas_session"
SESSION_MAX_AGE_SECONDS = 60 * 60 * 24 * 7

password_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
session_serializer = URLSafeTimedSerializer(SECRET_KEY, salt="mini-saas-auth")


def hash_password(password: str) -> str:
    return password_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return password_context.verify(password, password_hash)


def generate_session_token(user_id: int) -> str:
    return session_serializer.dumps({"user_id": user_id})


def decode_session_token(token: str) -> int | None:
    try:
        payload = session_serializer.loads(token, max_age=SESSION_MAX_AGE_SECONDS)
    except (BadSignature, SignatureExpired):
        return None

    user_id = payload.get("user_id") if isinstance(payload, dict) else None
    return user_id if isinstance(user_id, int) and user_id > 0 else None
