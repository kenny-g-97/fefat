"""`python -m fefat_xcheck nautilus <comparison folder>` runs NautilusTrader's side;
`python -m fefat_xcheck report <xcheck folder> <report.md>` compares every engine's trades with
FEFAT's and writes the report, exiting 1 while any difference is `unknown`."""

import argparse
from pathlib import Path

from fefat_xcheck.comparison import write_report
from fefat_xcheck.nautilus_side import run_nautilus_side


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fefat_xcheck", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    nautilus = commands.add_parser("nautilus", help="run NautilusTrader's side of a comparison")
    nautilus.add_argument(
        "folder", type=Path, help="the comparison folder, with fefat/ and the cut"
    )
    report = commands.add_parser("report", help="compare the engines' trades and write the report")
    report.add_argument("xcheck", type=Path, help="the xcheck folder holding every comparison")
    report.add_argument("out", type=Path, help="where to write the report")
    arguments = parser.parse_args(argv)
    if arguments.command == "nautilus":
        facts = run_nautilus_side(arguments.folder)
        print(f"NautilusTrader {facts['nautilus_trader']} ran on {facts['bars']} bars")
        return 0
    unknown = write_report(arguments.xcheck, arguments.out)
    print(f"Wrote {arguments.out} with {unknown} unknown differences")
    return 1 if unknown else 0


if __name__ == "__main__":
    raise SystemExit(main())
