"""The web's copy of a reproduction's verdicts (step 5.10): the run page parses a `reproduce` job's
result with zod, where a verdict it does not know fails the whole answer, so the copy is held
equal to the app's enum."""

import re
from pathlib import Path

from fefat_app.reproductions import ReproductionVerdict

REPRODUCTIONS = Path(__file__).resolve().parents[2] / "web" / "src" / "api" / "reproductions.ts"


def test_the_webs_verdicts_are_the_apps() -> None:
    found = re.search(
        r"const VERDICTS = \[(.*?)\]", REPRODUCTIONS.read_text(encoding="utf-8"), re.DOTALL
    )

    assert found is not None, f"Expected the verdicts in {REPRODUCTIONS.name}, got none."
    assert re.findall(r'"([a-z_]+)"', found.group(1)) == [
        each.value for each in ReproductionVerdict
    ]
