import os

class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-change-this-before-deploying")
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL", "sqlite:///ghost_kitchen.db")
    if SQLALCHEMY_DATABASE_URI.startswith("postgres://"):
        SQLALCHEMY_DATABASE_URI = SQLALCHEMY_DATABASE_URI.replace("postgres://", "postgresql://", 1)
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    MAX_CONTENT_LENGTH = 12 * 1024 * 1024
    UPLOAD_FOLDER = os.environ.get("UPLOAD_FOLDER", os.path.join(os.path.dirname(__file__), "instance", "uploads"))
    BUSINESS_NAME = os.environ.get("BUSINESS_NAME", "Merriman Valley Pizza")
    RENTAL_RATE = int(os.environ.get("RENTAL_RATE", "150"))
    TIMEZONE = os.environ.get("TIMEZONE", "America/New_York")
