"""Run the local server and the web app's dev server together (step 4.3, `01-architecture.md`
section 9): `just dev`.

    uv run python scripts/dev.py

`fefat up` starts first, on the port of `FEFAT_HOME`'s `config.toml`, and asks at this console
for a password when it has none; once its `/v1/healthz` answers, Vite's dev server starts on
http://localhost:5173 with its proxy pointed at that port (`web/vite.config.ts`) and opens the
app in the browser. Ctrl+C, or either server ending, stops both, with every process they
started.
"""

import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request

from fefat.config import load_settings, resolve_paths

POLL_SECONDS = 0.25


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


def main() -> int:
    port = load_settings(resolve_paths(os.environ).config_file).port
    started: list[subprocess.Popen[bytes]] = []
    try:
        server = subprocess.Popen([program("uv"), "run", "fefat", "up"])
        started.append(server)
        if not answered(server, f"http://127.0.0.1:{port}/v1/healthz"):
            return server.returncode
        web = [program("pnpm"), "--dir", "web", "dev", "--open"]
        started.append(subprocess.Popen(web, env={**os.environ, "FEFAT_SERVER_PORT": str(port)}))
        while all(process.poll() is None for process in started):
            time.sleep(POLL_SECONDS)
        return 0
    except KeyboardInterrupt:
        return 0
    finally:
        for process in reversed(started):
            stop(process)


if __name__ == "__main__":
    sys.exit(main())
