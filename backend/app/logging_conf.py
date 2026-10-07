"""Structured (key=value) logging. Never log document contents at INFO."""

import logging


def setup_logging(level: int = logging.INFO) -> None:
    logging.basicConfig(level=level, format="ts=%(asctime)s level=%(levelname)s logger=%(name)s msg=%(message)s")
