"""Process-level logging configuration (called from entry points only)."""

import logging
import os

LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'


def configure_logging() -> None:
    """Configure root logging once; LOG_LEVEL env var, invalid -> INFO."""
    level = getattr(logging, os.environ.get("LOG_LEVEL", "INFO").strip().upper(), None)
    if not isinstance(level, int):
        level = logging.INFO
    logging.basicConfig(level=level, format=LOG_FORMAT)
