"""The demo job (step 4.4): it counts seconds, one a second, reporting each, for the tests of the
jobs and for the builder's check of the progress bar, which survives a reload and stops on
Cancel."""

import time
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from fefat_app.jobs.progress import JobProgress


class DemoPayload(BaseModel):
    """What a demo job counts: its seconds."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    seconds: int = Field(ge=1)


def run_demo(payload: Mapping[str, Any], progress: JobProgress) -> dict[str, Any]:
    """Count the payload's seconds, reporting after each, the chunk between two checks of a
    request to stop; what was counted."""
    seconds = DemoPayload.model_validate(payload).seconds
    for counted in range(1, seconds + 1):
        time.sleep(1)
        progress.advance(100 * counted / seconds, f"Counted {counted} of {seconds}", count=counted)
    return {"counted": seconds}
