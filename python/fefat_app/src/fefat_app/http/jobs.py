"""`GET /v1/jobs`, `GET /v1/jobs/{job_id}`, `POST /v1/jobs/{job_id}/cancel`, and `POST
/v1/jobs/demo` (step 4.4, `01-architecture.md` sections 6 and 7): the web app's jobs drawer and
home page list the jobs and cancel one, and its settings page starts the demo job, over
`fefat_app.services.jobs`; a login session or an API token may do each. A job's progress as it
runs comes from its stream, `GET /v1/streams/job:<id>`."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from fefat_app.http.api_prefix import API_PREFIX
from fefat_app.http.dependencies import ContainerDependency, the_identity
from fefat_app.http.problems import problem_responses
from fefat_app.ports import Job
from fefat_app.services.jobs import NoSuchJobError

router = APIRouter(prefix=API_PREFIX, tags=["jobs"], dependencies=[Depends(the_identity)])


class DemoJobRequest(BaseModel):
    """How many seconds a demo job counts, one a second, from 1 to an hour."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    seconds: int = Field(ge=1, le=3600)


@router.get("/jobs", responses=problem_responses(401))
def recent_jobs(container: ContainerDependency) -> tuple[Job, ...]:
    """The newest jobs, newest first, at most a hundred."""
    return container.jobs.recent()


@router.get("/jobs/{job_id}", responses=problem_responses(401, 404, 422))
def job_by_id(job_id: str, container: ContainerDependency) -> Job:
    """The job `job_id`; refused with 404 where no job has the id."""
    try:
        return container.jobs.by_id(job_id)
    except NoSuchJobError as refused:
        raise HTTPException(404, str(refused)) from refused


@router.post("/jobs/{job_id}/cancel", responses=problem_responses(401, 403, 404, 422))
def cancel_job(job_id: str, container: ContainerDependency) -> Job:
    """Cancel the job `job_id`: at once while it is queued; while it runs, it is asked to stop,
    which its worker does at its next report, or which the server makes it do ten seconds
    later; an ended job is given as it is. Refused with 404 where no job has the id."""
    try:
        return container.jobs.cancel(job_id)
    except NoSuchJobError as refused:
        raise HTTPException(404, str(refused)) from refused


@router.post("/jobs/demo", status_code=202, responses=problem_responses(401, 403, 422))
def start_demo_job(request: DemoJobRequest, container: ContainerDependency) -> Job:
    """Start a demo job that counts `seconds`, reporting each; it is queued until a worker of
    the pool is free."""
    return container.jobs.start_demo(request.seconds)
