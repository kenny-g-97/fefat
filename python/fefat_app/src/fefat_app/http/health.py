"""`GET /v1/healthz` and `GET /v1/version` (step 4.2, `01-architecture.md` section 7), which need
no login: whether the server answers, and the versions it runs."""

from typing import Literal

import fefat_engine
from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

import fefat
import fefat_app
from fefat_app.http.api_prefix import API_PREFIX

router = APIRouter(prefix=API_PREFIX, tags=["health"])


class Health(BaseModel):
    """The server answers."""

    model_config = ConfigDict(frozen=True)

    status: Literal["ok"] = "ok"


class Versions(BaseModel):
    """The versions the server runs: the app's, the SDK's, and the engine's three, which every
    run records (`02-engine-and-data.md` section 4)."""

    model_config = ConfigDict(frozen=True)

    fefat_app: str
    fefat: str
    engine: int
    fill_model: int
    artifact_schema: int


@router.get("/healthz")
def health() -> Health:
    """Whether the server answers; no login needed."""
    return Health()


@router.get("/version")
def version() -> Versions:
    """The versions the server runs; no login needed."""
    return Versions(
        fefat_app=fefat_app.__version__,
        fefat=fefat.__version__,
        engine=fefat_engine.ENGINE_VERSION,
        fill_model=fefat_engine.FILL_MODEL_VERSION,
        artifact_schema=fefat_engine.ARTIFACT_SCHEMA_VERSION,
    )
