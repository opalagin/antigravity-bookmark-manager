import jwt
from datetime import datetime, timedelta, timezone
import settings

def create_access_token(sub: str, email: str) -> str:
    """
    Generates an HS256-signed stateless access JWT.
    """
    now = datetime.now(timezone.utc)
    payload = {
        "sub": sub,
        "email": email,
        "iat": int(now.timestamp()),
        "exp": int(
            (
                now + timedelta(seconds=settings.JWT_ACCESS_TTL_SECONDS)
            ).timestamp()
        ),
        "iss": settings.JWT_ISSUER,
        "aud": settings.JWT_AUDIENCE,
        "typ": "access"
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm="HS256")

def create_refresh_token(sub: str, email: str, jti: str) -> str:
    """
    Generates an HS256-signed refresh JWT containing a unique identifier (jti).
    """
    now = datetime.now(timezone.utc)
    payload = {
        "sub": sub,
        "email": email,
        "jti": jti,
        "iat": int(now.timestamp()),
        "exp": int(
            (
                now + timedelta(seconds=settings.JWT_REFRESH_TTL_SECONDS)
            ).timestamp()
        ),
        "iss": settings.JWT_ISSUER,
        "aud": settings.JWT_AUDIENCE,
        "typ": "refresh"
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm="HS256")

def decode_token(token: str, typ: str = "access") -> dict:
    """
    Decodes and validates a JWT token.
    Supports secret key rotation by attempting validation using JWT_SECRET_PREVIOUS
    if verification with the primary JWT_SECRET fails with InvalidSignatureError.
    """
    # 1. Primary key validation
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=["HS256"],
            audience=settings.JWT_AUDIENCE,
            issuer=settings.JWT_ISSUER,
        )
        if payload.get("typ") != typ:
            raise jwt.InvalidTokenError(
                f"Expected token type '{typ}', got '{payload.get('typ')}'"
            )
        return payload
    except jwt.InvalidSignatureError as e:
        # 2. Key rotation support: try with previous secret if defined
        if settings.JWT_SECRET_PREVIOUS:
            try:
                payload = jwt.decode(
                    token,
                    settings.JWT_SECRET_PREVIOUS,
                    algorithms=["HS256"],
                    audience=settings.JWT_AUDIENCE,
                    issuer=settings.JWT_ISSUER,
                )
                if payload.get("typ") != typ:
                    raise jwt.InvalidTokenError(
                        f"Expected token type '{typ}', got '{payload.get('typ')}'"
                    )
                return payload
            except jwt.InvalidSignatureError:
                pass
        raise e
