"""The settings page's settings (steps 4.2 and 4.3, D-86, `01-architecture.md` section 8): those
of `config.toml` and the data folder, shown read-only, since the server reads them before its
database opens; the theme, which the database keeps; and the secrets, which the page writes to
the operating system's credential store and never reads back, so that a secret's value never
leaves the server."""

from enum import StrEnum
from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from fefat.config import Settings
from fefat_app.ports import CredentialStore, Preferences, SecretName, Theme


class SecretState(StrEnum):
    """Whether the credential store holds a secret."""

    STORED = "stored"
    MISSING = "missing"


class SecretStatus(BaseModel):
    """A secret by its name, with whether it is stored, never with its value."""

    model_config = ConfigDict(frozen=True)

    name: SecretName
    state: SecretState


class AppSettings(BaseModel):
    """The settings the page shows: the server's, from `config.toml`, the data folder, the
    theme, and each secret's state."""

    model_config = ConfigDict(frozen=True)

    server: Settings
    data_dir: Path
    theme: Theme
    secrets: tuple[SecretStatus, ...]


type SecretChanges = dict[SecretName, Annotated[SecretStr, Field(min_length=1)] | None]
"""The secrets a change names, each with a value to store or null to remove it."""


def no_secret_changes() -> SecretChanges:
    """A change that names no secret."""
    return {}


class SettingsChange(BaseModel):
    """A change of the settings: a secret named with a value stores it, one named with null
    removes it, and one left out stays as it is; a theme, when given, replaces the theme."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    secrets: SecretChanges = Field(default_factory=no_secret_changes)
    theme: Theme | None = None


def current_settings(
    settings: Settings, data_dir: Path, credentials: CredentialStore, preferences: Preferences
) -> AppSettings:
    """The settings of `config.toml`, the data folder, the theme, and whether `credentials`
    holds each secret."""
    statuses = tuple(
        SecretStatus(
            name=name,
            state=SecretState.MISSING if credentials.get(name) is None else SecretState.STORED,
        )
        for name in SecretName
    )
    return AppSettings(
        server=settings, data_dir=data_dir, theme=preferences.theme(), secrets=statuses
    )


def apply_settings_change(
    change: SettingsChange,
    settings: Settings,
    data_dir: Path,
    credentials: CredentialStore,
    preferences: Preferences,
) -> AppSettings:
    """Store and remove the secrets `change` names and keep its theme; the settings after it."""
    for name, value in change.secrets.items():
        if value is not None:
            credentials.set(name, value.get_secret_value())
        elif credentials.get(name) is not None:
            credentials.delete(name)
    if change.theme is not None:
        preferences.replace_theme(change.theme)
    return current_settings(settings, data_dir, credentials, preferences)
