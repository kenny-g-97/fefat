"""`GET` and `PUT /v1/settings` (steps 4.2 and 4.3, D-86, `01-architecture.md` section 7), behind
the login, over `fefat_app.services.app_settings`: secrets go in and never come out, and the
theme stays chosen."""

from fastapi import APIRouter, Depends

from fefat_app.http.api_prefix import API_PREFIX
from fefat_app.http.dependencies import ContainerDependency, the_identity
from fefat_app.http.problems import problem_responses
from fefat_app.services.app_settings import (
    AppSettings,
    SettingsChange,
    apply_settings_change,
    current_settings,
)

router = APIRouter(prefix=API_PREFIX, tags=["settings"], dependencies=[Depends(the_identity)])


@router.get("/settings", responses=problem_responses(401))
def read_settings(container: ContainerDependency) -> AppSettings:
    """The settings of `config.toml` and the data folder, which the page shows read-only, the
    theme, and whether each secret is stored, never its value."""
    return current_settings(
        container.settings, container.paths.data_dir, container.credentials, container.preferences
    )


@router.put("/settings", responses=problem_responses(401, 403, 422))
def change_settings(change: SettingsChange, container: ContainerDependency) -> AppSettings:
    """Store each secret named with a value in the operating system's credential store, remove
    each named with null, and keep the theme when one is given; the settings after the change,
    never a secret's value."""
    return apply_settings_change(
        change,
        container.settings,
        container.paths.data_dir,
        container.credentials,
        container.preferences,
    )
