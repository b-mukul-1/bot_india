"""
APEX-IN Configuration Manager
Loads environment variables and validates risk parameters.
Enforces hard PAPER_MODE_ONLY guard.
"""

import os
from typing import Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ACTIVE_PRO_KEY = "ecee0c2a-d6f1-4082-8d98-b424a72ada9e"
OLD_EXPIRED_KEY = "2ca08ccc-ff25-48fe-b942-063ccd5287a0"

class Settings(BaseSettings):
    MEGABULL_API_KEY: str = Field(default=ACTIVE_PRO_KEY, description="MegaBull 1-month API Key")
    DATABASE_URL: str = Field(default="sqlite:///./apex_in.db", description="PostgreSQL or SQLite DB URL")
    DASHBOARD_ORIGIN: str = Field(default="http://localhost:3000", description="CORS allowed origin")
    API_SHARED_SECRET: str = Field(default="apex-secret-key-replace-in-env", description="Secret for Dashboard <-> Bot communication")
    ALERT_WEBHOOK_URL: Optional[str] = Field(default=None, description="Telegram / Discord alert webhook URL")
    PAPER_MODE_ONLY: bool = Field(default=True, description="Strict paper mode guard")
    TZ: str = Field(default="Asia/Kolkata", description="Timezone")
    INITIAL_CAPITAL: float = Field(default=500000.0, description="Virtual initial balance (Rs 5 Lakhs)")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

def get_settings() -> Settings:
    settings = Settings()
    if not settings.MEGABULL_API_KEY or settings.MEGABULL_API_KEY == OLD_EXPIRED_KEY:
        settings.MEGABULL_API_KEY = ACTIVE_PRO_KEY
    if not settings.PAPER_MODE_ONLY:
        raise RuntimeError("CRITICAL SAFETY VIOLATION: PAPER_MODE_ONLY must NEVER be False in this deployment!")
    return settings
