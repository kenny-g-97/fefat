"""The leak detector's report (step 3.4, `fefat.features.validation`): what a validation ran on, each
cut compared, the start check, and the lint's findings, kept as JSON beside the feature's versions
(`fefat.features.versions.validation_file`), with its verdict and the words that explain it.

A report passes when no cut changed a value before it, the start check moved the start and
agreed, each output had values compared at one cut at least (`MINIMUM_COMPARED`), and the lint
found no data a feature reads itself or holds from outside it, and no label it computes; the
lint's other findings are warnings, which a report that passes shows as `PASSED WITH WARNINGS`."""

from collections.abc import Mapping
from datetime import date, datetime
from typing import Any

from fefat.features.cache_evaluation import Difference
from fefat.features.cuts import CutKind
from fefat.features.source_lint import LintFinding
from fefat.market.calendar import utc_text
from fefat.market.schema import FrozenModel

MINIMUM_COMPARED = 1
"""The values of each output, non-null on both sides, that the cuts must have compared, at one
of them at least: below it the report fails, so that a warm-up longer than the data compares
nothing and passes nothing (D-71)."""


class CutResult(FrozenModel):
    """A cut compared: its instant and kinds, the values of each output it compared, and where
    the values before it first differ from the whole range's, None where they agree. A cut that
    compares no value of an output, early in a window whose warm-up reaches past the data or
    before an output null for whole sessions by design shows one, decides nothing alone
    (`ValidationReport.uncompared`)."""

    instant: int
    kinds: tuple[CutKind, ...]
    compared: dict[str, int]
    difference: Difference | None

    @property
    def passed(self) -> bool:
        return self.difference is None

    def __str__(self) -> str:
        at = f"at {utc_text(self.instant)} ({', '.join(self.kinds)})"
        found = self.difference
        if found is not None:
            return (
                f"{at}: {found.output} at {utc_text(found.ts_close)} differs, with the data after "
                f"the cut against without it: {found.apart()}"
            )
        return f"{at}: {_agreement(self.compared)}"


class StartCheck(FrozenModel):
    """The start check (`fefat.features.validation`): the first trade date of the whole range's
    bars and of the later start's, the trade date from which their values were compared, the
    values of each output compared, and where they first differ, None where they agree. It passes
    where they agree and the later start lies after the whole range's: a start the data does not
    let move checks nothing."""

    whole_from: date
    later_from: date
    compared_from: date
    compared: dict[str, int]
    difference: Difference | None

    @property
    def passed(self) -> bool:
        return self.difference is None and self.later_from > self.whole_from

    def __str__(self) -> str:
        read = f"from {self.compared_from}, read from {self.whole_from} and from {self.later_from}"
        found = self.difference
        if self.later_from <= self.whole_from:
            return (
                f"{read}: the start did not move, since the data begins on {self.whole_from}; "
                "validate a window with more data before its middle"
            )
        if found is not None:
            return (
                f"{read}: {found.output} at {utc_text(found.ts_close)} differs: {found.apart()}, "
                "so the feature remembers more than its warm-up"
            )
        return f"{read}: {_agreement(self.compared)}"


class FeatureRead(FrozenModel):
    """A feature the validated feature reads, as `reads` gave it: its name, its content hash, and
    its parameters, so that the validation repeats (D-11)."""

    name: str
    hash: str
    parameters: dict[str, Any]


class ValidationReport(FrozenModel):
    """A validation of a feature with its parameters, and the features it reads with theirs, on an
    instrument's signal bars of a timeframe over a window of trade dates, with the seed and the
    numbers of stops and random cuts that drew its cuts (module docstring)."""

    feature: str
    hash: str
    parameters: dict[str, Any]
    reads: tuple[FeatureRead, ...]
    instrument: str
    timeframe: str
    provider: str
    start: date
    end: date
    seed: int
    stops: int
    random_cuts: int
    cuts: tuple[CutResult, ...]
    start_check: StartCheck
    lint: tuple[LintFinding, ...]
    created_at: datetime

    @property
    def passed(self) -> bool:
        fails = any(finding.rule.fails_validation for finding in self.lint)
        agrees = not self.failing_cuts() and self.start_check.passed
        return agrees and not self.uncompared() and not fails

    def failing_cuts(self) -> tuple[CutResult, ...]:
        """The cuts that changed a value before them, in order of instant."""
        return tuple(cut for cut in self.cuts if not cut.passed)

    def first_failure(self) -> CutResult | None:
        """The first failing cut, with the first row whose value it changed; None when none
        fails."""
        failing = self.failing_cuts()
        return failing[0] if failing else None

    def uncompared(self) -> list[str]:
        """The outputs no cut compared a value of, as when a warm-up longer than the data leaves
        none; the start check, which reads the same data after each cut, does not count."""
        outputs = self.start_check.compared
        return _missing(
            {output: max(cut.compared[output] for cut in self.cuts) for output in outputs}
        )

    def summary(self) -> str:
        """The report in words: the verdict, the first failing cut, the start check, the outputs
        never compared, and the lint's findings, each on a line of its own."""
        named = ", ".join(f"{name}={value!r}" for name, value in self.parameters.items())
        failing = self.failing_cuts()
        cuts = (
            f"cuts: {len(failing)} of {len(self.cuts)} fail, the first {failing[0]}"
            if failing
            else f"cuts: none of {len(self.cuts)} fails"
        )
        missing = self.uncompared()
        never = (
            f"values: no value of {', '.join(missing)} compared at any cut, as a warm-up longer "
            "than the data leaves none, or an input without data, such as prints without a side; "
            "validate a window with more data before it, or with data in every input"
        )
        found = [f"lint: {finding}" for finding in self.lint] or ["lint: no finding"]
        return "\n".join(
            [
                f"{self.feature}({named}) on {self.instrument} {self.timeframe} from {self.start} "
                f"to {self.end}, seed {self.seed}: {self._verdict()}",
                cuts,
                f"start check {self.start_check}",
                *([never] if missing else []),
                *found,
            ]
        )

    def _verdict(self) -> str:
        if not self.passed:
            return "FAILED"
        if self.lint:
            return "PASSED WITH WARNINGS"
        return "PASSED"


def _missing(compared: Mapping[str, int]) -> list[str]:
    """The outputs with fewer values compared than `MINIMUM_COMPARED`."""
    return [output for output, count in compared.items() if count < MINIMUM_COMPARED]


def _agreement(compared: Mapping[str, int]) -> str:
    missing = _missing(compared)
    if missing:
        return f"no value of {', '.join(missing)} before it to compare"
    return f"{sum(compared.values()):,} values agree"
