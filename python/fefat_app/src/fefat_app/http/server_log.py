"""The server's log (step 4.2, D-86): `<FEFAT_HOME>/logs/server.log`, kept to 5 MB and three files
before it, and the terminal `fefat up` runs in, both at INFO, where uvicorn's own lines arrive
too, since `fefat up` gives uvicorn no logging configuration of its own. Plain lines; step 13.3
turns them into JSON lines."""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_FILE_NAME = "server.log"
LOG_FILE_BYTES = 5 * 1024 * 1024
LOG_FILES_KEPT = 3
LINE_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"


def configure_server_log(logs_dir: Path) -> Path:
    """Send the process's log to `logs_dir`'s server log and to the terminal; the log file."""
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_file = logs_dir / LOG_FILE_NAME
    formatter = logging.Formatter(LINE_FORMAT)
    to_file = RotatingFileHandler(
        log_file, maxBytes=LOG_FILE_BYTES, backupCount=LOG_FILES_KEPT, encoding="utf-8"
    )
    to_terminal = logging.StreamHandler()
    root = logging.getLogger()
    for handler in (to_file, to_terminal):
        handler.setFormatter(formatter)
        root.addHandler(handler)
    root.setLevel(logging.INFO)
    return log_file
