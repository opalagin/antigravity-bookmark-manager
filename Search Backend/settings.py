import os

# Base configurations
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")

# JWT configurations
JWT_SECRET = os.getenv("JWT_SECRET")
if not JWT_SECRET:
    if ENVIRONMENT == "production":
        raise ValueError("JWT_SECRET environment variable is required in production!")
    else:
        JWT_SECRET = "dev_secret_key_at_least_32_bytes_long_fallback"
elif len(JWT_SECRET) < 32:
    if ENVIRONMENT == "production":
        raise ValueError("JWT_SECRET must be at least 32 bytes in production!")

JWT_SECRET_PREVIOUS = os.getenv("JWT_SECRET_PREVIOUS")

# Default values specified in the spec:
# JWT_ACCESS_TTL_SECONDS: 30 minutes (1800)
# JWT_REFRESH_TTL_SECONDS: 90 days (7776000)
try:
    JWT_ACCESS_TTL_SECONDS = int(os.getenv("JWT_ACCESS_TTL_SECONDS", "1800"))
except ValueError:
    JWT_ACCESS_TTL_SECONDS = 1800

try:
    JWT_REFRESH_TTL_SECONDS = int(os.getenv("JWT_REFRESH_TTL_SECONDS", "7776000"))
except ValueError:
    JWT_REFRESH_TTL_SECONDS = 7776000

JWT_ISSUER = os.getenv("JWT_ISSUER", "smart-bookmark-manager")
JWT_AUDIENCE = os.getenv("JWT_AUDIENCE", "api")

# Migration and legacy token compatibility
AUTH_ALLOW_LEGACY_GOOGLE_TOKEN = os.getenv("AUTH_ALLOW_LEGACY_GOOGLE_TOKEN", "0") in ("1", "true", "True")
