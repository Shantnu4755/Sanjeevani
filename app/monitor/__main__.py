"""Self-healing monitor: python -m app.monitor (same image as the API, different command)."""

from ..config import Config
from ..extensions import db
from ..logging_setup import setup_logging
from .monitor import Alerter, HealthProbe, Monitor, Restarter


def main() -> None:
    config = Config.from_env()
    setup_logging(config.log_level)
    db.init_app(config.database_url)
    alerter = Alerter(config.telegram_bot_token, config.telegram_chat_id)
    Monitor(HealthProbe(), Restarter(config.docker_url), alerter, interval=config.check_interval).run()


if __name__ == "__main__":
    main()
