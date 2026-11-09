"""The environment a runner starts with (step 4.5, the step's amendment of D-83): the variables of
the server's environment a program needs to run, by name, FEFAT's folders, and keyring's null
backend, which keeps nothing, so that no key, token, or password the server's environment holds
reaches the trader's code, and a snippet asking keyring for a key gets none. A list of what is
kept rather than of what is dropped, since a secret's name follows no rule, such as a database's
URL holding its password. It keeps the trader's code from what the server knows, not from the
machine: a program can still read the Windows credential store through the system's own
interfaces (`fefat_app.executor`)."""

from collections.abc import Mapping

from fefat.config import (
    ALLOW_DATA_DIR_IN_GIT_TREE_VARIABLE,
    DATA_DIR_VARIABLE,
    HOME_VARIABLE,
    FefatPaths,
    resolve_paths,
)

PASSED_ON = frozenset(
    {
        "PATH",
        "PYTHONPATH",
        "SYSTEMROOT",
        "SYSTEMDRIVE",
        "WINDIR",
        "COMSPEC",
        "PATHEXT",
        "TEMP",
        "TMP",
        "USERPROFILE",
        "HOMEDRIVE",
        "HOMEPATH",
        "APPDATA",
        "LOCALAPPDATA",
        "PROGRAMDATA",
        "NUMBER_OF_PROCESSORS",
        "PROCESSOR_ARCHITECTURE",
        "HOME",
        "XDG_DATA_HOME",
        "TMPDIR",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "TZ",
        HOME_VARIABLE,
        DATA_DIR_VARIABLE,
        ALLOW_DATA_DIR_IN_GIT_TREE_VARIABLE,
    }
)
"""The variables a runner keeps, by their names in capitals, the case Windows ignores: what
Windows, a POSIX system, and Python need to run a program, find the workspace's packages, and
find the user's folders, and FEFAT's folders with its consent to a data folder in a git working
tree, none of them a secret."""
KEYRING_BACKEND_VARIABLE = "PYTHON_KEYRING_BACKEND"
NULL_KEYRING = "keyring.backends.null.Keyring"


def scrubbed_environment(paths: FefatPaths, environment: Mapping[str, str]) -> dict[str, str]:
    """The variables of `environment` a runner keeps (`PASSED_ON`), keyring's null backend, and
    Python's UTF-8 mode, in which the runner reads the folders it is sent and writes its reports.
    FEFAT's folders stay as `environment` names them where they resolve to `paths`, so that a
    runner resolves the platform's default home as the server does, which no git working tree
    around it refuses (D-85), and are set to `paths` otherwise."""
    kept = {name: value for name, value in environment.items() if name.upper() in PASSED_ON}
    if resolve_paths(kept) != paths:
        kept |= {HOME_VARIABLE: str(paths.home), DATA_DIR_VARIABLE: str(paths.data_dir)}
    return {**kept, KEYRING_BACKEND_VARIABLE: NULL_KEYRING, "PYTHONUTF8": "1"}
