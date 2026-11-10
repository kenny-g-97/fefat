"""A process of the tests' that hangs inside a write of the database, holding its write lock, as a
worker of the pool can (the Phase 4 exit): standard library alone, so that it starts fast."""

import sqlite3
import time
from multiprocessing.synchronize import Event


def hung_inside_a_write(database_file: str, go: Event, locked: Event) -> None:
    """Once `go` is set, begin a write of `database_file`, set `locked`, and hang there."""
    go.wait()
    connection = sqlite3.connect(database_file, timeout=60)
    connection.execute("BEGIN IMMEDIATE")
    locked.set()
    time.sleep(600)
