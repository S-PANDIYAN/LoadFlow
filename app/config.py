"""Application configuration."""
import os

class Settings:
    APP_NAME: str = "LoadFlow"
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./loadflow.db")
    JWT_SECRET: str = os.getenv("JWT_SECRET", "loadflow-dev-secret-change-in-prod")
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = int(os.getenv("JWT_EXPIRE_MINUTES", "480"))  # 8h — hackathon demo friendly

settings = Settings()
