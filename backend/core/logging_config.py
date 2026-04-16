"""Application-wide logging setup (call once at process entry)."""

import logging
import os


def configure_logging() -> None:
    # Set STREAM_DEBUG=1 in your environment to enable verbose chunk-level debug logs.
    stream_debug = os.environ.get("STREAM_DEBUG", "0") == "1"
    logging.basicConfig(level=logging.DEBUG if stream_debug else logging.INFO)
    if not stream_debug:
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("httpcore").setLevel(logging.WARNING)
