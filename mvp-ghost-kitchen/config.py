import os
from datetime import timedelta


class Config:
    # Render supplies SECRET_KEY through render.yaml. Keep a development fallback
    # only for local use; create_app rejects a missing key in production.
    SECRET_KEY = os.environ.get("SECRET_KEY") or (
        None if os.environ.get("RENDER") else "dev-only-change-this-before-deploying"
    )

    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL", "sqlite:///ghost_kitchen.db")
    if SQLALCHEMY_DATABASE_URI.startswith("postgres://"):
        SQLALCHEMY_DATABASE_URI = SQLALCHEMY_DATABASE_URI.replace(
            "postgres://", "postgresql://", 1
        )

    SQLALCHEMY_TRACK_MODIFICATIONS = False
    MAX_CONTENT_LENGTH = 12 * 1024 * 1024
    UPLOAD_FOLDER = os.environ.get(
        "UPLOAD_FOLDER",
        os.path.join(os.path.dirname(__file__), "instance", "uploads"),
    )
    BUSINESS_NAME = os.environ.get("BUSINESS_NAME", "Merriman Valley Pizza")
    RENTAL_RATE = int(os.environ.get("RENTAL_RATE", "150"))
    TIMEZONE = os.environ.get("TIMEZONE", "America/New_York")

    # Limit the lifetime of the persistent organizer login cookie.
    PERMANENT_SESSION_LIFETIME = timedelta(hours=8)
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = (
        os.environ.get("SESSION_COOKIE_SECURE", "true" if os.environ.get("RENDER") else "false").lower()
        == "true"
    )
