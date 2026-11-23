"""The import wizard (step 5.12, `01-architecture.md` section 7, D-93): the profiles it offers, the
presets and those saved; the files the browser sends, kept as uploads, their names checked first
(`fefat_app.services.uploads`); a preview, of a file's table or of what its import would do, run
by the executor and answered as it comes; and the import, of one file or batch, or of several
files in one round through one profile (D-102), queued as an `import` job. A path is
resolved under the import roots (`fefat_app.import_sources`), and an upload's file found by its
id, before the executor reads either; a profile a request names is looked up among the presets
and the saved profiles alone, never read as a path, as `load_profile` reads a name ending in
`.yaml`; a profile given whole is refused under a name another profile has before anything runs,
and is kept once its import has written."""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from fefat.config import FefatPaths, Settings
from fefat.market.importers.profiles import (
    ImportProfile,
    preset_profiles,
    profile_is_saved,
    saved_profiles,
)
from fefat_app.execution import (
    ExecutionFailed,
    ExecutionLimits,
    ExecutionProgress,
    ExecutionResult,
    ExecutionTimedOut,
    keep_running,
)
from fefat_app.import_sources import confined_path
from fefat_app.imports import (
    BatchImportAsked,
    BatchRequest,
    FileImportAsked,
    FileRequest,
    FilesImportAsked,
    ImportAsked,
    ImportJobPayload,
    ImportPreviewAnswer,
    ImportPreviewOutput,
    ImportPreviewSpec,
    ImportSource,
    ImportSpec,
    ListedProfile,
    NamedProfile,
    PreviewAsked,
    ProfileChoice,
    ProfileOrigin,
    ProfileRefusedError,
    ReadKind,
    RefusedImport,
    RoundFile,
    TableAsked,
    TableRequest,
    UploadedFile,
    UploadSource,
)
from fefat_app.job_models import Job, JobKind
from fefat_app.ports import Executor, UploadRecords
from fefat_app.services.jobs import Jobs
from fefat_app.services.uploads import checked_upload_name

PREVIEW_LIMITS = ExecutionLimits(timeout_seconds=30 * 60, memory_bytes=8 * 1024**3)
"""What a preview may take: half an hour and 8 GiB, as it reads the whole file (your answer at
step 5.12's plan)."""
IMPORT_LIMITS = ExecutionLimits(timeout_seconds=6 * 60 * 60, memory_bytes=8 * 1024**3)
"""What an import's job may take: six hours and 8 GiB, a backtest's limits."""


class NoSuchProfileError(ValueError):
    """A profile's name that no preset and no saved profile has."""

    def __init__(self, name: str, known: list[str]) -> None:
        super().__init__(
            f"Expected the name of a preset or a saved profile ({', '.join(known)}), got {name!r}."
        )


