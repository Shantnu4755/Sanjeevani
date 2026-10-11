import os
from dataclasses import dataclass


class ConfigError(RuntimeError):
    """Raised at startup when required configuration is missing."""


def _require(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise ConfigError(f"Missing required environment variable: {name}")
    return value


@dataclass(frozen=True)
class Config:
    app_name: str
    database_url: str
    log_level: str
    debug: bool
    docker_url: str = "tcp://docker-proxy:2375"
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    admin_token: str = ""  # empty: manual restarts are disabled
    check_interval: float = 30.0

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            app_name=os.getenv("APP_NAME", "app"),
            database_url=_require("DATABASE_URL"),
            log_level=os.getenv("LOG_LEVEL", "INFO"),
            debug=os.getenv("DEBUG", "false").lower() == "true",
            docker_url=os.getenv("DOCKER_URL", "tcp://docker-proxy:2375"),
            telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
            telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID", ""),
            admin_token=os.getenv("ADMIN_TOKEN", ""),
            check_interval=float(os.getenv("CHECK_INTERVAL", "30")),
        )
