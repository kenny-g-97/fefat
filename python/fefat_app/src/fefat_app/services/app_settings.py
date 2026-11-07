"""The settings page's settings (step 4.2, D-86, `01-architecture.md` section 8): those of
`config.toml`, shown read-only, since the server reads them before its database opens; and the
secrets, which the page writes to the operating system's credential store and never reads back,
so that a secret's value never leaves the server."""

from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from fefat.config import Settings
from fefat_app.ports import CredentialStore, SecretName


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
    """The settings the page shows: the server's, from `config.toml`, and each secret's
    state."""

    model_config = ConfigDict(frozen=True)

    server: Settings
    secrets: tuple[SecretStatus, ...]


class SettingsChange(BaseModel):
    """A change of the settings: a secret named with a value stores it, one named with null
    removes it, and one left out stays as it is."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    secrets: dict[SecretName, Annotated[SecretStr, Field(min_length=1)] | None]


def current_settings(settings: Settings, credentials: CredentialStore) -> AppSettings:
    """The settings of `config.toml` and whether `credentials` holds each secret."""
    statuses = tuple(
        SecretStatus(
            name=name,
            state=SecretState.MISSING if credentials.get(name) is None else SecretState.STORED,
        )
        for name in SecretName
    )
    return AppSettings(server=settings, secrets=statuses)


def apply_settings_change(
    change: SettingsChange, settings: Settings, credentials: CredentialStore
) -> AppSettings:
    """Store and remove the secrets `change` names; the settings after it."""
    for name, value in change.secrets.items():
        if value is not None:
            credentials.set(name, value.get_secret_value())
        elif credentials.get(name) is not None:
            credentials.delete(name)
    return current_settings(settings, credentials)