@dataclass(frozen=True)
class Imports:
    """The wizard's work over the executor, the jobs, and the uploads, in the folders of `paths`
    and within the import roots and the upload suffixes of `settings`."""

    executor: Executor
    jobs: Jobs
    uploads: UploadRecords
    paths: FefatPaths
    settings: Settings

    def profiles(self) -> tuple[ListedProfile, ...]:
        """The presets, then the profiles saved under `profiles/`, each by its name."""
        presets = preset_profiles().values()
        saved = saved_profiles(self.paths.profiles_dir).values()
        return (
            *(ListedProfile(origin=ProfileOrigin.PRESET, profile=profile) for profile in presets),
            *(ListedProfile(origin=ProfileOrigin.SAVED, profile=profile) for profile in saved),
        )

    async def keep_upload(self, name: str, chunks: AsyncIterator[bytes]) -> UploadedFile:
        """Keep the file `name` the browser sends in `chunks`, its name checked before a byte
        is read."""
        return await self.uploads.keep(
            checked_upload_name(name, self.settings.upload_suffixes), chunks
        )

    def preview(self, asked: PreviewAsked) -> ImportPreviewAnswer:
        """What `asked` finds, read by the executor; a preview that failed or ran out of time is
        answered as refused, with why."""
        spec = ImportPreviewSpec(request=self._request(asked), limits=PREVIEW_LIMITS)
        return _preview_answer(self.executor.run(spec, _unreported, keep_running))

    def start(self, asked: ImportAsked) -> Job:
        """Queue the import `asked` as an `import` job, its paths and its profile checked
        first."""
        if isinstance(asked, FilesImportAsked):
            payload = self._round(asked)
        else:
            spec = ImportSpec(request=self._import_request(asked), limits=IMPORT_LIMITS)
            payload = ImportJobPayload(spec=spec, upload_id=_upload_id(asked.source))
        return self.jobs.start(JobKind.IMPORT, payload.model_dump(mode="json"))

    def start_again(self, job: Job) -> Job:
        """The import of `job`'s inputs queued again (step 5.19), or the same one under way,
        checked as a new import is: each file an upload still kept or a path still under the
        import roots, and a whole profile it would keep free of a saved one's name; refused
        with `NoSuchUploadError`, `PathRefusedError`, or `ProfileRefusedError`."""
        settings = self.settings
        payload = ImportJobPayload.model_validate(job.payload)
        request = payload.spec.request
        if isinstance(request, FileRequest) and request.keep_profile:
            self._is_saved(request.profile)
        for spec, upload_id in payload.files():
            if upload_id is not None:
                self.uploads.path_of(upload_id)
                continue
            confined_path(
                str(spec.request.path),
                spec.request.kind,
                settings.import_roots,
                self.paths,
                settings.upload_suffixes,
            )
        return self.jobs.start_unless_under_way(job.kind, job.payload)

    def _round(self, asked: FilesImportAsked) -> ImportJobPayload:
        """A round's payload (D-102): the profile resolved once, the first file's import its
        spec, each other file's path and upload beside it."""
        profile, keep = self._profile(asked.profile)
        first, *others = (
            RoundFile(
                path=self._path(source, ReadKind.FILE),
                upload_id=_upload_id(source),
                bars_in_breaks=asked.bars_in_breaks_of(source),
            )
            for source in asked.sources
        )
        request = FileRequest(
            path=first.path,
            profile=profile,
            keep_profile=keep,
            contract=None,
            root=asked.root,
            time_zone=asked.time_zone,
            differing=asked.differing,
            bars_in_breaks=first.bars_in_breaks,
        )
        spec = ImportSpec(request=request, limits=IMPORT_LIMITS)
        return ImportJobPayload(
            spec=spec, upload_id=first.upload_id, others=tuple(others), in_round=True
        )

    def _request(self, asked: PreviewAsked) -> TableRequest | FileRequest | BatchRequest:
        if isinstance(asked, TableAsked):
            return TableRequest(path=self._path(asked.source, ReadKind.TABLE), layout=asked.layout)
        return self._import_request(asked)

    def _import_request(
        self, asked: FileImportAsked | BatchImportAsked
    ) -> FileRequest | BatchRequest:
        if isinstance(asked, BatchImportAsked):
            path = self._path(asked.source, ReadKind.DATABENTO)
            return BatchRequest(path=path, differing=asked.differing)
        profile, keep = self._profile(asked.profile)
        return FileRequest(
            path=self._path(asked.source, ReadKind.FILE),
            profile=profile,
            keep_profile=keep,
            contract=asked.contract,
            root=asked.root,
            time_zone=asked.time_zone,
            differing=asked.differing,
            bars_in_breaks=asked.bars_in_breaks,
        )

    def _path(self, source: ImportSource, kind: ReadKind) -> Path:
        if isinstance(source, UploadSource):
            return self.uploads.path_of(source.upload_id)
        settings = self.settings
        return confined_path(
            source.path, kind, settings.import_roots, self.paths, settings.upload_suffixes
        )

    def uploads_of_active_imports(self) -> frozenset[str]:
        """The folders of the uploads that queued and running imports read, which `fefat up`
        keeps, as the reaper queues an import the last server left running again."""
        payloads = (
            ImportJobPayload.model_validate(job.payload) for job in self.jobs.active(JobKind.IMPORT)
        )
        return frozenset(
            str(upload_id)
            for each in payloads
            for _, upload_id in each.files()
            if upload_id is not None
        )

    def _profile(self, choice: ProfileChoice) -> tuple[ImportProfile, bool]:
        """The profile `choice` names or gives, and whether its import keeps it: a profile
        given whole that is not saved as it is."""
        if isinstance(choice, NamedProfile):
            return self._named(choice.name), False
        return choice.profile, not self._is_saved(choice.profile)

    def _is_saved(self, profile: ImportProfile) -> bool:
        """Whether `profile` is saved as it is; `ProfileRefusedError` for a name it may not
        keep, such as a saved profile's that holds another."""
        try:
            return profile_is_saved(profile, self.paths.profiles_dir)
        except ValueError as refused:
            raise ProfileRefusedError(str(refused)) from refused

    def _named(self, name: str) -> ImportProfile:
        """The preset named `name`, else the saved profile, the saved profiles read only for a
        name no preset has, so that a saved file edited by hand refuses only what reads it."""
        presets = preset_profiles()
        if name in presets:
            return presets[name]
        try:
            saved = saved_profiles(self.paths.profiles_dir)
        except ValueError as refused:
            raise ProfileRefusedError(str(refused)) from refused
        if name in saved:
            return saved[name]
        raise NoSuchProfileError(name, [*presets, *saved])


def _upload_id(source: ImportSource) -> UUID | None:
    """The upload `source` names, if it names one."""
    return source.upload_id if isinstance(source, UploadSource) else None


def _preview_answer(result: ExecutionResult) -> ImportPreviewAnswer:
    if isinstance(result, ExecutionTimedOut):
        minutes = PREVIEW_LIMITS.timeout_seconds / 60
        return RefusedImport(
            message=f"Expected the file read within {minutes:g} minutes, got it still being read "
            "then: it was stopped. Import a file of fewer records."
        )
    if isinstance(result, ExecutionFailed):
        return RefusedImport(message=_failure(result))
    output = result.output
    if not isinstance(output, ImportPreviewOutput):
        raise ValueError(
            f"Expected the output of an import's preview, got that of a {output.kind}."
        )
    return output.answer


def _failure(failed: ExecutionFailed) -> str:
    """Why the file could not be read, the last line of the runner's error, such as
    `MemoryError` for a file, or an archive's content, past the preview's memory."""
    lines = failed.error.strip().splitlines()
    last = lines[-1] if lines else "the runner gave no error"
    if not last.startswith(MemoryError.__name__):
        return f"Expected the file read, got a failure: {last}"
    gibibytes = PREVIEW_LIMITS.memory_bytes / 1024**3
    return (
        f"Expected the file read within {gibibytes:g} GiB of memory, got more: a file, or an "
        "archive's content, that large is imported in parts."
    )


def _unreported(progress: ExecutionProgress) -> None:
    """A preview reports nothing its caller shows."""
