"""
Config — 12-Factor: mọi cấu hình đọc từ biến môi trường.

Không có secret nào trong code: AGENT_API_KEY bắt buộc đặt qua env
(trên Railway/Render là Variables, local là file .env được docker compose đọc).
"""
import os
from dataclasses import dataclass, field


def _env_str(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        raise ValueError(f"{name} phải là số nguyên, nhận được {os.getenv(name)!r}")


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        raise ValueError(f"{name} phải là số, nhận được {os.getenv(name)!r}")


@dataclass
class Settings:
    # Server
    port: int = field(default_factory=lambda: _env_int("PORT", 8000))
    environment: str = field(default_factory=lambda: _env_str("ENVIRONMENT", "development"))
    log_level: str = field(default_factory=lambda: _env_str("LOG_LEVEL", "INFO").upper())
    app_version: str = field(default_factory=lambda: _env_str("APP_VERSION", "1.0.0"))

    # Security — KHÔNG có giá trị mặc định cho secret
    agent_api_key: str = field(default_factory=lambda: _env_str("AGENT_API_KEY"))

    # State store
    redis_url: str = field(default_factory=lambda: _env_str("REDIS_URL", "redis://localhost:6379/0"))

    # Rate limit: số request tối đa / 60 giây cho mỗi API key
    rate_limit_per_minute: int = field(default_factory=lambda: _env_int("RATE_LIMIT_PER_MINUTE", 10))

    # Cost guard (USD). <= 0 nghĩa là không giới hạn theo kỳ đó.
    daily_budget_usd: float = field(default_factory=lambda: _env_float("DAILY_BUDGET_USD", 0))
    monthly_budget_usd: float = field(default_factory=lambda: _env_float("MONTHLY_BUDGET_USD", 10.0))

    def validate(self) -> "Settings":
        """Fail fast khi cấu hình sai ở production."""
        if self.environment == "production" and not self.agent_api_key:
            raise ValueError("AGENT_API_KEY phải được đặt khi ENVIRONMENT=production")
        if self.rate_limit_per_minute <= 0:
            raise ValueError("RATE_LIMIT_PER_MINUTE phải > 0")
        return self


settings = Settings().validate()
