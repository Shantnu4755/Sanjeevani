"""Liveness for processes without an HTTP server (workers, relays, monitors).

The image's HEALTHCHECK calls /health, which only the API serves, so compose gives these
containers a check on how recently this file was touched instead. A hung loop goes unhealthy.
"""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

LIVENESS_FILE = Path("/tmp/alive")


def mark_alive() -> None:
    try:
        LIVENESS_FILE.touch()
    except OSError:
        logger.exception("liveness_touch_failed")
