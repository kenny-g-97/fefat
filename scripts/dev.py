"""Run the local server and the web app's dev server together (steps 4.3 and 5.1,
`01-architecture.md` section 9): `just dev`.

    uv run python scripts/dev.py

Without `FEFAT_HOME`, `fefat up` serves `fefat-dev` in the system's temporary folder, made afresh
at each start as the UI harness's home is (`e2e_server.seed`): the synthetic fixtures as its
data, or the data folder `FEFAT_DATA_DIR` names, keyring at its null backend, port 8765, and the
password this script prints. With `FEFAT_HOME`, it serves that home at the port of its
`config.toml`, asking at this console for a password where it has none. Once the server's
`/v1/healthz` answers, Vite's dev server starts on http://localhost:5173 with its proxy pointed at
that port (`web/vite.config.ts`) and opens the app in the browser.

The server starts again whenever a file of the SDK's or the app's source changes, which a stamp
of them, read four times a second, tells; Vite reloads the web app by itself. A server that ends
by itself, as at an error in the source, waits for the next change. Ctrl+C, or Vite's end, stops
both, with every process they started.
"""

import contextlib
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from typing import NamedTuple

import e2e_server
from fefat.config import load_settings, resolve_paths

ROOT = Path(__file__).resolve().parents[1]
SOURCES = (ROOT / "python" / "fefat" / "src", ROOT / "python" / "fefat_app" / "src")
"""The source the server runs, whose change starts it again."""
DEV_HOME_NAME = "fefat-dev"
DEV_PORT = 8765
DEV_PASSWORD = "only the dev home"
"""The dev home's password, which this script prints; short and spaced, so that the commit guard
never reads it as a secret."""
POLL_SECONDS = 0.25
SETTLE_SECONDS = 0.5
STOP_SECONDS = 10.0

type SourceStamp = frozenset[tuple[str, int]]


class DevHome(NamedTuple):
    """The home `just dev` seeds, and the data folder the environment names for it; None for the
    home's own copy of the synthetic fixtures."""

    home: Path
    data_dir: Path | None


def dev_home(environment: Mapping[str, str]) -> DevHome | None:
    """The throwaway home `just dev` serves where `environment` names no `FEFAT_HOME`, with the
    data folder it names, if any; None where it names a home, which `just dev` serves as it is."""
    if "FEFAT_HOME" in environment:
        return None
    named = environment.get("FEFAT_DATA_DIR")
    home = Path(tempfile.gettempdir()) / DEV_HOME_NAME
    return DevHome(home=home, data_dir=None if named is None else Path(named))


def source_stamp(folders: Sequence[Path]) -> SourceStamp:
    """Each file under `folders`, but those of `__pycache__`, with the time it was last written:
    another stamp means a file was saved, added, removed, or renamed. A folder, or a file, that
    goes while it is read ends its folder's part of the stamp, as a checkout that removes it
    changes the stamp anyway."""
    return frozenset(found for folder in folders for found in _written(folder))


def _written(folder: Path) -> Iterator[tuple[str, int]]:
    with contextlib.suppress(FileNotFoundError), os.scandir(folder) as entries:
        for entry in entries:
            if not entry.is_dir():
                yield entry.path, entry.stat().st_mtime_ns
            elif entry.name != "__pycache__":
                yield from _written(Path(entry.path))


def answers(url: str) -> bool:
    """Whether a server answers at `url`, with any status."""
    try:
        with urllib.request.urlopen(url, timeout=1):
            return True
    except urllib.error.HTTPError:
        return True
    except OSError:
        return False


def answered(server: subprocess.Popen[bytes], url: str) -> bool:
    """Whether `server` answers at `url` before it ends."""
    while server.poll() is None:
        if answers(url):
            return True
        time.sleep(POLL_SECONDS)
    return False


def closed(url: str) -> None:
    """Wait until no server answers at `url`, as after a stop, `STOP_SECONDS` at most."""
    deadline = time.monotonic() + STOP_SECONDS
    while answers(url) and time.monotonic() < deadline:
        time.sleep(POLL_SECONDS)


def settled(stamp: SourceStamp) -> SourceStamp:
    """The stamp of the source once it holds still for `SETTLE_SECONDS`, as it does when an
    editor has saved its files or a checkout has written them."""
    while True:
        time.sleep(SETTLE_SECONDS)
        now = source_stamp(SOURCES)
        if now == stamp:
            return now
        stamp = now


def stop(process: subprocess.Popen[bytes]) -> None:
    """Stop `process` and every process it started, unless it has ended."""
    if process.poll() is not None:
        return
    if sys.platform == "win32":
        tree = ["taskkill", "/T", "/F", "/PID", str(process.pid)]
        subprocess.run(tree, capture_output=True, check=False)
    else:
        process.terminate()
    process.wait()


def program(name: str) -> str:
    """The path of `name` on the PATH, which a `.cmd` shim such as pnpm's needs on Windows."""
    found = shutil.which(name)
    if found is None:
        raise SystemExit(f"Expected {name} on the PATH (just doctor), got none.")
    return found


def started_server() -> subprocess.Popen[bytes]:
    return subprocess.Popen([program("uv"), "run", "fefat", "up"])


def served(running: list[subprocess.Popen[bytes]], health: str) -> int:
    """Start the server, `running[0]`, again whenever the source changes, until Vite,
    `running[1]`, ends, and give Vite's exit code; a server that ends by itself is told of once
    and waits for the next change."""
    stamp = source_stamp(SOURCES)
    told = False
    while running[1].poll() is None:
        time.sleep(POLL_SECONDS)
        if running[0].poll() is not None and not told:
            print(
                f"FEAT's server ended with {running[0].returncode}; it starts again at the next "
                "change of the source.",
                flush=True,
            )
            told = True
        now = source_stamp(SOURCES)
        if now == stamp:
            continue
        stamp = settled(now)
        stop(running[0])
        closed(health)
        running[0] = started_server()
        told = False
        print("The source changed: FEAT's server starts again.", flush=True)
    return running[1].returncode


def main() -> int:
    seeded = dev_home(os.environ)
    port = DEV_PORT
    if seeded is None:
        port = load_settings(resolve_paths(os.environ).config_file).port
    health = f"http://127.0.0.1:{port}/v1/healthz"
    if answers(health):
        elsewhere = "set another port in config.toml"
        if seeded is not None:
            elsewhere = "name a FEFAT_HOME whose config.toml sets another port"
        raise SystemExit(
            f"Expected port {port} free for fefat up, got a server answering there: stop it, "
            f"or {elsewhere}."
        )
    if seeded is not None:
        e2e_server.seed(seeded.home, port, DEV_PASSWORD, seeded.data_dir)
        print(f"FEAT serves the dev home {seeded.home}; its password: {DEV_PASSWORD}", flush=True)
    running: list[subprocess.Popen[bytes]] = []
    try:
        running.append(started_server())
        if not answered(running[0], health):
            return running[0].returncode
        web = [program("pnpm"), "--dir", "web", "dev", "--open"]
        running.append(subprocess.Popen(web, env={**os.environ, "FEFAT_SERVER_PORT": str(port)}))
        return served(running, health)
    except KeyboardInterrupt:
        return 0
    finally:
        for process in reversed(running):
            stop(process)


if __name__ == "__main__":
    sys.exit(main())
