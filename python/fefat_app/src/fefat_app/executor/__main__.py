"""`python -m fefat_app.executor --memory-bytes N [folder]` (step 4.5): the runner, which limits
its own memory where Windows does not, before the SDK is imported, then serves the executor:
`folder`'s execution alone, or each folder read from stdin (`fefat_app.executor.runner`)."""

import argparse
import sys
from pathlib import Path


def main(arguments: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m fefat_app.executor",
        description=(
            "Run the trader's code for FEAT's executor: the execution of FOLDER, or, without "
            "it, of each folder read from stdin until stdin ends."
        ),
    )
    parser.add_argument(
        "--memory-bytes",
        type=int,
        required=True,
        help="the memory the runner may take, limited here on Linux and macOS",
    )
    parser.add_argument("folder", type=Path, nargs="?", help="the folder of one execution")
    parsed = parser.parse_args(arguments)
    limit_memory(parsed.memory_bytes)
    from fefat_app.executor.runner import serve

    return serve(parsed.folder)


def limit_memory(memory_bytes: int) -> None:
    """Cap this process's address space at `memory_bytes`, past which an allocation fails as a
    `MemoryError`, on Linux and macOS; on Windows the Job Object the runner joined before it ran
    caps what its processes commit (`fefat_app.executor.windows_job`)."""
    if sys.platform == "win32":
        return
    import resource

    resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
