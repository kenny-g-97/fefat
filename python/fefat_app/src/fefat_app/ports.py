"""The app's seams (`01-architecture.md` section 10, `08-code-design.md` section 1, D-27): each a
`typing.Protocol` that an adapter implements, built once in `fefat_app.container` and passed to
what uses it, so that swapping an adapter is a module of its own and a line of the container.

The credential store is the first (step 4.1); the executor, the dispatcher, the blob store, the
agent's runtime, and the licence arrive with the steps that first use them."""

from enum import StrEnum
from typing import Protocol


class SecretName(StrEnum):
    """The secrets FEFAT keeps, each the key of a service it calls: the agent's model provider
    (Phase 8) and a market data vendor (D-37). The list is closed, since a credential store
    cannot list what it holds; a step that calls another service adds its name."""

    ANTHROPIC = "anthropic"
    DATABENTO = "databento"


class CredentialStore(Protocol):
    """Where the secrets live: the operating system's credential store, never `config.toml` or
    another file FEFAT writes (`01-architecture.md` section 8)."""

    def get(self, name: SecretName) -> str | None:
        """The secret `name`, or None where none is stored."""
        ...

    def set(self, name: SecretName, value: str) -> None:
        """Store `value` as the secret `name`, in place of any stored before; an empty value is
        refused."""
        ...

    def delete(self, name: SecretName) -> None:
        """Remove the secret `name`, refused where none is stored."""
        ...
