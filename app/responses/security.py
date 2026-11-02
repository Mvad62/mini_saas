import secrets

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.auth.security import SECRET_KEY

CSRF_TOKEN_MAX_AGE_SECONDS = 60 * 60 * 2
csrf_serializer = URLSafeTimedSerializer(SECRET_KEY, salt="mini-saas-public-form-csrf")


def create_csrf_token(survey_id: int) -> str:
    return csrf_serializer.dumps(
        {"survey_id": survey_id, "nonce": secrets.token_urlsafe(24)}
    )


def validate_csrf_token(token: str, survey_id: int) -> bool:
    try:
        payload = csrf_serializer.loads(token, max_age=CSRF_TOKEN_MAX_AGE_SECONDS)
    except (BadSignature, SignatureExpired):
        return False

    return (
        isinstance(payload, dict)
        and payload.get("survey_id") == survey_id
        and isinstance(payload.get("nonce"), str)
    )
