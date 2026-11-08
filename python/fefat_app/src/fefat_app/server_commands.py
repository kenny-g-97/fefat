"""`fefat up`, the local server (step 4.2, D-86, `01-architecture.md` sections 8 and 9,
`fefat_app.cli`):

    fefat up

It reads `config.toml`, refusing a bind address other than 127.0.0.1 before anything starts;
migrates the app's database; asks for a password on its first run, typed twice at a prompt that
does not echo it; sends the server's log to `<FEFAT_HOME>/logs/server.log`; and serves the app
with uvicorn in its own process, on 127.0.0.1 alone, at the port of `config.toml`, 8765 by
default, until Ctrl+C. uvicorn trusts no forwarded header, since every client of a loopback
server is 127.0.0.1, and one could claim HTTPS that way."""

import argparse
import os
from pathlib import Path

import uvicorn

from fefat.config import Settings, resolve_paths
from fefat_app.container import opened_container
from fefat_app.http.app import create_app
from fefat_app.http.server_log import configure_server_log
from fefat_app.http.web_app import built_web_app_dir
from fefat_app.password_commands import typed_new_password

EXIT_OK = 0


def serve(arguments: argparse.Namespace) -> int:
    """Start the local server (module docstring)."""
    paths = resolve_paths(os.environ)
    with opened_container(paths) as container:
        if not container.logins.password_is_set():
            print("FEAT has no password yet: set the one its login will ask for.")
            container.logins.set_password(typed_new_password())
        log_file = configure_server_log(paths.logs_dir)
        web_app = built_web_app_dir()
        _announce(container.settings, log_file, web_app)
        uvicorn.run(
            create_app(container, web_app),
            host=container.settings.bind_address,
            port=container.settings.port,
            log_config=None,
            access_log=False,
            server_header=False,
            proxy_headers=False,
        )
    return EXIT_OK


def _announce(settings: Settings, log_file: Path, web_app: Path | None) -> None:
    address = f"http://{settings.bind_address}:{settings.port}"
    print(f"FEAT serves {address} to this computer alone; stop it with Ctrl+C.")
    print(
        f"  The API's docs: {address}/docs, where you log in; a request there that changes "
        "something needs the csrf_token of GET /v1/me under Authorize, or an API token of "
        "`fefat token create`."
    )
    print(f"  The web app: {'built, at ' + address if web_app else 'not built yet'}.")
    print(f"  The server's log: {log_file}", flush=True)
